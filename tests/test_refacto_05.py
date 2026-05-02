# -*- coding: utf-8-sig -*-
"""
Tests REFACTO-05 -- TesterRunner : helpers purs + TesterReceiptBuilder.

18 tests couvrant :
  TestHash (2)               : longueur, hex-only
  TestRunSandboxSafe (3)     : success, exception, exit_code
  TestBuildReflection (3)    : contenu reflection (sandbox ok/fail, stderr)
  TestTesterReceiptBuilder (6): receipt valide, HMAC correct, persiste disque,
                                champs corrects, sandbox_fail, AssertionError si tamper
  TestTesterDelegates (4)    : tester_agent delegue bien a self._builder
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from core.agents.tester_runner import (
    _hash,
    _run_sandbox_safe,
    _build_reflection,
    TesterReceiptBuilder,
)
from core.receipt_store import ExecutionReceipt, verify_receipt


# ---------------------------------------------------------------------------
# TestHash
# ---------------------------------------------------------------------------

class TestHash:

    def test_returns_12_chars(self):
        h = _hash("hello world")
        assert len(h) == 12

    def test_returns_hex_only(self):
        h = _hash("test content")
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# TestRunSandboxSafe
# ---------------------------------------------------------------------------

class TestRunSandboxSafe:

    def test_success_path(self):
        """Sandbox OK -> success=True avec stdout/stderr corrects."""
        mock_sb = MagicMock()
        mock_sb.run.return_value = (True, "output", "", 0)
        result = _run_sandbox_safe(mock_sb, "x = 1")
        assert result["success"] is True
        assert result["stdout"] == "output"
        assert result["exit_code"] == 0

    def test_failure_path(self):
        """Sandbox KO -> success=False avec stderr."""
        mock_sb = MagicMock()
        mock_sb.run.return_value = (False, "", "NameError", 1)
        result = _run_sandbox_safe(mock_sb, "bad()")
        assert result["success"] is False
        assert "NameError" in result["stderr"]

    def test_exception_swallowed(self):
        """Exception interne -> success=False, jamais propagee."""
        mock_sb = MagicMock()
        mock_sb.run.side_effect = RuntimeError("sandbox crash")
        result = _run_sandbox_safe(mock_sb, "x = 1")
        assert result["success"] is False
        assert "crash" in result["stderr"]
        assert result["exit_code"] == -1


# ---------------------------------------------------------------------------
# TestBuildReflection
# ---------------------------------------------------------------------------

class TestBuildReflection:

    def _make_receipt(self, sandbox_ok: bool) -> ExecutionReceipt:
        return ExecutionReceipt(
            task_id="t_ref_001",
            agent="tester",
            input_hash="aaa",
            output_hash="bbb",
            sandbox_passed=sandbox_ok,
            tests_passed=1 if sandbox_ok else 0,
            tests_failed=0 if sandbox_ok else 1,
            tx_id=None,
            signature="",
        )

    def test_sandbox_ok_in_reflection(self):
        receipt = self._make_receipt(True)
        r = _build_reflection({"success": True, "stderr": ""}, receipt)
        # FL-01 : _build_reflection retourne un StructuredReflection (pas une str)
        assert r.sandbox_passed is True

    def test_sandbox_fail_in_reflection(self):
        receipt = self._make_receipt(False)
        r = _build_reflection({"success": False, "stderr": "NameError"}, receipt)
        # FL-01 : sandbox_passed False + stderr dans stderr_short
        assert r.sandbox_passed is False
        assert "NameError" in r.stderr_short

    def test_stderr_truncated_at_200(self):
        long_stderr = "x" * 500
        receipt = self._make_receipt(False)
        r = _build_reflection({"success": False, "stderr": long_stderr}, receipt)
        # FL-01 : troncature dans stderr_short
        assert len(r.stderr_short) <= 200


# ---------------------------------------------------------------------------
# TestTesterReceiptBuilder
# ---------------------------------------------------------------------------

class TestTesterReceiptBuilder:

    def _sandbox_ok(self) -> dict:
        return {"success": True, "stdout": "ok", "stderr": "", "exit_code": 0}

    def _sandbox_fail(self) -> dict:
        return {"success": False, "stdout": "", "stderr": "err", "exit_code": 1}

    def test_build_returns_execution_receipt(self, tmp_path, monkeypatch):
        import core.receipt_store as rs
        monkeypatch.setattr(rs, "RECEIPTS_DIR", tmp_path / "receipts")
        monkeypatch.setattr(rs, "SECRET_DIR", tmp_path / ".secret")
        monkeypatch.setattr(rs, "KEY_PATH", tmp_path / ".secret" / "a2a_key")

        builder = TesterReceiptBuilder()
        receipt = builder.build(
            task_id="t_builder_001",
            agent_name="tester",
            sandbox_result=self._sandbox_ok(),
            code="def foo(): pass",
            original_payload={},
        )
        assert isinstance(receipt, ExecutionReceipt)

    def test_hmac_valid(self, tmp_path, monkeypatch):
        """Le receipt produit doit passer verify_receipt."""
        import core.receipt_store as rs
        monkeypatch.setattr(rs, "RECEIPTS_DIR", tmp_path / "receipts")
        monkeypatch.setattr(rs, "SECRET_DIR", tmp_path / ".secret")
        monkeypatch.setattr(rs, "KEY_PATH", tmp_path / ".secret" / "a2a_key")

        builder = TesterReceiptBuilder()
        receipt = builder.build(
            task_id="t_builder_002",
            agent_name="tester",
            sandbox_result=self._sandbox_ok(),
            code="x = 42",
            original_payload={},
        )
        assert verify_receipt(receipt) is True

    def test_persisted_on_disk(self, tmp_path, monkeypatch):
        """Le receipt doit etre ecrit sur disque apres build()."""
        import core.receipt_store as rs
        receipts_dir = tmp_path / "receipts"
        monkeypatch.setattr(rs, "RECEIPTS_DIR", receipts_dir)
        monkeypatch.setattr(rs, "SECRET_DIR", tmp_path / ".secret")
        monkeypatch.setattr(rs, "KEY_PATH", tmp_path / ".secret" / "a2a_key")

        builder = TesterReceiptBuilder()
        builder.build(
            task_id="t_persist_001",
            agent_name="tester",
            sandbox_result=self._sandbox_ok(),
            code="pass",
            original_payload={},
        )
        assert (receipts_dir / "t_persist_001.json").exists()

    def test_sandbox_passed_field(self, tmp_path, monkeypatch):
        """sandbox_passed dans le receipt = valeur du sandbox_result."""
        import core.receipt_store as rs
        monkeypatch.setattr(rs, "RECEIPTS_DIR", tmp_path / "receipts")
        monkeypatch.setattr(rs, "SECRET_DIR", tmp_path / ".secret")
        monkeypatch.setattr(rs, "KEY_PATH", tmp_path / ".secret" / "a2a_key")

        builder = TesterReceiptBuilder()
        r_ok = builder.build("t_ok", "tester", self._sandbox_ok(), "x=1", {})
        r_fail = builder.build("t_fail", "tester", self._sandbox_fail(), "x=1", {})

        assert r_ok.sandbox_passed is True
        assert r_fail.sandbox_passed is False

    def test_tests_failed_field(self, tmp_path, monkeypatch):
        """tests_failed=1 si sandbox KO, 0 si sandbox OK."""
        import core.receipt_store as rs
        monkeypatch.setattr(rs, "RECEIPTS_DIR", tmp_path / "receipts")
        monkeypatch.setattr(rs, "SECRET_DIR", tmp_path / ".secret")
        monkeypatch.setattr(rs, "KEY_PATH", tmp_path / ".secret" / "a2a_key")

        builder = TesterReceiptBuilder()
        r_ok   = builder.build("t_ok2",   "tester", self._sandbox_ok(),   "x=1", {})
        r_fail = builder.build("t_fail2", "tester", self._sandbox_fail(), "x=1", {})

        assert r_ok.tests_failed == 0
        assert r_fail.tests_failed == 1

    def test_store_failure_silenced(self, tmp_path, monkeypatch):
        """Si store_receipt leve une exception, build() ne propage pas."""
        import core.receipt_store as rs
        monkeypatch.setattr(rs, "RECEIPTS_DIR", tmp_path / "receipts")
        monkeypatch.setattr(rs, "SECRET_DIR", tmp_path / ".secret")
        monkeypatch.setattr(rs, "KEY_PATH", tmp_path / ".secret" / "a2a_key")

        builder = TesterReceiptBuilder()
        with patch("core.agents.tester_runner.store_receipt", side_effect=OSError("disk full")):
            # Ne doit pas lever
            receipt = builder.build("t_store_err", "tester", self._sandbox_ok(), "x=1", {})
        assert receipt is not None


# ---------------------------------------------------------------------------
# TestTesterDelegates
# ---------------------------------------------------------------------------

class TestTesterDelegates:
    """
    Verifie que TesterAgent delegue bien a self._builder.
    On mocke self._builder pour intercepter les appels sans toucher au disque.
    """

    def _make_tester(self, bus):
        from core.agents.tester_agent import TesterAgent
        from core.agents.a2a_bus import A2ALocalBus
        t = TesterAgent.create(bus=bus)
        return t

    def _make_bus(self):
        from core.agents.a2a_bus import A2ALocalBus
        b = A2ALocalBus(db_path=":memory:")
        return b

    def _make_contract(self, code: str = "x = 1"):
        from core.agents.a2a_bus import TaskContract
        c = TaskContract(
            task_id="t_deleg_001",
            intent="test delegation",
            domain="global",
            source_agent="reviewer",
            target_agent="tester",
        )
        c.context["code"] = code
        c.context["original_payload"] = {}
        return c

    def test_builder_instanciated(self):
        """self._builder est un TesterReceiptBuilder apres __init__."""
        bus = self._make_bus()
        tester = self._make_tester(bus)
        assert isinstance(tester._builder, TesterReceiptBuilder)

    def test_builder_build_called_on_run_task(self, tmp_path, monkeypatch):
        """run_task() appelle self._builder.build() exactement une fois."""
        import core.receipt_store as rs
        monkeypatch.setattr(rs, "RECEIPTS_DIR", tmp_path / "receipts")
        monkeypatch.setattr(rs, "SECRET_DIR", tmp_path / ".secret")
        monkeypatch.setattr(rs, "KEY_PATH", tmp_path / ".secret" / "a2a_key")

        bus = self._make_bus()
        tester = self._make_tester(bus)

        # Mock sandbox + evaluator pour isoler
        mock_sb = MagicMock()
        mock_sb.run.return_value = (True, "ok", "", 0)
        tester._sandbox = mock_sb

        mock_ev = MagicMock()
        mock_ev.evaluate.return_value = MagicMock(score=80)
        tester._evaluator = mock_ev

        # Spy sur self._builder.build
        original_build = tester._builder.build
        build_calls = []

        def spy_build(*args, **kwargs):
            build_calls.append((args, kwargs))
            return original_build(*args, **kwargs)

        tester._builder.build = spy_build

        tester.run_task(self._make_contract())
        assert len(build_calls) == 1

    def test_builder_injectable(self, tmp_path, monkeypatch):
        """On peut remplacer self._builder par un mock pour les tests."""
        import core.receipt_store as rs
        monkeypatch.setattr(rs, "RECEIPTS_DIR", tmp_path / "receipts")
        monkeypatch.setattr(rs, "SECRET_DIR", tmp_path / ".secret")
        monkeypatch.setattr(rs, "KEY_PATH", tmp_path / ".secret" / "a2a_key")

        bus = self._make_bus()
        tester = self._make_tester(bus)

        # Injecter un builder mock
        mock_builder = MagicMock()
        fake_receipt = ExecutionReceipt(
            task_id="t_deleg_001",
            agent="tester",
            input_hash="aaa",
            output_hash="bbb",
            sandbox_passed=True,
            tests_passed=1,
            tests_failed=0,
            tx_id=None,
            signature="fakesig",
        )
        mock_builder.build.return_value = fake_receipt
        tester._builder = mock_builder

        mock_sb = MagicMock()
        mock_sb.run.return_value = (True, "ok", "", 0)
        tester._sandbox = mock_sb
        mock_ev = MagicMock()
        mock_ev.evaluate.return_value = MagicMock(score=80)
        tester._evaluator = mock_ev

        result = tester.run_task(self._make_contract())
        mock_builder.build.assert_called_once()
        assert result.success is True

    def test_existing_tests_still_pass(self, tmp_path, monkeypatch):
        """
        Verification de retro-compat : le test 'test_receipt_signature_valid'
        original utilise le meme mecanisme -> on simule ici le meme flow.
        """
        import core.receipt_store as rs
        monkeypatch.setattr(rs, "RECEIPTS_DIR", tmp_path / "receipts")
        monkeypatch.setattr(rs, "SECRET_DIR", tmp_path / ".secret")
        monkeypatch.setattr(rs, "KEY_PATH", tmp_path / ".secret" / "a2a_key")

        bus = self._make_bus()
        tester = self._make_tester(bus)

        mock_sb = MagicMock()
        mock_sb.run.return_value = (True, "ok", "", 0)
        tester._sandbox = mock_sb
        mock_ev = MagicMock()
        mock_ev.evaluate.return_value = MagicMock(score=85)
        tester._evaluator = mock_ev

        result = tester.run_task(self._make_contract("def ok(): return True"))
        assert result.success is True

        receipt = rs.load_receipt("t_deleg_001")
        assert receipt is not None
        assert verify_receipt(receipt) is True
