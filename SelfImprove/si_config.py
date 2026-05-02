# -*- coding: utf-8 -*-
"""
SelfImprove — Configuration loader V10.5
Lit config.toml et expose les paramètres à tous les modules SelfImprove.
Conforme aux conventions LCCA (skill 001) : Path, snake_case, pas de f-strings dans les logs.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    try:
        import tomli as tomllib  # fallback pip install tomli
    except ImportError:
        tomllib = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

_SELF_IMPROVE_DIR = Path(__file__).parent
_CONFIG_FILE = _SELF_IMPROVE_DIR / "config.toml"

_DEFAULT: dict[str, Any] = {
    "general": {"coupling_mode": 2},
    "observer": {
        "interval_sec": 60,
        "wal_dir": str(Path("D:/LLMCodeAgent/transactions")),
        "log_file": str(Path("D:/LLMCodeAgent/logs/lcca.log")),
        "test_results_file": str(Path("D:/LLMCodeAgent/tests/last_results.json")),
        "patterns_file": str(_SELF_IMPROVE_DIR / "observer_patterns.json"),
    },
    "orchestrator": {
        "observation_window": 3,
        "observation_max_age_sec": 600,
        "rules_file": str(_SELF_IMPROVE_DIR / "orchestrator_rules.json"),
    },
    "auto_fix": {
        "min_coverage": 0.60,
        "failure_cooldown_sec": 3600,
        "auto_push": False,
    },
    "paths": {
        "self_improve_dir": str(_SELF_IMPROVE_DIR),
        "observations_dir": str(_SELF_IMPROVE_DIR / "observations"),
        "auto_fixes_dir": str(_SELF_IMPROVE_DIR / "auto_fixes"),
        "patterns_dir": str(_SELF_IMPROVE_DIR / "patterns"),
        "actions_log": str(_SELF_IMPROVE_DIR / "actions.log"),
        "pending_actions": str(_SELF_IMPROVE_DIR / "pending_actions.json"),
        "borgnes_map": str(_SELF_IMPROVE_DIR / "borgnes_map.json"),
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Fusionne override dans base récursivement."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load_config() -> dict[str, Any]:
    """Charge config.toml et fusionne avec les valeurs par défaut.

    Retourne toujours un dict valide même si le fichier est absent ou corrompu.
    Rechargé à chaque appel — pas de cache — pour permettre la modification sans restart.
    """
    if tomllib is None:
        log.warning("tomllib non disponible — utilisation des valeurs par défaut")
        return dict(_DEFAULT)

    if not _CONFIG_FILE.exists():
        log.warning("config.toml absent (%s) — utilisation des valeurs par défaut", _CONFIG_FILE)
        return dict(_DEFAULT)

    try:
        raw = _CONFIG_FILE.read_bytes()
        parsed = tomllib.loads(raw.decode("utf-8"))
        return _deep_merge(_DEFAULT, parsed)
    except Exception as exc:  # noqa: BLE001
        log.error("Erreur lecture config.toml : %s — utilisation des valeurs par défaut", exc)
        return dict(_DEFAULT)


def get_coupling_mode() -> int:
    """Retourne le mode de couplage actuel (1, 2 ou 3)."""
    cfg = load_config()
    mode = int(cfg["general"].get("coupling_mode", 2))
    return max(1, min(3, mode))


def get_paths(cfg: dict[str, Any] | None = None) -> dict[str, Path]:
    """Retourne tous les chemins SelfImprove sous forme de Path."""
    if cfg is None:
        cfg = load_config()
    return {k: Path(v) for k, v in cfg["paths"].items()}
