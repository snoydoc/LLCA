# -*- coding: utf-8-sig -*-
"""
test_refacto_13.py — LCCA V5 Fusion
V9-09 / REFACTO-13 — Tests du découpage error_analyzer.py

3 classes × 6 tests = 18 tests.

Vérifie :
  - ErrorReport dataclass accessible depuis error_analyzer (rétrocompat)
  - ErrorAnalyzer.analyze() : dispatch inchangé
  - ErrorClassifier : méthodes statiques directement utilisables
  - ErrorRecoveryHints : is_module_fixable, build_fix_prompt, try_auto_fix
  - Aliases rétrocompat : analyze_syntax_error, analyze_import_error, analyze_generic,
                          generate_fix_prompt, try_auto_fix
"""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ──────────────────────────────────────────────────────────────────────────────
# TestErrorAnalyzerRetrocompat — imports + aliases rétrocompat
# ──────────────────────────────────────────────────────────────────────────────

class TestErrorAnalyzerRetrocompat:
    """Vérifie que l'API publique de error_analyzer.py est inchangée."""

    def test_import_erroranalyzer_and_errorreport(self) -> None:
        """from core.error_analyzer import ErrorAnalyzer, ErrorReport doit fonctionner."""
        from core.error_analyzer import ErrorAnalyzer, ErrorReport
        assert ErrorAnalyzer is not None
        assert ErrorReport is not None

    def test_analyze_syntax_error_alias(self) -> None:
        """analyze_syntax_error() : alias rétrocompat retourne ErrorReport."""
        from core.error_analyzer import ErrorAnalyzer
        analyzer = ErrorAnalyzer()
        try:
            compile("def foo(\n", "<string>", "exec")
        except SyntaxError as e:
            report = analyzer.analyze_syntax_error(e, "test.py")
            assert report.error_type == "SyntaxError"
            assert report.severity == "blocking"
            assert report.auto_fixable is False

    def test_analyze_import_error_alias(self) -> None:
        """analyze_import_error() : alias rétrocompat retourne ErrorReport."""
        from core.error_analyzer import ErrorAnalyzer
        analyzer = ErrorAnalyzer()
        e = ImportError("No module named 'foobar'")
        report = analyzer.analyze_import_error(e, "test.py")
        assert report.error_type == "ImportError"
        assert "foobar" in report.suggestion

    def test_analyze_generic_alias(self) -> None:
        """analyze_generic() : alias rétrocompat retourne ErrorReport severity=warning."""
        from core.error_analyzer import ErrorAnalyzer
        analyzer = ErrorAnalyzer()
        e = RuntimeError("quelque chose s'est mal passé")
        report = analyzer.analyze_generic(e, "test.py")
        assert report.error_type == "RuntimeError"
        assert report.severity == "warning"

    def test_generate_fix_prompt_alias(self) -> None:
        """generate_fix_prompt() : alias rétrocompat retourne str < 800 chars."""
        from core.error_analyzer import ErrorAnalyzer, ErrorReport
        analyzer = ErrorAnalyzer()
        report = ErrorReport(
            error_type="SyntaxError",
            file="auth.py",
            line=10,
            message="invalid syntax",
            suggestion="Vérifier la ligne 10.",
            severity="blocking",
            auto_fixable=False,
        )
        prompt = analyzer.generate_fix_prompt(report)
        assert isinstance(prompt, str)
        assert "SyntaxError" in prompt
        assert len(prompt) <= 800

    def test_analyze_dispatch_returns_errorreport(self) -> None:
        """analyze() dispatch : AttributeError et NameError retournent ErrorReport."""
        from core.error_analyzer import ErrorAnalyzer
        analyzer = ErrorAnalyzer()

        attr_e = AttributeError("'NoneType' object has no attribute 'foo'")
        r1 = analyzer.analyze(attr_e, "mod.py")
        assert r1.error_type == "AttributeError"

        name_e = NameError("name 'bar' is not defined")
        r2 = analyzer.analyze(name_e, "mod.py")
        assert r2.error_type == "NameError"
        assert "bar" in r2.suggestion


# ──────────────────────────────────────────────────────────────────────────────
# TestErrorClassifier — méthodes statiques
# ──────────────────────────────────────────────────────────────────────────────

class TestErrorClassifier:
    """Teste ErrorClassifier directement."""

    def test_classify_syntax_indent_suggestion(self) -> None:
        """classify_syntax : IndentationError → suggestion contenant 'Indentation'."""
        from core.error_classifier import ErrorClassifier
        try:
            compile("if True:\nx = 1\n", "<string>", "exec")
        except SyntaxError as e:
            report = ErrorClassifier.classify_syntax(e, "mod.py")
            assert report.error_type == "SyntaxError"
            # suggestion non vide
            assert len(report.suggestion) > 0

    def test_classify_import_no_module(self) -> None:
        """classify_import : No module named 'x' → auto_fixable passé explicitement."""
        from core.error_classifier import ErrorClassifier
        e = ImportError("No module named 'requests'")
        report = ErrorClassifier.classify_import(e, "mod.py", auto_fixable=True)
        assert report.auto_fixable is True
        assert "requests" in report.suggestion

    def test_classify_attribute(self) -> None:
        """classify_attribute : 'NoneType' object has no attribute 'x'."""
        from core.error_classifier import ErrorClassifier
        e = AttributeError("'NoneType' object has no attribute 'run'")
        report = ErrorClassifier.classify_attribute(e, "mod.py")
        assert "NoneType" in report.suggestion
        assert "run" in report.suggestion

    def test_classify_name(self) -> None:
        """classify_name : name 'foo' is not defined."""
        from core.error_classifier import ErrorClassifier
        e = NameError("name 'foo' is not defined")
        report = ErrorClassifier.classify_name(e, "mod.py")
        assert "foo" in report.suggestion

    def test_classify_generic_fallback(self) -> None:
        """classify_generic : RuntimeError → severity warning."""
        from core.error_classifier import ErrorClassifier
        e = RuntimeError("crash inattendu")
        report = ErrorClassifier.classify_generic(e, "mod.py")
        assert report.severity == "warning"
        assert report.auto_fixable is False

    def test_extract_module_name_patterns(self) -> None:
        """_extract_module_name : No module named + from 'Y'."""
        from core.error_classifier import ErrorClassifier
        assert ErrorClassifier._extract_module_name("No module named 'os.path'") == "os"
        assert ErrorClassifier._extract_module_name("cannot import name 'foo' from 'bar'") == "bar"
        assert ErrorClassifier._extract_module_name("something else") is None


# ──────────────────────────────────────────────────────────────────────────────
# TestErrorRecoveryHints — logique requirements + prompt + auto_fix
# ──────────────────────────────────────────────────────────────────────────────

class TestErrorRecoveryHints:
    """Teste ErrorRecoveryHints directement."""

    def test_is_module_fixable_missing_file(self, tmp_path: Path) -> None:
        """is_module_fixable : requirements.txt absent → False."""
        from core.error_recovery_hints import ErrorRecoveryHints
        hints = ErrorRecoveryHints(requirements_path=tmp_path / "nonexistent.txt")
        assert hints.is_module_fixable("requests") is False

    def test_is_module_fixable_present(self, tmp_path: Path) -> None:
        """is_module_fixable : module dans requirements.txt → True."""
        from core.error_recovery_hints import ErrorRecoveryHints
        req = tmp_path / "requirements.txt"
        req.write_text("requests>=2.0\nlibcst>=1.1\n", encoding="utf-8-sig")
        hints = ErrorRecoveryHints(requirements_path=req)
        assert hints.is_module_fixable("requests") is True
        assert hints.is_module_fixable("libcst") is True
        assert hints.is_module_fixable("flask") is False

    def test_build_fix_prompt_basic(self) -> None:
        """build_fix_prompt : contient error_type + suggestion."""
        from core.error_recovery_hints import ErrorRecoveryHints
        from core.error_analyzer import ErrorReport
        hints = ErrorRecoveryHints()
        report = ErrorReport(
            error_type="ImportError",
            file="auth.py",
            line=None,
            message="No module named 'requests'",
            suggestion="Ajouter 'import requests'.",
            severity="blocking",
            auto_fixable=True,
        )
        prompt = hints.build_fix_prompt(report)
        assert "ImportError" in prompt
        assert "requests" in prompt

    def test_build_fix_prompt_with_context(self) -> None:
        """build_fix_prompt : contexte ajouté si fourni."""
        from core.error_recovery_hints import ErrorRecoveryHints
        from core.error_analyzer import ErrorReport
        hints = ErrorRecoveryHints()
        report = ErrorReport(
            error_type="SyntaxError",
            file="mod.py",
            line=5,
            message="invalid syntax",
            suggestion="Vérifier ligne 5.",
            severity="blocking",
            auto_fixable=False,
        )
        prompt = hints.build_fix_prompt(report, context="x = (1 +")
        assert "```python" in prompt
        assert "x = (1 +" in prompt

    def test_build_fix_prompt_truncated_at_800(self) -> None:
        """build_fix_prompt : résultat <= 800 chars même avec contexte énorme."""
        from core.error_recovery_hints import ErrorRecoveryHints
        from core.error_analyzer import ErrorReport
        hints = ErrorRecoveryHints()
        report = ErrorReport(
            error_type="SyntaxError",
            file="mod.py",
            line=1,
            message="x",
            suggestion="y",
            severity="blocking",
            auto_fixable=False,
        )
        prompt = hints.build_fix_prompt(report, context="z" * 2000)
        assert len(prompt) <= 800

    def test_try_auto_fix_not_auto_fixable(self) -> None:
        """try_auto_fix : auto_fixable=False → retourne False immédiatement."""
        from core.error_recovery_hints import ErrorRecoveryHints
        from core.error_analyzer import ErrorReport
        hints = ErrorRecoveryHints()
        report = ErrorReport(
            error_type="SyntaxError",
            file="mod.py",
            line=1,
            message="x",
            suggestion="y",
            severity="blocking",
            auto_fixable=False,
        )
        result = hints.try_auto_fix(report, patcher=MagicMock())
        assert result is False
