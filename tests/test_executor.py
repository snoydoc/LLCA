# -*- coding: utf-8-sig -*-
"""
test_executor.py — LCCA V5 Fusion
Sprint 06 — TASK-06-05

Tests unitaires : Executor (check_syntax, run_tests, validate).
Utilise tmp_path pour isolation complète.
"""

from __future__ import annotations

import pytest
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Dossier workspace temporaire."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def tests_dir(tmp_path: Path) -> Path:
    """Dossier tests/ temporaire (vide par défaut)."""
    td = tmp_path / "tests"
    td.mkdir()
    return td


@pytest.fixture
def executor(workspace: Path, tests_dir: Path):
    from core.executor import Executor
    return Executor(workspace=workspace, tests_dir=tests_dir, timeout_sec=30)


# ──────────────────────────────────────────────────────────────────────────────
# Tests check_syntax()
# ──────────────────────────────────────────────────────────────────────────────

class TestCheckSyntax:

    def test_valid_file_returns_none(self, executor, workspace: Path) -> None:
        """Fichier Python valide → check_syntax retourne None."""
        f = workspace / "valid.py"
        f.write_text("def foo():\n    return 42\n", encoding="utf-8-sig")
        assert executor.check_syntax("valid.py") is None

    def test_invalid_file_returns_message(self, executor, workspace: Path) -> None:
        """Fichier avec SyntaxError → message d'erreur retourné."""
        f = workspace / "bad.py"
        f.write_text("def foo(\n    return 42\n", encoding="utf-8-sig")
        result = executor.check_syntax("bad.py")
        assert result is not None
        assert "bad.py" in result

    def test_missing_file_returns_error(self, executor) -> None:
        """Fichier inexistant → message 'introuvable'."""
        result = executor.check_syntax("nonexistent.py")
        assert result is not None
        assert "introuvable" in result

    def test_non_python_file_returns_none(self, executor, workspace: Path) -> None:
        """Fichier non .py → skip (None), pas d'erreur."""
        f = workspace / "readme.md"
        f.write_text("# README", encoding="utf-8-sig")
        assert executor.check_syntax("readme.md") is None

    def test_empty_file_is_valid(self, executor, workspace: Path) -> None:
        """Fichier Python vide → syntaxe valide."""
        f = workspace / "empty.py"
        f.write_text("", encoding="utf-8-sig")
        assert executor.check_syntax("empty.py") is None

    def test_indentation_error_detected(self, executor, workspace: Path) -> None:
        """IndentationError → détectée comme SyntaxError."""
        f = workspace / "indent.py"
        f.write_text("def foo():\nreturn 1\n", encoding="utf-8-sig")
        result = executor.check_syntax("indent.py")
        assert result is not None


# ──────────────────────────────────────────────────────────────────────────────
# Tests run_tests()
# ──────────────────────────────────────────────────────────────────────────────

class TestRunTests:

    def test_run_tests_no_tests_returns_true(self, executor, tests_dir: Path) -> None:
        """tests/ sans test_*.py → (True, 'skip')."""
        passed, output = executor.run_tests()
        assert passed is True
        assert "skip" in output.lower()

    def test_run_tests_nonexistent_dir(self, workspace: Path) -> None:
        """tests_dir inexistant → (True, 'skip') car aucun test trouvé."""
        from core.executor import Executor
        ex = Executor(
            workspace=workspace,
            tests_dir=workspace / "no_such_dir",
        )
        passed, output = ex.run_tests()
        assert passed is True
        assert "skip" in output.lower()

    def test_run_tests_passes_on_trivial_test(
        self, executor, workspace: Path, tests_dir: Path
    ) -> None:
        """Test trivial dans tests_dir → pytest retourne 0."""
        test_file = tests_dir / "test_trivial.py"
        test_file.write_text(
            "def test_always_passes():\n    assert 1 + 1 == 2\n",
            encoding="utf-8-sig",
        )
        passed, output = executor.run_tests()
        assert passed is True, f"pytest échoué inattendu:\n{output}"

    def test_run_tests_fails_on_failing_test(
        self, executor, workspace: Path, tests_dir: Path
    ) -> None:
        """Test qui échoue → passed=False, output non vide."""
        test_file = tests_dir / "test_fail.py"
        test_file.write_text(
            "def test_always_fails():\n    assert False, 'voulu'\n",
            encoding="utf-8-sig",
        )
        passed, output = executor.run_tests()
        assert passed is False
        assert len(output) > 0


# ──────────────────────────────────────────────────────────────────────────────
# Tests validate()
# ──────────────────────────────────────────────────────────────────────────────

class TestValidate:

    def test_validate_valid_file_no_tests(
        self, executor, workspace: Path
    ) -> None:
        """Fichier valide + pas de tests → ValidationResult.passed=True."""
        f = workspace / "ok.py"
        f.write_text("x = 1\n", encoding="utf-8-sig")
        result = executor.validate(["ok.py"])
        assert result.passed is True
        assert result.syntax_errors == []
        assert result.duration_ms >= 0

    def test_validate_invalid_file_stops_early(
        self, executor, workspace: Path
    ) -> None:
        """Syntaxe invalide → passed=False, pas de lancement pytest."""
        f = workspace / "bad.py"
        f.write_text("def (\n", encoding="utf-8-sig")
        result = executor.validate(["bad.py"])
        assert result.passed is False
        assert len(result.syntax_errors) == 1
        assert "bad.py" in result.syntax_errors[0]

    def test_validate_multiple_files_all_valid(
        self, executor, workspace: Path
    ) -> None:
        """Plusieurs fichiers valides → passed=True."""
        for name in ["a.py", "b.py", "c.py"]:
            (workspace / name).write_text(f"# {name}\n", encoding="utf-8-sig")
        result = executor.validate(["a.py", "b.py", "c.py"])
        assert result.passed is True
        assert result.syntax_errors == []

    def test_validate_empty_list(self, executor) -> None:
        """Liste vide → passed=True (rien à vérifier)."""
        result = executor.validate([])
        assert result.passed is True


# ──────────────────────────────────────────────────────────────────────────────
# Tests ErrorAnalyzer
# ──────────────────────────────────────────────────────────────────────────────

class TestErrorAnalyzer:

    def test_analyze_syntax_error(self) -> None:
        """analyze(SyntaxError) → rapport avec suggestion non vide."""
        from core.error_analyzer import ErrorAnalyzer
        analyzer = ErrorAnalyzer()
        try:
            compile("def foo(\n    return 1\n", "test.py", "exec")
        except SyntaxError as e:
            report = analyzer.analyze(e, "test.py")
        assert report.error_type == "SyntaxError"
        assert len(report.suggestion) > 0
        assert report.severity == "blocking"
        assert report.auto_fixable is False

    def test_analyze_import_error_known_module(self, tmp_path: Path) -> None:
        """ImportError pour module dans requirements.txt → auto_fixable=True."""
        from core.error_analyzer import ErrorAnalyzer
        # Crée un faux requirements.txt
        req = tmp_path / "requirements.txt"
        req.write_text("libcst>=1.1.0\nrequests>=2.0\n", encoding="utf-8-sig")
        analyzer = ErrorAnalyzer(requirements_path=req)
        e = ImportError("No module named 'requests'")
        report = analyzer.analyze(e, "auth.py")
        assert report.error_type == "ImportError"
        assert "requests" in report.suggestion
        assert report.auto_fixable is True

    def test_analyze_import_error_unknown_module(self, tmp_path: Path) -> None:
        """ImportError pour module absent de requirements.txt → auto_fixable=False."""
        from core.error_analyzer import ErrorAnalyzer
        req = tmp_path / "requirements.txt"
        req.write_text("libcst>=1.1.0\n", encoding="utf-8-sig")
        analyzer = ErrorAnalyzer(requirements_path=req)
        e = ImportError("No module named 'numpy'")
        report = analyzer.analyze(e, "auth.py")
        assert report.auto_fixable is False

    def test_analyze_attribute_error(self) -> None:
        """AttributeError → rapport avec mention de l'objet et l'attribut."""
        from core.error_analyzer import ErrorAnalyzer
        analyzer = ErrorAnalyzer()
        e = AttributeError("'NoneType' object has no attribute 'strip'")
        report = analyzer.analyze(e, "utils.py")
        assert "NoneType" in report.suggestion
        assert "strip" in report.suggestion

    def test_analyze_name_error(self) -> None:
        """NameError → rapport avec le nom de variable."""
        from core.error_analyzer import ErrorAnalyzer
        analyzer = ErrorAnalyzer()
        e = NameError("name 'my_var' is not defined")
        report = analyzer.analyze(e, "models.py")
        assert "my_var" in report.suggestion

    def test_generate_fix_prompt_under_200_tokens(self) -> None:
        """generate_fix_prompt() retourne < 800 chars (~200 tokens)."""
        from core.error_analyzer import ErrorAnalyzer
        analyzer = ErrorAnalyzer()
        try:
            compile("def bad(\n", "f.py", "exec")
        except SyntaxError as e:
            report = analyzer.analyze(e, "f.py")
        prompt = analyzer.generate_fix_prompt(report)
        assert len(prompt) <= 800
        assert len(prompt) > 0

    def test_generate_fix_prompt_with_context(self) -> None:
        """generate_fix_prompt() inclut le contexte si fourni."""
        from core.error_analyzer import ErrorAnalyzer
        analyzer = ErrorAnalyzer()
        e = NameError("name 'x' is not defined")
        report = analyzer.analyze(e, "mod.py")
        prompt = analyzer.generate_fix_prompt(report, context="x = undefined_var\n")
        assert "Contexte" in prompt or "python" in prompt

    def test_analyze_generic_fallback(self) -> None:
        """Exception non reconnue → rapport générique valide."""
        from core.error_analyzer import ErrorAnalyzer
        analyzer = ErrorAnalyzer()
        e = ValueError("quelque chose d'inattendu")
        report = analyzer.analyze(e, "misc.py")
        assert report.error_type == "ValueError"
        assert len(report.suggestion) > 0
