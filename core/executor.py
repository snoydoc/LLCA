# -*- coding: utf-8-sig -*-
"""
executor.py — LCCA V5 Fusion
Sprint 06 — TASK-06-03

Validation des fichiers modifiés : syntaxe Python + lancement pytest optionnel.
Lecture seule — ne modifie aucun fichier.

Usage :
    from core.executor import Executor, ValidationResult
    ex = Executor(workspace=Path("D:/LLMCodeAgent/workspace"),
                  tests_dir=Path("D:/LLMCodeAgent/tests"))
    result = ex.validate(["auth.py", "models.py"])
    if not result.passed:
        print(result.syntax_errors)
"""

from __future__ import annotations

import subprocess
import sys
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger("lcca.executor")


@dataclass
class ValidationResult:
    """Résultat d'une validation Executor."""
    passed:        bool
    syntax_errors: List[str] = field(default_factory=list)   # "file.py:10: invalid syntax"
    test_failures: List[str] = field(default_factory=list)   # lignes FAILED de pytest
    test_output:   str       = ""                             # stdout+stderr pytest complet
    duration_ms:   int       = 0


class Executor:
    r"""
    Valide les fichiers Python modifiés dans le workspace.

    Étapes :
      1. Vérification syntaxe sur chaque .py via compile() (rapide, sans exécution)
      2. Si tests_dir non vide → lance pytest -x -q (optionnel)

    Attributes:
        workspace:   Dossier racine du code cible.
        tests_dir:   Dossier contenant les tests pytest.
        timeout_sec: Timeout subprocess pytest (défaut 30s).
    """

    def __init__(
        self,
        workspace: Path,
        tests_dir: Path,
        timeout_sec: int = 30,
    ) -> None:
        self.workspace   = workspace
        self.tests_dir   = tests_dir
        self.timeout_sec = timeout_sec

    # ── Interface publique ────────────────────────────────────────────────────

    def validate(self, modified_files: List[str]) -> ValidationResult:
        """
        Valide la syntaxe des fichiers modifiés, puis lance les tests si disponibles.

        Args:
            modified_files: Chemins relatifs au workspace des fichiers à vérifier.

        Returns:
            ValidationResult avec passed=True seulement si syntaxe OK ET tests OK.
        """
        t0 = time.perf_counter()

        syntax_errors: List[str] = []
        for rel in modified_files:
            err = self.check_syntax(rel)
            if err:
                syntax_errors.append(err)
                log.error("Syntax error: %s", err)

        if syntax_errors:
            elapsed = int((time.perf_counter() - t0) * 1000)
            return ValidationResult(
                passed=False,
                syntax_errors=syntax_errors,
                duration_ms=elapsed,
            )

        # Lancement tests
        tests_passed, test_output = self.run_tests()
        failures = self._extract_failures(test_output) if not tests_passed else []

        elapsed = int((time.perf_counter() - t0) * 1000)
        log.info(
            "Executor.validate: syntaxe OK, tests %s (%dms)",
            "PASSED" if tests_passed else "FAILED",
            elapsed,
        )
        return ValidationResult(
            passed=tests_passed,
            syntax_errors=[],
            test_failures=failures,
            test_output=test_output,
            duration_ms=elapsed,
        )

    def check_syntax(self, file_path: str) -> Optional[str]:
        """
        Vérifie la syntaxe Python d'un fichier (sans l'exécuter).

        Args:
            file_path: Chemin relatif au workspace.

        Returns:
            None si syntaxe valide, sinon message d'erreur "file:line: msg".
        """
        full = self.workspace / file_path
        if not full.exists():
            return f"{file_path}: fichier introuvable"
        if full.suffix != ".py":
            return None  # Non-Python → skip

        try:
            source = full.read_text(encoding="utf-8-sig")
        except Exception as exc:
            return f"{file_path}: lecture impossible ({exc})"

        try:
            compile(source, file_path, "exec")
            return None
        except SyntaxError as e:
            return f"{file_path}:{e.lineno}: {e.msg}"

    def run_tests(self) -> Tuple[bool, str]:
        """
        Lance pytest sur self.tests_dir.

        Returns:
            (passed: bool, output: str)
              - (True, "Pas de tests trouvés — skip") si aucun test_*.py
              - (True/False, stdout+stderr) sinon
        """
        test_files = list(self.tests_dir.rglob("test_*.py")) if self.tests_dir.exists() else []
        if not test_files:
            return True, "Pas de tests trouvés — skip"

        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "pytest",
                    str(self.tests_dir),
                    "-x", "-q", "--tb=short",
                    "--no-header",
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                cwd=self.workspace.parent,
            )
            output = result.stdout + result.stderr
            passed = result.returncode == 0
            log.debug("pytest returncode=%d", result.returncode)
            return passed, output

        except subprocess.TimeoutExpired:
            msg = f"pytest timeout après {self.timeout_sec}s"
            log.error(msg)
            return False, msg
        except FileNotFoundError:
            msg = "python/pytest introuvable dans PATH"
            log.error(msg)
            return False, msg
        except Exception as exc:
            msg = f"Erreur lancement pytest: {exc}"
            log.error(msg)
            return False, msg

    # ── Helper privé ──────────────────────────────────────────────────────────

    @staticmethod
    def _extract_failures(output: str) -> List[str]:
        """Extrait les lignes 'FAILED ...' de la sortie pytest."""
        return [
            line.strip()
            for line in output.splitlines()
            if line.strip().startswith("FAILED")
        ]
