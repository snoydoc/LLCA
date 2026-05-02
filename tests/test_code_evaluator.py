# -*- coding: utf-8-sig -*-
"""
test_code_evaluator.py — LCCA V5 Fusion
Sprint 11 — Tests unitaires CodeEvaluator

Couvre :
  - Syntaxe invalide → score 0, passed False
  - Code minimal sans hints ni docstrings → score faible
  - Code bien typé + documenté → score élevé
  - Anti-patterns détectés (bare except, print, global, eval, import *)
  - Complexité cyclomatique (simple vs complexe)
  - evaluate_diff() avant/après patch
  - Threshold personnalisé
  - Cas limites (code vide, module docstring seul, lambda, etc.)
"""

from __future__ import annotations

import pytest
from core.code_evaluator import (
    CodeEvaluator,
    EvaluationResult,
    CriterionScore,
    _DEFAULT_PASS_THRESHOLD,
    _W_SYNTAX,
    _W_TYPE_HINTS,
    _W_DOCSTRINGS,
    _W_COMPLEXITY,
    _W_ANTIPATTERN,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures helpers
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def ev() -> CodeEvaluator:
    """Évaluateur avec seuil par défaut (60)."""
    return CodeEvaluator()


_CODE_INVALID_SYNTAX = "def (:\n    pass\n"

_CODE_BARE_MINIMUM = (
    "def foo():\n"
    "    pass\n"
)

_CODE_GOOD_QUALITY = (
    '"""\nModule de qualité.\n"""\n\n'
    "from __future__ import annotations\n\n\n"
    "def validate_email(email: str) -> bool:\n"
    '    """Valide une adresse email.\n\n    Args:\n        email: L\'adresse à valider.\n\n    Returns:\n        True si valide.\n    """\n'
    "    return \"@\" in email and \".\" in email\n"
)

_CODE_COMPLEX = (
    "def complex_func(x, y, z):\n"
    "    if x > 0:\n"
    "        if y > 0:\n"
    "            if z > 0:\n"
    "                for i in range(x):\n"
    "                    while y > 0:\n"
    "                        try:\n"
    "                            if i and y and z:\n"
    "                                pass\n"
    "                        except:\n"
    "                            pass\n"
    "                        y -= 1\n"
    "    return x\n"
)

_CODE_ANTIPATTERNS = (
    "from os import *\n"
    "def bad():\n"
    "    global counter\n"
    "    try:\n"
    "        print('debug')\n"
    "    except:\n"
    "        eval('1+1')\n"
    "counter = 0\n"
)

_CODE_NO_FUNCTIONS = (
    '"""\nModule sans fonctions.\n"""\n\n'
    "X = 42\n"
    "Y = 'hello'\n"
)


# ──────────────────────────────────────────────────────────────────────────────
# Tests : Syntaxe
# ──────────────────────────────────────────────────────────────────────────────

class TestSyntax:

    def test_invalid_syntax_score_zero(self, ev: CodeEvaluator) -> None:
        """Code syntaxiquement invalide → score=0, passed=False."""
        result = ev.evaluate(_CODE_INVALID_SYNTAX, filename="bad.py")
        assert result.score == 0
        assert result.passed is False
        assert result.syntax_error is not None

    def test_invalid_syntax_has_error_message(self, ev: CodeEvaluator) -> None:
        """Le message d'erreur syntaxe est non vide et mentionne la ligne."""
        result = ev.evaluate(_CODE_INVALID_SYNTAX)
        assert "1" in result.syntax_error  # ligne 1

    def test_invalid_syntax_has_syntax_criterion(self, ev: CodeEvaluator) -> None:
        """Un seul critère 'Syntaxe Python' avec score=0 est présent."""
        result = ev.evaluate(_CODE_INVALID_SYNTAX)
        assert len(result.criteria) >= 1
        syntax_c = result.criteria[0]
        assert syntax_c.score == 0
        assert syntax_c.max == _W_SYNTAX

    def test_valid_syntax_gets_full_syntax_score(self, ev: CodeEvaluator) -> None:
        """Code valide → critère syntaxe = score plein."""
        result = ev.evaluate(_CODE_BARE_MINIMUM)
        syntax_c = next(c for c in result.criteria if c.name == "Syntaxe Python")
        assert syntax_c.score == _W_SYNTAX

    def test_empty_code_is_valid(self, ev: CodeEvaluator) -> None:
        """Code vide → syntaxe valide, score > 0."""
        result = ev.evaluate("")
        assert result.syntax_error is None
        assert result.score >= 0


# ──────────────────────────────────────────────────────────────────────────────
# Tests : Type hints
# ──────────────────────────────────────────────────────────────────────────────

class TestTypeHints:

    def test_no_hints_gives_low_score(self, ev: CodeEvaluator) -> None:
        """Fonction sans type hints → score type hints faible."""
        result = ev.evaluate(_CODE_BARE_MINIMUM)
        hints_c = next(c for c in result.criteria if c.name == "Type hints")
        assert hints_c.score < hints_c.max

    def test_full_hints_gives_full_score(self, ev: CodeEvaluator) -> None:
        """Fonction totalement typée → score type hints maximum."""
        result = ev.evaluate(_CODE_GOOD_QUALITY)
        hints_c = next(c for c in result.criteria if c.name == "Type hints")
        assert hints_c.score == _W_TYPE_HINTS

    def test_no_functions_bonus(self, ev: CodeEvaluator) -> None:
        """Module sans fonction → bonus type hints accordé (non applicable)."""
        result = ev.evaluate(_CODE_NO_FUNCTIONS)
        hints_c = next(c for c in result.criteria if c.name == "Type hints")
        assert hints_c.score == _W_TYPE_HINTS

    def test_partial_hints_intermediate_score(self, ev: CodeEvaluator) -> None:
        """Fonction avec return typé mais args non typés → score intermédiaire."""
        code = "def fn(x) -> bool:\n    return bool(x)\n"
        result = ev.evaluate(code)
        hints_c = next(c for c in result.criteria if c.name == "Type hints")
        assert 0 < hints_c.score < _W_TYPE_HINTS


# ──────────────────────────────────────────────────────────────────────────────
# Tests : Docstrings
# ──────────────────────────────────────────────────────────────────────────────

class TestDocstrings:

    def test_no_docstring_penalized(self, ev: CodeEvaluator) -> None:
        """Fonction sans docstring → pénalité."""
        result = ev.evaluate(_CODE_BARE_MINIMUM)
        doc_c = next(c for c in result.criteria if c.name == "Docstrings")
        assert doc_c.score < doc_c.max

    def test_good_docstrings_score(self, ev: CodeEvaluator) -> None:
        """Module + fonctions documentées → score docstrings maximal."""
        result = ev.evaluate(_CODE_GOOD_QUALITY)
        doc_c = next(c for c in result.criteria if c.name == "Docstrings")
        assert doc_c.score == _W_DOCSTRINGS

    def test_module_docstring_only(self, ev: CodeEvaluator) -> None:
        """Module avec seulement une docstring module → score partiel."""
        result = ev.evaluate(_CODE_NO_FUNCTIONS)
        doc_c = next(c for c in result.criteria if c.name == "Docstrings")
        assert doc_c.score > 0

    def test_class_docstring_counted(self, ev: CodeEvaluator) -> None:
        """Docstring sur une classe → comptabilisée."""
        code = (
            'class MyClass:\n'
            '    """Une classe documentée."""\n'
            '    pass\n'
        )
        result = ev.evaluate(code)
        doc_c = next(c for c in result.criteria if c.name == "Docstrings")
        assert doc_c.score > 0


# ──────────────────────────────────────────────────────────────────────────────
# Tests : Complexité cyclomatique
# ──────────────────────────────────────────────────────────────────────────────

class TestComplexity:

    def test_simple_code_max_score(self, ev: CodeEvaluator) -> None:
        """Code simple → score complexité maximal."""
        result = ev.evaluate(_CODE_GOOD_QUALITY)
        cx_c = next(c for c in result.criteria if "Complexit" in c.name)
        assert cx_c.score == _W_COMPLEXITY

    def test_complex_code_penalized(self, ev: CodeEvaluator) -> None:
        """Code très complexe → score complexité réduit ou nul."""
        result = ev.evaluate(_CODE_COMPLEX)
        cx_c = next(c for c in result.criteria if "Complexit" in c.name)
        assert cx_c.score < _W_COMPLEXITY

    def test_complexity_value_returned(self, ev: CodeEvaluator) -> None:
        """La valeur de complexité brute est retournée dans EvaluationResult."""
        result = ev.evaluate(_CODE_COMPLEX)
        assert result.complexity > 1

    def test_simple_code_complexity_low(self, ev: CodeEvaluator) -> None:
        """Code sans branchement → complexité basse."""
        code = "x = 1 + 2\ny = x * 3\n"
        result = ev.evaluate(code)
        assert result.complexity <= 3


# ──────────────────────────────────────────────────────────────────────────────
# Tests : Anti-patterns
# ──────────────────────────────────────────────────────────────────────────────

class TestAntipatterns:

    def test_clean_code_max_score(self, ev: CodeEvaluator) -> None:
        """Code propre → score anti-patterns maximal."""
        result = ev.evaluate(_CODE_GOOD_QUALITY)
        ap_c = next(c for c in result.criteria if c.name == "Anti-patterns")
        assert ap_c.score == _W_ANTIPATTERN

    def test_bare_except_penalized(self, ev: CodeEvaluator) -> None:
        """bare `except:` → pénalité."""
        code = "def fn():\n    try:\n        pass\n    except:\n        pass\n"
        result = ev.evaluate(code)
        ap_c = next(c for c in result.criteria if c.name == "Anti-patterns")
        assert ap_c.score < _W_ANTIPATTERN

    def test_print_penalized(self, ev: CodeEvaluator) -> None:
        """print() dans le code → pénalité."""
        code = "def fn():\n    print('debug')\n"
        result = ev.evaluate(code)
        ap_c = next(c for c in result.criteria if c.name == "Anti-patterns")
        assert ap_c.score < _W_ANTIPATTERN

    def test_global_penalized(self, ev: CodeEvaluator) -> None:
        """`global` → pénalité."""
        code = "counter = 0\ndef fn():\n    global counter\n    counter += 1\n"
        result = ev.evaluate(code)
        ap_c = next(c for c in result.criteria if c.name == "Anti-patterns")
        assert ap_c.score < _W_ANTIPATTERN

    def test_eval_penalized(self, ev: CodeEvaluator) -> None:
        """`eval()` → pénalité."""
        code = "def fn(s):\n    return eval(s)\n"
        result = ev.evaluate(code)
        ap_c = next(c for c in result.criteria if c.name == "Anti-patterns")
        assert ap_c.score < _W_ANTIPATTERN

    def test_import_star_penalized(self, ev: CodeEvaluator) -> None:
        """`import *` → pénalité."""
        code = "from os import *\ndef fn():\n    pass\n"
        result = ev.evaluate(code)
        ap_c = next(c for c in result.criteria if c.name == "Anti-patterns")
        assert ap_c.score < _W_ANTIPATTERN

    def test_multiple_antipatterns_cumulated(self, ev: CodeEvaluator) -> None:
        """Plusieurs anti-patterns cumulés → score très faible (min 0)."""
        result = ev.evaluate(_CODE_ANTIPATTERNS)
        ap_c = next(c for c in result.criteria if c.name == "Anti-patterns")
        assert ap_c.score == 0  # Déductions > total → clampé à 0

    def test_antipattern_detail_lists_issues(self, ev: CodeEvaluator) -> None:
        """Le détail du critère liste les anti-patterns trouvés."""
        result = ev.evaluate(_CODE_ANTIPATTERNS)
        ap_c = next(c for c in result.criteria if c.name == "Anti-patterns")
        assert "anti-pattern" in ap_c.details.lower()


# ──────────────────────────────────────────────────────────────────────────────
# Tests : Score global & passed
# ──────────────────────────────────────────────────────────────────────────────

class TestGlobalScore:

    def test_good_code_passes(self, ev: CodeEvaluator) -> None:
        """Code de bonne qualité → passed=True."""
        result = ev.evaluate(_CODE_GOOD_QUALITY)
        assert result.passed is True
        assert result.score >= _DEFAULT_PASS_THRESHOLD

    def test_bad_code_fails(self, ev: CodeEvaluator) -> None:
        """Code invalide → passed=False."""
        result = ev.evaluate(_CODE_INVALID_SYNTAX)
        assert result.passed is False

    def test_score_bounded_0_100(self, ev: CodeEvaluator) -> None:
        """Le score total est toujours dans [0, 100]."""
        for code in [_CODE_INVALID_SYNTAX, _CODE_BARE_MINIMUM, _CODE_GOOD_QUALITY,
                     _CODE_COMPLEX, _CODE_ANTIPATTERNS]:
            result = ev.evaluate(code)
            assert 0 <= result.score <= 100, f"Score hors bornes: {result.score}"

    def test_custom_threshold(self) -> None:
        """Threshold personnalisé respecté."""
        ev_high = CodeEvaluator(threshold=90)
        result  = ev_high.evaluate(_CODE_BARE_MINIMUM)
        assert result.threshold == 90
        assert result.passed is False

    def test_threshold_zero_always_passes(self) -> None:
        """Threshold=0 → tout code valide passe."""
        ev_zero = CodeEvaluator(threshold=0)
        result  = ev_zero.evaluate(_CODE_BARE_MINIMUM)
        assert result.passed is True

    def test_invalid_threshold_raises(self) -> None:
        """Threshold hors [0,100] → ValueError."""
        with pytest.raises(ValueError):
            CodeEvaluator(threshold=150)
        with pytest.raises(ValueError):
            CodeEvaluator(threshold=-1)

    def test_five_criteria_always_present(self, ev: CodeEvaluator) -> None:
        """5 critères toujours présents pour du code valide."""
        result = ev.evaluate(_CODE_GOOD_QUALITY)
        assert len(result.criteria) == 5

    def test_metadata_populated(self, ev: CodeEvaluator) -> None:
        """n_functions, n_classes, n_lines correctement remplis."""
        result = ev.evaluate(_CODE_GOOD_QUALITY)
        assert result.n_functions >= 1
        assert result.n_lines > 0
        assert result.n_classes == 0


# ──────────────────────────────────────────────────────────────────────────────
# Tests : evaluate_diff()
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluateDiff:

    def test_diff_improved_after_adding_hints(self, ev: CodeEvaluator) -> None:
        """Ajout de type hints → delta positif, improved=True."""
        before = "def fn(x):\n    return x\n"
        after  = "def fn(x: int) -> int:\n    return x\n"
        diff   = ev.evaluate_diff(before, after)
        assert diff["delta"] >= 0
        assert diff["improved"] is True

    def test_diff_worsened_after_adding_antipattern(self, ev: CodeEvaluator) -> None:
        """Ajout d'un anti-pattern → delta négatif."""
        before = "def fn(x: int) -> int:\n    return x\n"
        after  = "def fn(x: int) -> int:\n    print(x)\n    return x\n"
        diff   = ev.evaluate_diff(before, after)
        assert diff["delta"] <= 0

    def test_diff_returns_result_after(self, ev: CodeEvaluator) -> None:
        """evaluate_diff retourne un EvaluationResult complet pour l'after."""
        diff = ev.evaluate_diff(_CODE_BARE_MINIMUM, _CODE_GOOD_QUALITY)
        assert isinstance(diff["result_after"], EvaluationResult)

    def test_diff_keys_present(self, ev: CodeEvaluator) -> None:
        """Toutes les clés attendues sont présentes dans le dict diff."""
        diff = ev.evaluate_diff("pass\n", "x = 1\n")
        expected = {"filename", "score_before", "score_after", "delta", "improved", "passed_after", "result_after"}
        assert expected.issubset(diff.keys())


# ──────────────────────────────────────────────────────────────────────────────
# Tests : EvaluationResult.summary() & to_dict()
# ──────────────────────────────────────────────────────────────────────────────

class TestResultFormatting:

    def test_summary_contains_score(self, ev: CodeEvaluator) -> None:
        """summary() contient le score et le filename."""
        result = ev.evaluate(_CODE_GOOD_QUALITY, filename="auth.py")
        s = result.summary()
        assert "auth.py" in s
        assert str(result.score) in s

    def test_summary_contains_passed_status(self, ev: CodeEvaluator) -> None:
        """summary() indique PASSED ou FAILED."""
        r_pass = ev.evaluate(_CODE_GOOD_QUALITY)
        r_fail = ev.evaluate(_CODE_INVALID_SYNTAX)
        assert "PASSED" in r_pass.summary()
        assert "FAILED" in r_fail.summary()

    def test_to_dict_serializable(self, ev: CodeEvaluator) -> None:
        """to_dict() retourne un dict JSON-sérialisable."""
        import json
        result = ev.evaluate(_CODE_GOOD_QUALITY)
        d = result.to_dict()
        # Ne doit pas lever d'exception
        json.dumps(d)

    def test_to_dict_keys(self, ev: CodeEvaluator) -> None:
        """to_dict() contient toutes les clés attendues."""
        result = ev.evaluate(_CODE_BARE_MINIMUM)
        d = result.to_dict()
        for key in ("filename", "score", "passed", "threshold", "n_functions",
                    "n_classes", "n_lines", "complexity", "criteria"):
            assert key in d, f"Clé manquante : {key}"
