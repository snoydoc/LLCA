# -*- coding: utf-8 -*-
"""
SelfImprove — AutoFix Engine V10.5 (SI-04)
Corrections syntaxiques déterministes sur whitelist stricte.
Conforme aux conventions LCCA (skill 001).

Patterns supportés :
  - missing_import      : import ajouté via SmartPatcher.add_import() (AddImportTransformer)
  - coroutine_never_awaited : STUB — transformer add_await non implémenté (prévu sprint ultérieur)

Conditions bloquantes (toutes requises pour exécuter un patch) :
  1. Flag .auto_fix_enabled présent dans self_improve_dir
  2. Mode couplage >= 2
  3. pattern_id dans auto_fix_whitelist.json
  4. Fichier cible dans allowed_files du pattern
  5. Coverage >= min_coverage (pytest-cov → coverage.json, line_rate)
  6. Tests verts AVANT le patch
  7. Diff <= 5 lignes
  8. Tests verts APRÈS le patch (sinon rollback)

auto_push = False — jamais de git push automatique.
Commit sur branche auto-fix/<pattern>-YYYYMMDD-HHMMSS uniquement.
"""
from __future__ import annotations

import fnmatch
import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from SelfImprove.si_config import get_coupling_mode, load_config
from SelfImprove.si_utils import atomic_write_json, log_action

log = logging.getLogger(__name__)

# Nom du fichier de résultats coverage produit par pytest-cov
_COVERAGE_JSON = "coverage.json"


# ---------------------------------------------------------------------------
# AutoFixEngine
# ---------------------------------------------------------------------------

class AutoFixEngine:
    """Moteur de corrections déterministes sur whitelist."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self._cfg = cfg or load_config()
        self._si_dir = Path(self._cfg["paths"]["self_improve_dir"])
        self._auto_fixes_dir = Path(self._cfg["paths"]["auto_fixes_dir"])
        self._auto_fixes_dir.mkdir(parents=True, exist_ok=True)
        self._whitelist = self._load_whitelist()

    # ------------------------------------------------------------------
    # Point d'entrée
    # ------------------------------------------------------------------

    def run(self, pattern_id: str) -> str:
        """Exécute l'auto-fix pour le pattern donné.

        Retourne le statut : 'success' | 'failed' | 'skipped'.
        """
        # Guard 1 — flag .auto_fix_enabled
        if not (self._si_dir / ".auto_fix_enabled").exists():
            log.info("AutoFix désactivé (flag absent) — pattern %s ignoré", pattern_id)
            return "skipped"

        # Guard 2 — mode couplage >= 2
        if get_coupling_mode() < 2:
            log.info("AutoFix ignoré : mode couplage < 2 pour pattern %s", pattern_id)
            return "skipped"

        # Guard 3 — pattern dans whitelist
        pattern_cfg = self._find_pattern(pattern_id)
        if pattern_cfg is None:
            log.info("Pattern %s absent de la whitelist — skipped", pattern_id)
            return "skipped"

        # Récupère le signal correspondant depuis les observations
        signal = self._get_latest_signal(pattern_id)
        if signal is None:
            log.info("Aucun signal récent pour pattern %s — skipped", pattern_id)
            return "skipped"

        target_file = signal.get("file", "")
        if not target_file:
            log.info("Signal pattern %s sans champ 'file' — skipped", pattern_id)
            return "skipped"

        target_path = Path(target_file)

        # Guard 4 — fichier dans allowed_files
        if not self._is_allowed(target_path, pattern_cfg.get("allowed_files", [])):
            log.info("Fichier %s hors allowed_files pour pattern %s — skipped",
                     target_file, pattern_id)
            return "skipped"

        if not target_path.exists():
            log.warning("Fichier cible introuvable : %s", target_file)
            return "skipped"

        # Guard 5 — coverage >= min_coverage
        min_cov = self._cfg["auto_fix"]["min_coverage"]
        if not self._check_coverage(target_path, min_cov):
            log.info("Coverage < %.0f%% pour %s — failed (cooldown)", min_cov * 100, target_file)
            return "failed"

        # Guard 6 — tests verts AVANT le patch
        if not self._run_tests(target_path):
            log.info("Tests non verts avant patch sur %s — skipped", target_file)
            return "skipped"

        # Calcule le patch (ne modifie pas encore le disque)
        new_content, patch_lines = self._compute_patch(pattern_cfg, signal, target_path)
        if new_content is None:
            return "skipped"

        # Guard 7 — diff <= 5 lignes
        if patch_lines > 5:
            log.info("Patch trop grand (%d lignes) pour %s — skipped", patch_lines, target_file)
            return "skipped"

        # Snapshot pour rollback
        original_content = target_path.read_text(encoding="utf-8-sig")

        # Écriture du patch
        target_path.write_text(new_content, encoding="utf-8-sig")
        log.info("Patch appliqué sur %s (%d lignes)", target_file, patch_lines)

        # Guard 8 — tests verts APRÈS le patch
        if not self._run_tests(target_path):
            log.warning("Tests non verts après patch sur %s — rollback", target_file)
            target_path.write_text(original_content, encoding="utf-8-sig")
            self._write_patch_file(pattern_id, target_file, new_content, status="rollback")
            return "failed"

        # Sauvegarde du patch + commit git
        self._write_patch_file(pattern_id, target_file, new_content, status="success")
        self._git_commit(pattern_id, target_file)

        # Log write-ahead final
        log_action(pattern_id, "auto_fix", target_file, "success",
                   "patch applied %d lines" % patch_lines, self._cfg)

        return "success"

    # ------------------------------------------------------------------
    # Chargement de la whitelist
    # ------------------------------------------------------------------

    def _load_whitelist(self) -> list[dict]:
        whitelist_path = self._si_dir / "auto_fix_whitelist.json"
        if not whitelist_path.exists():
            log.warning("auto_fix_whitelist.json absent")
            return []
        try:
            data = json.loads(whitelist_path.read_text(encoding="utf-8"))
            return data.get("patterns", [])
        except Exception as exc:  # noqa: BLE001
            log.error("Lecture auto_fix_whitelist.json : %s", exc)
            return []

    def _find_pattern(self, pattern_id: str) -> dict | None:
        for p in self._whitelist:
            if p.get("id") == pattern_id:
                return p
        return None

    # ------------------------------------------------------------------
    # Récupération du signal le plus récent pour un pattern
    # ------------------------------------------------------------------

    def _get_latest_signal(self, pattern_id: str) -> dict | None:
        obs_dir = Path(self._cfg["paths"]["observations_dir"])
        if not obs_dir.exists():
            return None

        files = sorted(obs_dir.glob("*.json"), reverse=True)[:5]
        for f in files:
            try:
                data = json.loads(f.read_text("utf-8"))
                for sig in data.get("signals", []):
                    if sig.get("pattern") == pattern_id:
                        return sig
            except Exception as exc:  # noqa: BLE001
                log.debug("Lecture observation %s : %s", f.name, exc)
        return None

    # ------------------------------------------------------------------
    # Vérification allowed_files (fnmatch glob)
    # ------------------------------------------------------------------

    @staticmethod
    def _is_allowed(path: Path, allowed_files: list[str]) -> bool:
        if not allowed_files:
            return False
        path_str = path.as_posix()
        for pattern in allowed_files:
            if fnmatch.fnmatch(path_str, pattern) or fnmatch.fnmatch(path.name, pattern):
                return True
        return False

    # ------------------------------------------------------------------
    # Vérification coverage
    # ------------------------------------------------------------------

    def _check_coverage(self, target_path: Path, min_coverage: float) -> bool:
        """Lit coverage.json (pytest-cov) et vérifie line_rate pour le fichier cible.

        Retourne True si coverage >= min_coverage ou si le fichier coverage est absent
        (mode dégradé — on laisse passer pour ne pas bloquer).
        """
        # Cherche coverage.json dans la racine projet
        project_root = self._si_dir.parent
        cov_path = project_root / _COVERAGE_JSON
        if not cov_path.exists():
            log.debug("coverage.json absent — coverage check ignoré")
            return True  # mode dégradé : on ne bloque pas

        try:
            cov_data = json.loads(cov_path.read_text("utf-8"))
            # Format pytest-cov : {"files": {"path": {"summary": {"line_rate": 0.85}}}}
            files = cov_data.get("files", {})
            target_str = str(target_path)

            # Recherche par correspondance de suffixe (chemins absolus vs relatifs)
            for fpath, fdata in files.items():
                if fpath.endswith(target_str) or target_str.endswith(fpath) or \
                        Path(fpath).name == target_path.name:
                    line_rate = fdata.get("summary", {}).get("line_rate", 1.0)
                    if line_rate < min_coverage:
                        log.info("Coverage %.1f%% < %.1f%% pour %s",
                                 line_rate * 100, min_coverage * 100, target_str)
                        return False
                    return True

            # Fichier non référencé dans coverage.json — mode dégradé
            log.debug("Fichier %s absent de coverage.json — check ignoré", target_path.name)
            return True

        except Exception as exc:  # noqa: BLE001
            log.error("Lecture coverage.json : %s", exc)
            return True  # mode dégradé

    # ------------------------------------------------------------------
    # Exécution des tests
    # ------------------------------------------------------------------

    def _run_tests(self, target_path: Path) -> bool:
        """Lance pytest sur le fichier cible. Retourne True si tous les tests passent."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(target_path), "-x", "--quiet", "--tb=no"],
                capture_output=True,
                timeout=120,
            )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            log.warning("pytest timeout sur %s", target_path)
            return False
        except Exception as exc:  # noqa: BLE001
            log.error("_run_tests échoué : %s", exc)
            return False

    # ------------------------------------------------------------------
    # Calcul du patch (sans écriture disque)
    # ------------------------------------------------------------------

    def _compute_patch(
        self,
        pattern_cfg: dict,
        signal: dict,
        target_path: Path,
    ) -> tuple[str | None, int]:
        """Calcule le nouveau contenu du fichier et le nombre de lignes ajoutées.

        Retourne (new_content, patch_lines) ou (None, 0) si skipped.
        """
        fix_template = pattern_cfg.get("fix_template", "")
        pattern_id = pattern_cfg.get("id", "")

        if fix_template == "add_await":
            # STUB — transformer add_await non implémenté (sprint ultérieur)
            log.info("Pattern coroutine_never_awaited : transformer add_await non implémenté — skipped")
            return None, 0

        if fix_template == "add_import":
            return self._patch_missing_import(signal, target_path)

        log.warning("fix_template inconnu '%s' pour pattern %s — skipped", fix_template, pattern_id)
        return None, 0

    def _patch_missing_import(
        self,
        signal: dict,
        target_path: Path,
    ) -> tuple[str | None, int]:
        """Applique un import manquant via SmartPatcher (AddImportTransformer).

        signal doit contenir 'module' (et optionnellement 'names': list[str]).
        Retourne (new_content, patch_lines) ou (None, 0).
        """
        module = signal.get("module")
        if not module:
            log.info("Signal missing_import sans champ 'module' — skipped")
            return None, 0

        names = signal.get("names")  # list[str] ou None

        try:
            from core.smart_patcher import SmartPatcher  # import tardif

            patcher = SmartPatcher(workspace=target_path.parent)
            new_content = patcher.add_import(
                path=target_path,
                module=module,
                names=names,
            )
        except ImportError:
            # SmartPatcher/libcst indisponible — fallback template string
            new_content = self._add_import_template(target_path, module, names)
            if new_content is None:
                return None, 0

        original_lines = target_path.read_text(encoding="utf-8-sig").splitlines()
        new_lines = new_content.splitlines()
        patch_lines = max(0, len(new_lines) - len(original_lines))
        return new_content, patch_lines

    @staticmethod
    def _add_import_template(
        target_path: Path,
        module: str,
        names: list[str] | None,
    ) -> str | None:
        """Fallback sans libcst : insère l'import en tête de fichier.

        Vérifie l'absence de doublon avant insertion.
        Retourne None si doublon détecté.
        """
        original = target_path.read_text(encoding="utf-8-sig")

        if names:
            import_line = "from %s import %s" % (module, ", ".join(names))
        else:
            import_line = "import %s" % module

        # Vérification doublon simple
        for line in original.splitlines():
            stripped = line.strip()
            if stripped == import_line:
                log.debug("Import déjà présent (fallback) : %s", import_line)
                return original  # pas de changement — 0 lignes ajoutées

        return import_line + "\n" + original

    # ------------------------------------------------------------------
    # Sauvegarde du patch
    # ------------------------------------------------------------------

    def _write_patch_file(
        self,
        pattern_id: str,
        target_file: str,
        new_content: str,
        status: str,
    ) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        safe_name = Path(target_file).name.replace(".py", "")
        patch_path = self._auto_fixes_dir / ("%s_%s_%s.patch" % (pattern_id, safe_name, ts))
        meta_path = self._auto_fixes_dir / ("%s_%s_%s.json" % (pattern_id, safe_name, ts))

        try:
            patch_path.write_text(new_content, encoding="utf-8")
            atomic_write_json(meta_path, {
                "timestamp": ts,
                "pattern_id": pattern_id,
                "target_file": target_file,
                "status": status,
            })
        except Exception as exc:  # noqa: BLE001
            log.error("_write_patch_file échoué : %s", exc)

    # ------------------------------------------------------------------
    # Git commit (jamais de push)
    # ------------------------------------------------------------------

    def _git_commit(self, pattern_id: str, target_file: str) -> None:
        """Crée un commit sur une branche dédiée. auto_push = False — jamais de git push."""
        if self._cfg["auto_fix"].get("auto_push", False):
            log.error("auto_push=True détecté — refus de pousser (sécurité LCCA)")
            # On continue quand même avec le commit local

        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        branch = "auto-fix/%s-%s" % (pattern_id, ts)

        project_root = self._si_dir.parent

        try:
            subprocess.run(
                ["git", "checkout", "-b", branch],
                cwd=str(project_root),
                capture_output=True,
                timeout=30,
            )
            subprocess.run(
                ["git", "add", target_file],
                cwd=str(project_root),
                capture_output=True,
                timeout=30,
            )
            subprocess.run(
                ["git", "commit", "-m",
                 "[auto-fix] %s on %s" % (pattern_id, Path(target_file).name)],
                cwd=str(project_root),
                capture_output=True,
                timeout=30,
            )
            log.info("Commit auto-fix sur branche %s", branch)
            # NE PAS appeler git push — auto_push = false (invariant LCCA)
        except Exception as exc:  # noqa: BLE001
            log.warning("git commit auto-fix échoué (non bloquant) : %s", exc)
