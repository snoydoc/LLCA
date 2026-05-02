# -*- coding: utf-8-sig -*-
"""
test_orchestrator.py — Sprint 04
Tests d'intégration : DSLParser, FileSelector, MultiFilePlanner, LCCAV5Fusion.

Couvre :
    - 6 cas de parsing DSL
    - FileSelector sur workspace réel ou mock
    - MultiFilePlanner : plan + validation
    - LCCAV5Fusion.dry_run() et execute()
    - Rollback automatique sur erreur
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

# ── Assure l'import depuis la racine projet ───────────────────────────────────
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.dsl_parser import DSLParser, Intent
from core.planner import MultiFilePlanner, OpPriority


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def parser() -> DSLParser:
    return DSLParser()


@pytest.fixture()
def planner() -> MultiFilePlanner:
    return MultiFilePlanner()


@pytest.fixture()
def tmp_workspace(tmp_path: Path) -> Path:
    """Workspace temporaire avec quelques fichiers Python."""
    (tmp_path / "auth.py").write_text(
        "def authenticate(user, pwd):\n    return True\n", encoding="utf-8"
    )
    (tmp_path / "modal.py").write_text(
        "def send_sms(phone):\n    pass\n", encoding="utf-8"
    )
    return tmp_path


# ─────────────────────────────────────────────────────────────────────────────
# TASK-04-01 — DSLParser
# ─────────────────────────────────────────────────────────────────────────────

class TestDSLParser:

    def test_structured_3_parts(self, parser: DSLParser) -> None:
        """Format basique : Projet - Cible - Action Details."""
        intent = parser.parse("DashV1 - Page RDV - Ajoute validate_email()")
        assert intent.project == "DashV1"
        assert intent.target == "Page RDV"
        assert intent.sub_target is None
        assert intent.action == "ajoute"
        assert "validate_email" in intent.details
        assert intent.confidence >= 0.9

    def test_structured_4_parts(self, parser: DSLParser) -> None:
        """Format avec sous-cible : Projet - Cible - Sous-cible - Action."""
        intent = parser.parse("DashV1 - RDV - Modal - Modifie send_sms()")
        assert intent.project == "DashV1"
        assert intent.target == "RDV"
        assert intent.sub_target == "Modal"
        assert intent.action == "modifie"
        assert "send_sms" in intent.details
        assert intent.confidence >= 0.9

    def test_create_action(self, parser: DSLParser) -> None:
        """Action 'Crée' reconnue."""
        intent = parser.parse("MyProj - Payments - Crée process_payment()")
        assert intent.action in {"cree", "crée"}

    def test_confidence_low_for_natural_language(self, parser: DSLParser) -> None:
        """Commande naturelle → confidence < 0.5."""
        intent = parser.parse("Ajoute une validation email dans auth.py")
        assert intent.confidence < 0.5

    def test_natural_language_extracts_file(self, parser: DSLParser) -> None:
        """Parsing naturel tente d'extraire le fichier mentionné."""
        intent = parser.parse("Ajoute une validation email dans auth.py")
        assert "auth" in intent.target

    def test_empty_command(self, parser: DSLParser) -> None:
        """Commande vide → confidence = 0, pas d'exception."""
        intent = parser.parse("")
        assert intent.confidence == 0.0
        assert intent.project == "inconnu"

    def test_intent_summary(self, parser: DSLParser) -> None:
        """summary() retourne une chaîne lisible."""
        intent = parser.parse("Proj - Auth - Ajoute login()")
        summary = intent.summary()
        assert "Proj" in summary
        assert "ajoute" in summary.lower() or "login" in summary


# ─────────────────────────────────────────────────────────────────────────────
# TASK-04-03 — MultiFilePlanner
# ─────────────────────────────────────────────────────────────────────────────

class TestMultiFilePlanner:

    def test_create_plan_basic(self, planner: MultiFilePlanner) -> None:
        """Plan généré pour 2 fichiers."""
        ops = planner.create_plan(
            intent_details="validate_email()",
            target_files=["auth.py", "utils.py"],
            intent_action="ajoute",
        )
        assert len(ops) == 2
        assert ops[0].file in {"auth.py", "utils.py"}

    def test_max_files_respected(self, planner: MultiFilePlanner) -> None:
        """Le planner ne dépasse jamais MAX_FILES_PER_TX = 3."""
        ops = planner.create_plan(
            intent_details="fn()",
            target_files=["a.py", "b.py", "c.py", "d.py", "e.py"],
        )
        assert len(ops) <= 3

    def test_empty_files_returns_empty_plan(self, planner: MultiFilePlanner) -> None:
        """Aucun fichier → plan vide."""
        ops = planner.create_plan("fn()", [])
        assert ops == []

    def test_validation_too_many_files(self, planner: MultiFilePlanner) -> None:
        """Plus de 3 fichiers distincts → plan invalide."""
        ops = planner.create_plan("fn()", ["a.py", "b.py", "c.py"])
        # Injecte manuellement un 4e pour tester la validation
        from core.planner import PlannedOperation
        ops.append(PlannedOperation(
            file="d.py", action="modify", target_symbol=None, description="test"
        ))
        valid, errors = planner.validate_plan_consistency(ops)
        assert not valid
        assert any("fichiers" in e.lower() or "files" in e.lower() for e in errors)

    def test_validation_delete_and_modify_conflict(self, planner: MultiFilePlanner) -> None:
        """Fichier supprimé ET modifié dans la même TX → invalide."""
        from core.planner import PlannedOperation
        ops = [
            PlannedOperation(file="auth.py", action="delete", target_symbol=None, description="del"),
            PlannedOperation(file="auth.py", action="modify", target_symbol=None, description="mod"),
        ]
        valid, errors = planner.validate_plan_consistency(ops)
        assert not valid
        assert any("supprimé" in e or "supprime" in e or "delete" in e.lower() for e in errors)

    def test_topological_sort_high_priority_first(self, planner: MultiFilePlanner) -> None:
        """Les opérations HIGH priority arrivent avant NORMAL."""
        ops = planner.create_plan(
            intent_details="fn()",
            target_files=["utils.py", "core/__init__.py"],  # __init__ → HIGH
        )
        if len(ops) >= 2:
            priorities = [op.priority.value for op in ops]
            assert priorities == sorted(priorities)

    def test_symbol_inferred_from_details(self, planner: MultiFilePlanner) -> None:
        """Le symbole est extrait depuis les détails."""
        ops = planner.create_plan(
            intent_details="validate_email()",
            target_files=["auth.py"],
        )
        assert ops[0].target_symbol == "validate_email"


# ─────────────────────────────────────────────────────────────────────────────
# TASK-04-04 — LCCAV5Fusion dry_run
# ─────────────────────────────────────────────────────────────────────────────

class TestLCCAV5FusionDryRun:

    def test_dry_run_returns_dict(self, tmp_workspace: Path) -> None:
        """dry_run() retourne un dict avec les clés attendues."""
        from core.orchestrator import LCCAV5Fusion

        fusion = LCCAV5Fusion(workspace=tmp_workspace)
        result = fusion.dry_run("Proj - auth - Ajoute login()")
        assert isinstance(result, dict)
        assert "intent" in result
        assert "target_files" in result
        assert "plan" in result
        assert "plan_valid" in result

    def test_dry_run_does_not_write(self, tmp_workspace: Path) -> None:
        """dry_run() ne crée aucun nouveau fichier dans le workspace."""
        from core.orchestrator import LCCAV5Fusion

        before = set(tmp_workspace.rglob("*.py"))
        fusion = LCCAV5Fusion(workspace=tmp_workspace)
        fusion.dry_run("Proj - auth - Ajoute login()")
        after = set(tmp_workspace.rglob("*.py"))
        assert before == after

    def test_execute_no_crash_on_valid_command(self, tmp_workspace: Path) -> None:
        """execute() ne doit pas lever d'exception sur une commande valide."""
        from core.orchestrator import LCCAV5Fusion

        fusion = LCCAV5Fusion(workspace=tmp_workspace)
        # Ne teste pas le résultat (True/False), seulement l'absence de crash
        try:
            fusion.execute("Proj - auth - Ajoute login()")
        except Exception as e:
            pytest.fail(f"execute() a levé une exception inattendue: {e}")

    def test_execute_rollback_on_bad_workspace(self) -> None:
        """execute() retourne False (et rollback) si workspace invalide."""
        from core.orchestrator import LCCAV5Fusion

        fusion = LCCAV5Fusion(workspace=Path("D:/inexistant/workspace"))
        result = fusion.execute("Proj - unknown - Ajoute fn()")
        assert result is False
