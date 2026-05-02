# -*- coding: utf-8-sig -*-
"""
model_router.py — ROUTER-01
Routeur de modeles LLM pour LCCA.

Responsabilite unique : decider quel modele utiliser pour une tache donnee,
en fonction de la complexite, du type de tache et des providers online disponibles.

Interface :
    router = ModelRouter()                             # charge online_models.json
    decision = router.get_model("coding", 70, api_key) # → ModelDecision
    router.reload_config()                             # hotreload sans redemarrage

Invariants :
    - Ne modifie jamais config.py ni online_models.json
    - Les cles API arrivent en parametre — jamais lues depuis le disque ici
    - JSON invalide ou fichier absent → routing desactive, 0 exception levee
    - online=False dans le JSON → provider jamais appele
    - Pas de cle API → fallback local silencieux
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger("lcca.model_router")

# Chemin par defaut — injectable dans les tests via config_path
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "online_models.json"


@dataclass
class ModelDecision:
    """Resultat de la decision de routing."""
    model_name:    str   # "qwen3:8b" ou "moonshot-v1-8k" etc.
    provider:      str   # "ollama" | id du provider online
    is_online:     bool  # True si provider cloud
    fallback_used: bool  # True si fallback local declenche
    reason:        str   # Explication lisible (pour les logs)


class ModelRouter:
    """
    Routeur de modeles LLM.

    Charge online_models.json au demarrage. En mode degrade (fichier absent
    ou JSON invalide), se comporte comme si routing.enabled = False.
    """

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self._config_path = config_path or _DEFAULT_CONFIG_PATH
        self._cfg: dict = {}
        self._enabled: bool = False
        self._load_config()

    # ── Interface publique ────────────────────────────────────────────────────

    def get_model(
        self,
        task_type:        str,
        complexity_score: int,
        api_key:          Optional[str] = None,
    ) -> ModelDecision:
        """
        Decide quel modele utiliser.

        Args:
            task_type:        "coding" | "debug" | "spec" | "nl"
            complexity_score: 0-100 (SpecComplexityEstimator) ou 0-10 (heuristique brute)
            api_key:          cle API du provider online candidat, ou None

        Returns:
            ModelDecision avec le modele a utiliser.
        """
        # Normalise 0-100 → 0-10 (accepte aussi 0-10 directement)
        score_norm = complexity_score // 10 if complexity_score > 10 else complexity_score

        # Routing desactive → modele local par defaut
        if not self._enabled:
            return self._local_default("routing desactive")

        thresholds = self._cfg.get("routing", {}).get("thresholds", {})
        thr_heavy  = thresholds.get("use_heavy_local", 5)
        thr_online = thresholds.get("use_online", 6)

        # Tache debug → modele debug dedié
        if task_type == "debug":
            model = self._cfg_read("OLLAMA_MODEL_DEBUG") or self._cfg_read("OLLAMA_MODEL_HEAVY")
            if model:
                return ModelDecision(
                    model_name=model, provider="ollama",
                    is_online=False, fallback_used=False,
                    reason=f"debug task → {model}",
                )
            return self._local_default("debug task, pas de modele debug configure")

        # Score suffisant pour tenter un provider online
        if score_norm >= thr_online:
            decision = self._try_online(task_type, score_norm, api_key)
            if decision is not None:
                return decision
            # Fallback : essayer le modele lourd local
            heavy = self._cfg_read("OLLAMA_MODEL_HEAVY")
            if heavy:
                return ModelDecision(
                    model_name=heavy, provider="ollama",
                    is_online=False, fallback_used=True,
                    reason=f"online indisponible → fallback heavy local {heavy}",
                )
            return self._local_default("online indisponible, pas de heavy configure")

        # Score intermediaire → modele lourd local
        if score_norm >= thr_heavy:
            heavy = self._cfg_read("OLLAMA_MODEL_HEAVY")
            if heavy:
                return ModelDecision(
                    model_name=heavy, provider="ollama",
                    is_online=False, fallback_used=False,
                    reason=f"complexite {score_norm} >= {thr_heavy} → heavy local {heavy}",
                )

        return self._local_default(f"complexite {score_norm} → modele par defaut")

    def list_available_online(self) -> list[dict]:
        """Retourne les providers avec online=True (sans les cles API)."""
        providers = self._cfg.get("providers", [])
        return [
            {k: v for k, v in p.items()}
            for p in providers
            if p.get("online", False)
        ]

    def reload_config(self) -> None:
        """Relit online_models.json depuis le disque (hotreload)."""
        self._load_config()
        log.info("model_router: config rechargee depuis %s", self._config_path)

    # ── Helpers internes ──────────────────────────────────────────────────────

    def _load_config(self) -> None:
        """Charge le JSON de configuration. Mode degrade silencieux si erreur."""
        try:
            raw = self._config_path.read_text(encoding="utf-8")
            self._cfg = json.loads(raw)
            self._enabled = bool(
                self._cfg.get("routing", {}).get("enabled", False)
            )
            log.info(
                "model_router: config chargee — routing.enabled=%s, %d providers",
                self._enabled, len(self._cfg.get("providers", [])),
            )
        except FileNotFoundError:
            log.debug("model_router: %s absent — routing desactive", self._config_path)
            self._cfg = {}
            self._enabled = False
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("model_router: erreur lecture config (%s) — routing desactive", exc)
            self._cfg = {}
            self._enabled = False

    def _try_online(
        self,
        task_type:  str,
        score_norm: int,
        api_key:    Optional[str],
    ) -> Optional[ModelDecision]:
        """
        Cherche le premier provider online eligible.
        Retourne None si aucun provider ne convient (fallback a la charge de l'appelant).
        """
        if not api_key:
            log.debug("model_router: pas de cle API → online ignore")
            return None

        providers = self._cfg.get("providers", [])
        for p in providers:
            if not p.get("online", False):
                continue
            if task_type not in p.get("roles", []):
                continue
            if score_norm < p.get("min_complexity", 0):
                continue
            log.info(
                "model_router: provider online selectionne — id=%s model=%s",
                p["id"], p["model_name"],
            )
            return ModelDecision(
                model_name=p["model_name"],
                provider=p["id"],
                is_online=True,
                fallback_used=False,
                reason=(
                    f"score {score_norm} >= min_complexity {p.get('min_complexity')}"
                    f" → provider online {p['id']}"
                ),
            )
        log.debug(
            "model_router: aucun provider online eligible pour task=%s score=%d",
            task_type, score_norm,
        )
        return None

    def _local_default(self, reason: str) -> ModelDecision:
        """Retourne le modele local par defaut (OLLAMA_MODEL depuis config.py)."""
        model = self._cfg_read("OLLAMA_MODEL") or "qwen3:8b"
        return ModelDecision(
            model_name=model, provider="ollama",
            is_online=False, fallback_used=False,
            reason=reason,
        )

    @staticmethod
    def _cfg_read(key: str) -> Optional[str]:
        """Lit une cle depuis config.py sans lever d'erreur si absent."""
        try:
            import config  # type: ignore
            val = getattr(config, key, None)
            return str(val) if val else None
        except Exception:
            return None
