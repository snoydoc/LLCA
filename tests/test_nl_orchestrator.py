# -*- coding: utf-8-sig -*-
"""
test_nl_orchestrator.py — LCCA V5 Fusion
Sprint 10 — TASK-10-02

Tests unitaires NLOrchestrator + NLResult + NLSession.
100% mockés : ni Ollama, ni LCCAV5Fusion réel requis.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.nl_orchestrator import NLOrchestrator, NLResult, NLSession
from core.nl_parser import NLIntent


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_intent(
    action:      str   = "add_function",
    target_file: str   = "core/utils.py",
    symbol:      str   = "validate_phone",
    description: str   = "Valide les numéros marocains",
    confidence:  float = 0.9,
    from_fallback: bool = False,
) -> NLIntent:
    return NLIntent(
        action        = action,
        target_file   = target_file,
        symbol        = symbol,
        description   = description,
        confidence    = confidence,
        raw_command   = "commande test",
        from_fallback = from_fallback,
    )


def _make_orchestrator(
    intent:      NLIntent | None = None,
    exec_result: dict | None     = None,
    dry_result:  dict | None     = None,
    project_dir: Path | None     = None,
) -> NLOrchestrator:
    """
    Crée un NLOrchestrator avec NLParser et LCCAV5Fusion mockés.
    """
    mock_parser = MagicMock()
    mock_parser.parse.return_value = intent or _make_intent()
    mock_parser.is_available.return_value = True
    mock_parser._model = "qwen2.5-coder:14b"

    mock_fusion = MagicMock()
    mock_fusion.execute.return_value  = exec_result or {"status": "committed", "tx_id": "tx_abc123"}
    mock_fusion.dry_run.return_value  = dry_result  or {"action": "add_function", "llm_available": False}

    with patch("core.nl_orchestrator.NLParser",      return_value=mock_parser), \
         patch("core.nl_orchestrator.LCCAV5Fusion",  return_value=mock_fusion):
        orc = NLOrchestrator(
            project_dir   = project_dir or Path("D:/LLMCodeAgent/workspace"),
            auto_confirm  = True,
        )

    # Inject directement pour contourner le __init__ patché
    orc.nl_parser    = mock_parser
    orc.orchestrator = mock_fusion
    return orc


# ──────────────────────────────────────────────────────────────────────────────
# TestNLResult
# ──────────────────────────────────────────────────────────────────────────────

class TestNLResult:

    def test_str_success(self) -> None:
        """__str__ indique ✅ si success=True."""
        r = NLResult(
            success       = True,
            command       = "test",
            intent_action = "add_function",
            confidence    = 0.9,
            dsl_command   = "LCCA - utils - Ajoute validate_phone",
            duration_s    = 0.5,
        )
        s = str(r)
        assert "✅" in s
        assert "add_function" in s
        assert "90%" in s

    def test_str_failure(self) -> None:
        """__str__ indique ❌ si success=False avec le message d'erreur."""
        r = NLResult(
            success = False,
            command = "test",
            error   = "Action inconnue",
        )
        s = str(r)
        assert "❌" in s
        assert "Action inconnue" in s

    def test_str_dry_run(self) -> None:
        """__str__ indique [dry-run] si dry_run=True."""
        r = NLResult(success=True, command="test", dry_run=True)
        assert "dry-run" in str(r)

    def test_str_fallback(self) -> None:
        """__str__ indique [heuristique] si from_fallback=True."""
        r = NLResult(
            success       = True,
            command       = "test",
            from_fallback = True,
            confidence    = 0.3,
        )
        assert "heuristique" in str(r)


# ──────────────────────────────────────────────────────────────────────────────
# TestNLSession
# ──────────────────────────────────────────────────────────────────────────────

class TestNLSession:

    def test_add_increments_total(self) -> None:
        sess = NLSession()
        sess.add(NLResult(success=True, command="cmd1"))
        sess.add(NLResult(success=False, command="cmd2"))
        assert sess.commands_total == 2
        assert sess.commands_ok    == 1

    def test_summary_format(self) -> None:
        sess = NLSession()
        sess.add(NLResult(success=True,  command="a"))
        sess.add(NLResult(success=True,  command="b"))
        sess.add(NLResult(success=False, command="c"))
        s = sess.summary()
        assert "3 commandes" in s
        assert "2 réussies" in s

    def test_summary_empty_session(self) -> None:
        """Pas de division par zéro si session vide."""
        sess = NLSession()
        s = sess.summary()
        assert "0 commandes" in s


# ──────────────────────────────────────────────────────────────────────────────
# TestNLOrchestrator — run()
# ──────────────────────────────────────────────────────────────────────────────

class TestNLOrchestratorRun:

    def test_run_success(self) -> None:
        """run() retourne NLResult.success=True sur happy path."""
        orc = _make_orchestrator()
        result = orc.run("Ajoute validate_phone dans core/utils.py")

        assert result.success
        assert result.intent_action == "add_function"
        assert result.intent_file   == "core/utils.py"
        assert result.intent_symbol == "validate_phone"
        assert result.confidence    == 0.9
        assert result.duration_s    >= 0

    def test_run_calls_nlparser(self) -> None:
        """run() appelle NLParser.parse() avec la commande."""
        orc = _make_orchestrator()
        orc.run("Ajoute validate_phone")
        orc.nl_parser.parse.assert_called_once()
        call_args = orc.nl_parser.parse.call_args
        assert "Ajoute validate_phone" in call_args[0]

    def test_run_calls_orchestrator_execute(self) -> None:
        """run() appelle LCCAV5Fusion.execute() avec la commande DSL."""
        orc = _make_orchestrator()
        orc.run("Ajoute validate_phone dans core/utils.py")
        orc.orchestrator.execute.assert_called_once()

    def test_run_empty_command_returns_failure(self) -> None:
        """run('') → NLResult.success=False sans appeler le LLM."""
        orc = _make_orchestrator()
        result = orc.run("")
        assert not result.success
        assert "vide" in result.error.lower()
        orc.nl_parser.parse.assert_not_called()

    def test_run_unknown_action_returns_failure(self) -> None:
        """run() avec intent.action='unknown' → NLResult.success=False."""
        orc = _make_orchestrator(intent=_make_intent(action="unknown"))
        result = orc.run("Fais quelque chose de magique")
        assert not result.success
        assert result.intent_action == "unknown"
        orc.orchestrator.execute.assert_not_called()

    def test_run_low_confidence_refused_without_auto_confirm(self) -> None:
        """Confiance < seuil sans auto_confirm → refus."""
        mock_parser = MagicMock()
        mock_parser.parse.return_value = _make_intent(confidence=0.1)
        mock_parser.is_available.return_value = False
        mock_parser._model = "test"

        mock_fusion = MagicMock()

        with patch("core.nl_orchestrator.NLParser",     return_value=mock_parser), \
             patch("core.nl_orchestrator.LCCAV5Fusion", return_value=mock_fusion):
            orc = NLOrchestrator(
                project_dir   = Path("D:/LLMCodeAgent/workspace"),
                auto_confirm  = False,
                min_confidence = 0.4,
            )
        orc.nl_parser    = mock_parser
        orc.orchestrator = mock_fusion

        result = orc.run("commande ambiguë")
        assert not result.success
        assert "confiance" in result.error.lower()
        mock_fusion.execute.assert_not_called()

    def test_run_low_confidence_accepted_with_auto_confirm(self) -> None:
        """Confiance < seuil AVEC auto_confirm → exécuté quand même."""
        orc = _make_orchestrator(intent=_make_intent(confidence=0.1))
        # auto_confirm=True par défaut dans _make_orchestrator
        result = orc.run("commande ambiguë")
        orc.orchestrator.execute.assert_called_once()

    def test_run_propagates_dsl_command(self) -> None:
        """NLResult.dsl_command contient la commande DSL construite."""
        orc    = _make_orchestrator()
        result = orc.run("Ajoute validate_phone dans core/utils.py")
        assert result.dsl_command != ""
        assert "validate_phone" in result.dsl_command or "utils" in result.dsl_command

    def test_run_fusion_exception_returns_failure(self) -> None:
        """Si LCCAV5Fusion.execute() lève une exception → NLResult.success=False."""
        orc = _make_orchestrator()
        orc.orchestrator.execute.side_effect = RuntimeError("Workspace inaccessible")
        result = orc.run("Ajoute validate_phone dans core/utils.py")
        assert not result.success
        assert "Workspace inaccessible" in result.error

    def test_run_from_fallback_flag_propagated(self) -> None:
        """NLResult.from_fallback reflète l'intent.from_fallback."""
        orc = _make_orchestrator(intent=_make_intent(from_fallback=True, confidence=0.3))
        result = orc.run("commande vague")
        assert result.from_fallback

    def test_run_stores_tx_metadata(self) -> None:
        """NLResult.tx_metadata contient les métadonnées de la transaction."""
        tx_meta = {"status": "committed", "tx_id": "tx_abc", "llm_model": "qwen"}
        orc = _make_orchestrator(exec_result=tx_meta)
        result = orc.run("Ajoute validate_phone dans core/utils.py")
        assert result.tx_metadata.get("tx_id") == "tx_abc"


# ──────────────────────────────────────────────────────────────────────────────
# TestNLOrchestrator — dry_run()
# ──────────────────────────────────────────────────────────────────────────────

class TestNLOrchestratorDryRun:

    def test_dry_run_does_not_call_execute(self) -> None:
        """dry_run() appelle LCCAV5Fusion.dry_run(), jamais execute()."""
        orc = _make_orchestrator()
        result = orc.dry_run("Ajoute validate_phone")
        orc.orchestrator.dry_run.assert_called_once()
        orc.orchestrator.execute.assert_not_called()

    def test_dry_run_result_has_flag(self) -> None:
        """NLResult.dry_run == True."""
        orc = _make_orchestrator()
        result = orc.dry_run("Ajoute validate_phone")
        assert result.dry_run

    def test_dry_run_returns_nlresult(self) -> None:
        """dry_run() retourne bien un NLResult."""
        orc = _make_orchestrator()
        result = orc.dry_run("Ajoute validate_phone")
        assert isinstance(result, NLResult)


# ──────────────────────────────────────────────────────────────────────────────
# TestNLOrchestrator — utilitaires
# ──────────────────────────────────────────────────────────────────────────────

class TestNLOrchestratorUtils:

    def test_scan_project_files_empty_dir(self, tmp_path: Path) -> None:
        """_scan_project_files() sur dossier vide → liste vide."""
        orc = _make_orchestrator(project_dir=tmp_path)
        files = orc._scan_project_files()
        assert files == []

    def test_scan_project_files_finds_py(self, tmp_path: Path) -> None:
        """_scan_project_files() trouve les .py récursivement."""
        (tmp_path / "core").mkdir()
        (tmp_path / "core" / "utils.py").write_text("# utils")
        (tmp_path / "main.py").write_text("# main")
        # Fichier non-py à ignorer
        (tmp_path / "README.md").write_text("# doc")

        orc = _make_orchestrator(project_dir=tmp_path)
        files = orc._scan_project_files()
        assert "core/utils.py" in files
        assert "main.py" in files
        assert all(f.endswith(".py") for f in files)

    def test_scan_ignores_pycache(self, tmp_path: Path) -> None:
        """_scan_project_files() ignore __pycache__."""
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "utils.cpython-311.pyc").write_bytes(b"")

        orc = _make_orchestrator(project_dir=tmp_path)
        files = orc._scan_project_files()
        assert not any("__pycache__" in f for f in files)

    def test_refresh_project_files(self, tmp_path: Path) -> None:
        """refresh_project_files() met à jour la liste."""
        orc = _make_orchestrator(project_dir=tmp_path)
        assert orc.refresh_project_files() == 0

        (tmp_path / "new_module.py").write_text("# new")
        count = orc.refresh_project_files()
        assert count == 1
        assert "new_module.py" in orc._project_files

    def test_validate_intent_unknown_action(self) -> None:
        """_validate_intent() retourne une erreur pour action='unknown'."""
        orc    = _make_orchestrator()
        intent = _make_intent(action="unknown")
        error  = orc._validate_intent(intent)
        assert error != ""
        assert "Action" in error or "action" in error

    def test_validate_intent_empty_description(self) -> None:
        """_validate_intent() retourne une erreur si description vide."""
        orc    = _make_orchestrator()
        intent = _make_intent(description="   ")
        error  = orc._validate_intent(intent)
        assert error != ""

    def test_validate_intent_ok(self) -> None:
        """_validate_intent() retourne '' sur intent valide."""
        orc    = _make_orchestrator()
        intent = _make_intent()
        error  = orc._validate_intent(intent)
        assert error == ""
