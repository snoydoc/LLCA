# -*- coding: utf-8-sig -*-
"""
error_recovery_hints.py — LCCA V5 Fusion
REFACTO-13 — Extrait de error_analyzer.py

Gestion de la récupération automatique des erreurs :
  - Chargement requirements.txt (modules auto-fixables)
  - Génération du prompt LLM de correction
  - Application automatique du fix (ImportError via SmartPatcher)

Usage interne :
    from core.error_recovery_hints import ErrorRecoveryHints
    hints = ErrorRecoveryHints()
    fixable = hints.is_module_fixable("requests")
    prompt  = hints.build_fix_prompt(report, context)
    ok      = hints.try_auto_fix(report, patcher)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

log = logging.getLogger("lcca.error_recovery_hints")

try:
    from config import BASE_DIR as _BASE_DIR
    _REQUIREMENTS_FILE: Path = _BASE_DIR / "requirements.txt"
except (ImportError, AttributeError):
    _REQUIREMENTS_FILE: Path = Path(__file__).resolve().parent.parent / "requirements.txt"


class ErrorRecoveryHints:
    """
    Logique de récupération des erreurs Python.

    Responsabilités :
      - Charger requirements.txt (lazy, mis en cache).
      - Déterminer si un module est auto-fixable.
      - Générer un prompt LLM de correction < 200 tokens.
      - Appliquer un fix automatique via SmartPatcher (ImportError V1).

    Séparé de ErrorClassifier pour respecter la règle SRP :
    classification ≠ récupération.
    """

    def __init__(self, requirements_path: Optional[Path] = None) -> None:
        self._req_path = requirements_path or _REQUIREMENTS_FILE
        self._known_modules: Optional[set] = None

    # ── API publique ──────────────────────────────────────────────────────────

    def is_module_fixable(self, module: str) -> bool:
        """True si le module est listado dans requirements.txt."""
        if not module:
            return False
        if self._known_modules is None:
            self._known_modules = self._load_requirements()
        return module.lower() in self._known_modules

    def build_fix_prompt(self, report, context: str = "") -> str:
        """
        Génère un prompt LLM concis (< 200 tokens) pour corriger l'erreur.

        Args:
            report:  ErrorReport issu de ErrorAnalyzer.analyze().
            context: Code source court (optionnel).

        Returns:
            str : Prompt actionnable < 200 tokens.
        """
        line_str = f":{report.line}" if report.line else ""
        base = (
            f"Erreur {report.error_type} [{report.file}{line_str}]: "
            f"{report.message}. "
            f"Corriger en: {report.suggestion}"
        )

        if context:
            ctx_short = context[:300].strip()
            full = f"{base}\n\nContexte:\n```python\n{ctx_short}\n```"
        else:
            full = base

        if len(full) > 800:
            full = full[:797] + "..."

        return full

    def try_auto_fix(
        self, report, patcher, workspace: Optional[Path] = None
    ) -> bool:
        """
        Tente une correction automatique si auto_fixable=True.

        V1 : Gère uniquement ImportError auto_fixable
             (module dans requirements.txt → ajoute via AddImportTransformer).

        Returns:
            True si la correction a été appliquée avec succès.
        """
        if not report.auto_fixable:
            log.debug("try_auto_fix: rapport non auto_fixable, skip.")
            return False

        if report.error_type != "ImportError":
            log.debug(
                "try_auto_fix: type '%s' non supporté en V1.", report.error_type
            )
            return False

        module_name = self._extract_module_name(report.message)
        if not module_name:
            return False

        ws = workspace or patcher.workspace
        file_path = report.file

        try:
            new_code = patcher.apply_patch(
                file_path,
                "add_import",
                module=module_name,
            )
            full_path = ws / file_path
            full_path.write_text(new_code, encoding="utf-8-sig")
            log.info(
                "try_auto_fix: import '%s' ajouté dans %s", module_name, file_path
            )
            return True

        except Exception as exc:
            log.error(
                "try_auto_fix: echec pour '%s' dans %s: %s",
                module_name, file_path, exc,
            )
            return False

    # ── Helpers privés ────────────────────────────────────────────────────────

    def _load_requirements(self) -> set:
        """Charge requirements.txt et retourne un set de noms (lowercase)."""
        if not self._req_path.exists():
            return set()
        names: set = set()
        for line in self._req_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pkg = re.split(r"[><=!;]", line)[0].strip().lower()
            if pkg:
                names.add(pkg)
                names.add(pkg.replace("-", "_"))
        return names

    @staticmethod
    def _extract_module_name(error_msg: str) -> Optional[str]:
        m = re.search(r"No module named '([^']+)'", error_msg)
        if m:
            return m.group(1).split(".")[0]
        m = re.search(r"from '([^']+)'", error_msg)
        if m:
            return m.group(1).split(".")[0]
        return None
