# -*- coding: utf-8-sig -*-
"""test_spec_orchestrator.py — 12 tests Sprint 15 (Orchestrator + MCP Spec tools).
Sprint 20 — Migration V7.2 : _mock_memory(has_specs=True) crée les specs avec
            validated=True pour que is_usable() retourne True (logique V7.2).
Sprint 22 — test_generate_spec_tool_success vérifie domain, validated, complexity_score
            (champs V7.2 obligatoires dans la réponse MCP generate_spec).
"""
from __future__ import annotations
import json
import pytest
from unittest.mock import MagicMock, patch

from core.orchestrator import LCCAV5Fusion
from core.mcp_server import McpServer
from core.spec_entry import SpecEntry, make_spec_id
from core.spec_validator import SpecValidatorService


# ── Helpers ──────────────────────────────────────────────────────────────────

def _mock_memory(has_specs: bool = False) -> MagicMock:
    mem = MagicMock()
    if has_specs:
        sid = make_spec_id("Titre test", "Abstract de test.")
        # Sprint 20 : validated=True obligatoire pour is_usable() V7.2
        spec = SpecEntry(
            spec_id=sid,
            title="Titre test",
            abstract="Abstract de test.",
            body_md="## Corps\n\n" + "x" * 60,
            score=0.9,
            validated=True,   # V7.2 — Règle 11
        )
        entry = MagicMock()
        entry.metadata = spec.to_dict()
        mem.search.return_value = {"lcca_specs": [entry], "lcca_failures": []}
    else:
        mem.search.return_value = {"lcca_specs": [], "lcca_failures": []}
    mem.store.return_value = MagicMock(
        stored=True, collection="lcca_specs", entry_id="abc", reason="ok"
    )
    return mem


def _mock_estimator(need_spec: bool, score: int = 70) -> MagicMock:
    est = MagicMock()
    est.estimate.return_value = (need_spec, score)
    return est


def _mock_spec_generator(valid: bool = True) -> MagicMock:
    gen = MagicMock()
    sid = make_spec_id("Generated spec", "Abstract generee.")
    # Sprint 20 : validated=True si valid=True pour is_usable() V7.2
    spec = SpecEntry(
        spec_id=sid,
        title="Generated spec",
        abstract="Abstract generee.",
        body_md="## Corps\n\n" + "x" * 60,
        score=0.95 if valid else 0.3,
        validated=valid,   # V7.2 — Règle 11
    )
    gen.generate.return_value = spec
    gen.auto_fix.return_value = spec
    return gen


def _make_orchestrator(
    need_spec: bool = False,
    has_specs: bool = False,
    gen_valid: bool = True,
) -> LCCAV5Fusion:
    """
    Factory : LCCAV5Fusion construit via __new__ avec toutes les deps mockées.
    On évite d'appeler __init__ (qui instancie des deps réelles et fait de l'I/O).
    """
    orch = object.__new__(LCCAV5Fusion)

    # Attributs core
    orch.workspace   = MagicMock()
    orch.tx_manager  = MagicMock()
    orch.indexer     = MagicMock()
    orch.dep_graph   = MagicMock()
    orch.patcher     = MagicMock()
    orch.selector    = MagicMock()
    orch.planner     = MagicMock()
    orch.llm         = MagicMock()
    orch.llm.is_available.return_value = False

    # Spec Layer
    orch._memory         = _mock_memory(has_specs)
    orch._complexity     = _mock_estimator(need_spec)
    orch._spec_generator = _mock_spec_generator(gen_valid)
    orch._spec_validator = SpecValidatorService()

    return orch


def _initialized_mcp_server(**kwargs) -> McpServer:
    server = McpServer(**kwargs)
    server.handle({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "clientInfo": {}},
    })
    server.handle({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    return server


# ── TestAdaptiveSpec ──────────────────────────────────────────────────────────

class TestAdaptiveSpec:

    def test_simple_task_skips_spec_layer(self):
        """Score < 60 → _run_spec_layer retourne True sans générer."""
        orch = _make_orchestrator(need_spec=False)
        with patch("config.ADAPTIVE_SPEC_ENABLED", True):
            result = orch._run_spec_layer(
                MagicMock(raw="rename x", details="rename x", target_files=[])
            )
        assert result is True
        orch._spec_generator.generate.assert_not_called()

    def test_complex_task_generates_spec(self):
        """Score >= 60, pas de spec en mémoire → generate() appelé."""
        orch = _make_orchestrator(need_spec=True, has_specs=False, gen_valid=True)
        intent = MagicMock(
            raw="refactor transaction rollback",
            details="refactor transaction rollback",
            target_files=[],
        )
        with patch("config.ADAPTIVE_SPEC_ENABLED", True):
            result = orch._run_spec_layer(intent)
        assert result is True
        orch._spec_generator.generate.assert_called_once()

    def test_reuse_existing_validated_spec(self):
        """Hit mémoire avec spec usable (validated=True) → pas de génération."""
        orch = _make_orchestrator(need_spec=True, has_specs=True)
        intent = MagicMock(
            raw="refactor transaction", details="refactor transaction", target_files=[]
        )
        with patch("config.ADAPTIVE_SPEC_ENABLED", True):
            result = orch._run_spec_layer(intent)
        assert result is True
        orch._spec_generator.generate.assert_not_called()

    def test_adaptive_spec_blocks_invalid_spec(self):
        """Spec invalide meme apres auto-fix -> _run_spec_layer retourne False.
        body_md contient apply_patch + write_text -> R01 blocking -> valid=False.
        """
        orch = _make_orchestrator(need_spec=True, has_specs=False)
        bad_body = "## Corps\n\nAppelle apply_patch() puis write_text() directement.\n" + "x" * 30
        bad_spec = SpecEntry(
            spec_id="a" * 12,
            title="spec invalide",
            abstract="abs",
            body_md=bad_body,
            score=0.1,
            validated=False,
        )
        orch._spec_generator.generate.return_value = bad_spec
        orch._spec_generator.auto_fix.return_value = bad_spec

        intent = MagicMock(
            raw="refactor architecture", details="refactor architecture", target_files=[]
        )
        with patch("config.ADAPTIVE_SPEC_ENABLED", True):
            result = orch._run_spec_layer(intent)
        assert result is False

    def test_invalid_spec_stored_in_lcca_failures(self):
        """Spec invalide -> store() appele avec collection contenant 'failure'.
        body_md contient apply_patch + write_text -> R01 blocking -> valid=False.
        """
        orch = _make_orchestrator(need_spec=True, has_specs=False)
        bad_body = "## Corps\n\nAppelle apply_patch() puis write_text() directement.\n" + "x" * 30
        bad_spec = SpecEntry(
            spec_id="a" * 12,
            title="spec invalide",
            abstract="abs",
            body_md=bad_body,
            score=0.1,
            validated=False,
        )
        orch._spec_generator.generate.return_value = bad_spec
        orch._spec_generator.auto_fix.return_value = bad_spec

        intent = MagicMock(
            raw="refactor architecture", details="refactor architecture", target_files=[]
        )
        with patch("config.ADAPTIVE_SPEC_ENABLED", True):
            orch._run_spec_layer(intent)

        calls = orch._memory.store.call_args_list
        assert any(
            "failure" in str(c) for c in calls
        ), f"store() pas appele avec lcca_failures. Appels : {calls}"

    def test_valid_spec_stored_in_lcca_specs(self):
        """Spec valide → store() appelé au moins une fois."""
        orch = _make_orchestrator(need_spec=True, has_specs=False, gen_valid=True)
        intent = MagicMock(
            raw="refactor transaction", details="refactor transaction", target_files=[]
        )
        with patch("config.ADAPTIVE_SPEC_ENABLED", True):
            result = orch._run_spec_layer(intent)
        assert result is True
        orch._memory.store.assert_called()

    def test_usage_count_incremented_on_reuse(self):
        """Réutilisation d'une spec existante → search() appelé (hit mémoire)."""
        orch = _make_orchestrator(need_spec=True, has_specs=True)
        intent = MagicMock(
            raw="refactor transaction", details="refactor transaction", target_files=[]
        )
        with patch("config.ADAPTIVE_SPEC_ENABLED", True):
            result = orch._run_spec_layer(intent)
        assert result is True
        assert orch._memory.search.called

    def test_adaptive_spec_disabled_skips_layer(self):
        """ADAPTIVE_SPEC_ENABLED=False → estimate() jamais appelé."""
        orch = _make_orchestrator(need_spec=True)
        orch.selector.select.return_value = []  # stoppe le pipeline V5

        with patch("config.ADAPTIVE_SPEC_ENABLED", False):
            orch.execute("rename x to y", adaptive_spec=True)

        orch._complexity.estimate.assert_not_called()


# ── TestMcpSpecTools ──────────────────────────────────────────────────────────

class TestMcpSpecTools:

    def _mock_generator_svc(self) -> MagicMock:
        gen = MagicMock()
        sid = make_spec_id("Generated spec", "Abstract generee.")
        spec = SpecEntry(
            spec_id=sid,
            title="Generated spec",
            abstract="Abstract generee.",
            body_md="## Corps\n\n" + "x" * 60,
            score=0.95,
            validated=True,   # V7.2
        )
        gen.generate.return_value = spec
        return gen

    def test_generate_spec_tool_success(self):
        """generate_spec tool → JSON-RPC 2.0 réponse avec spec_id + champs V7.2.

        Sprint 22 : domain, validated, complexity_score, version obligatoires dans
        la réponse MCP (conformité checklist V7.2 generate_spec).
        Sprint CTX-04 : auto_stored présent dans la réponse.
        """
        server = _initialized_mcp_server(
            memory_engine=_mock_memory(),
            spec_generator=self._mock_generator_svc(),
            spec_validator=SpecValidatorService(),
        )
        response = server.handle({
            "jsonrpc": "2.0", "id": 10, "method": "tools/call",
            "params": {
                "name": "generate_spec",
                "arguments": {"intent": "Add sandbox", "domain": "sandbox"},
            },
        })
        assert response["id"] == 10
        assert "result" in response
        content = json.loads(response["result"]["content"][0]["text"])
        # Champs identité
        assert "spec_id" in content
        assert len(content["spec_id"]) == 12
        # Champs V7.2 Sprint 22
        assert "domain" in content
        assert "validated" in content
        assert "complexity_score" in content
        assert "version" in content
        assert isinstance(content["validated"], bool)
        assert isinstance(content["complexity_score"], int)
        # Champ CTX-04
        assert "auto_stored" in content
        assert isinstance(content["auto_stored"], bool)

    def test_generate_spec_auto_stored_on_valid(self):
        """CTX-04 : spec valide → memory.store() appelé avec lcca_specs."""
        mem = _mock_memory()
        server = _initialized_mcp_server(
            memory_engine=mem,
            spec_generator=self._mock_generator_svc(),
            spec_validator=SpecValidatorService(),
        )
        server.handle({
            "jsonrpc": "2.0", "id": 20, "method": "tools/call",
            "params": {
                "name": "generate_spec",
                "arguments": {"intent": "Add sandbox", "domain": "sandbox"},
            },
        })
        # store() doit avoir été appelé avec collection="lcca_specs"
        calls = mem.store.call_args_list
        assert any(
            "lcca_specs" in str(c) for c in calls
        ), f"store() pas appelé avec lcca_specs. Appels : {calls}"

    def test_generate_spec_not_stored_if_invalid(self):
        """CTX-04 : spec invalide -> memory.store() NOT appele avec lcca_specs.
        body_md contient apply_patch + write_text -> R01 blocking -> valid=False.
        """
        mem = _mock_memory()
        gen = MagicMock()
        sid = make_spec_id("Invalid spec", "Abstract invalide.")
        bad_body = "## Corps\n\nAppelle apply_patch() puis write_text() directement.\n" + "x" * 30
        bad_spec = SpecEntry(
            spec_id=sid,
            title="Invalid spec",
            abstract="Abstract invalide.",
            body_md=bad_body,
            score=0.1,
            validated=False,
        )
        gen.generate.return_value = bad_spec
        server = _initialized_mcp_server(
            memory_engine=mem,
            spec_generator=gen,
            spec_validator=SpecValidatorService(),
        )
        server.handle({
            "jsonrpc": "2.0", "id": 21, "method": "tools/call",
            "params": {
                "name": "generate_spec",
                "arguments": {"intent": "Bad spec", "domain": "global"},
            },
        })
        calls = mem.store.call_args_list
        # Aucun store avec lcca_specs ne doit avoir ete fait
        assert not any(
            "lcca_specs" in str(c) for c in calls
        ), f"store() appele a tort avec lcca_specs. Appels : {calls}"

    def test_generate_spec_tool_missing_intent(self):
        """generate_spec sans 'intent' → erreur -32602."""
        server = _initialized_mcp_server(memory_engine=_mock_memory())
        response = server.handle({
            "jsonrpc": "2.0", "id": 11, "method": "tools/call",
            "params": {"name": "generate_spec", "arguments": {"domain": "sandbox"}},
        })
        assert response["error"]["code"] == -32602

    def test_validate_spec_tool_with_body_md(self):
        """validate_spec avec body_md direct → réponse valide."""
        server = _initialized_mcp_server(
            memory_engine=_mock_memory(),
            spec_validator=SpecValidatorService(),
        )
        body = "## Corps\n\n" + "x" * 60
        response = server.handle({
            "jsonrpc": "2.0", "id": 12, "method": "tools/call",
            "params": {"name": "validate_spec", "arguments": {"body_md": body}},
        })
        assert "result" in response
        content = json.loads(response["result"]["content"][0]["text"])
        assert "valid" in content
        assert "score" in content

    def test_validate_spec_tool_unknown_id(self):
        """validate_spec avec spec_id introuvable → erreur -32602."""
        server = _initialized_mcp_server(memory_engine=_mock_memory(has_specs=False))
        response = server.handle({
            "jsonrpc": "2.0", "id": 13, "method": "tools/call",
            "params": {
                "name": "validate_spec",
                "arguments": {"spec_id": "aabbccddeeff"},
            },
        })
        assert response["error"]["code"] == -32602
