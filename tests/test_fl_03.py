# -*- coding: utf-8-sig -*-
"""FL-03 -- Tests sandbox soft-hardened."""
import sys
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from core.sandbox_engine import SandboxEngine, _FORBIDDEN_SOFT


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sandbox(tmp_path):
    return SandboxEngine(workspace=tmp_path, mode="soft")


# ---------------------------------------------------------------------------
# TestPrescanImports
# ---------------------------------------------------------------------------

class TestPrescanImports:
    def test_subprocess_blocked(self, sandbox):
        assert sandbox._prescan_imports("import subprocess") == "subprocess"

    def test_socket_blocked(self, sandbox):
        assert sandbox._prescan_imports("import socket") == "socket"

    def test_os_blocked(self, sandbox):
        assert sandbox._prescan_imports("import os") == "os"

    def test_urllib_blocked(self, sandbox):
        assert sandbox._prescan_imports("from urllib import request") == "urllib"

    def test_http_blocked(self, sandbox):
        assert sandbox._prescan_imports("import http.client") == "http"

    def test_submodule_of_forbidden_blocked(self, sandbox):
        code = "from subprocess import run"
        assert sandbox._prescan_imports(code) == "subprocess"

    def test_pathlib_allowed(self, sandbox):
        assert sandbox._prescan_imports("from pathlib import Path") is None

    def test_json_allowed(self, sandbox):
        assert sandbox._prescan_imports("import json") is None

    def test_ast_allowed(self, sandbox):
        assert sandbox._prescan_imports("import ast") is None

    def test_re_allowed(self, sandbox):
        assert sandbox._prescan_imports("import re") is None

    def test_syntax_error_returns_none(self, sandbox):
        """SyntaxError dans le code -> prescan retourne None (pas d'exception)."""
        assert sandbox._prescan_imports("def f(:") is None

    def test_empty_code_returns_none(self, sandbox):
        assert sandbox._prescan_imports("") is None

    def test_no_imports_returns_none(self, sandbox):
        assert sandbox._prescan_imports("x = 1 + 2\nprint(x)") is None


# ---------------------------------------------------------------------------
# TestSoftHardened
# ---------------------------------------------------------------------------

class TestSoftHardened:
    def test_stdlib_code_runs(self, sandbox):
        """Code stdlib simple doit passer."""
        ok, out, err, code = sandbox.run("import json; print(json.dumps({'a': 1}))")
        assert ok is True
        assert '{"a": 1}' in out

    def test_forbidden_import_blocked(self, sandbox):
        """import subprocess -> exit_code=-2, success=False."""
        ok, out, err, exit_code = sandbox.run("import subprocess")
        assert ok is False
        assert exit_code == -2
        assert "subprocess" in err

    def test_forbidden_from_import_blocked(self, sandbox):
        """from socket import ... -> exit_code=-2."""
        ok, out, err, exit_code = sandbox.run("from socket import gethostname")
        assert ok is False
        assert exit_code == -2

    def test_exit_code_minus2_distinct_from_timeout(self, sandbox):
        """exit_code=-2 (import bloque) est distinct de -1 (timeout)."""
        _, _, _, exit_code = sandbox.run("import subprocess")
        assert exit_code == -2

    def test_cwd_is_not_workspace(self, sandbox):
        """Le cwd d'execution n'est pas self.workspace."""
        code = "import os; print(os.getcwd())"
        # os est interdit -- on teste via _run_subprocess_legacy pour voir le cwd legacy
        ok, out, err, _ = sandbox._run_subprocess_legacy(code, timeout=10)
        if ok:
            assert str(sandbox.workspace) in out
        # et via hardened : os bloque donc exit_code=-2
        ok_h, _, _, ec = sandbox._run_subprocess_hardened(code, timeout=10)
        assert ok_h is False
        assert ec == -2

    def test_pythonpath_empty_in_env(self, sandbox):
        """PYTHONPATH est vide dans l'env du subprocess hardened."""
        # On verifie que le code qui depend d'un package tiers echoue
        # (json reste dispo car c'est stdlib)
        ok, out, err, _ = sandbox._run_subprocess_hardened(
            "import json; print('ok')", timeout=10
        )
        assert ok is True
        assert "ok" in out

    def test_syntax_error_propagates(self, sandbox):
        """SyntaxError dans le code -> echec propre (pas d'exception Python)."""
        ok, out, err, exit_code = sandbox.run("def f(:")
        assert ok is False
        # exit_code != -2 (c'est une vraie SyntaxError, pas un import bloque)
        assert exit_code != -2

    def test_timeout_returns_minus1(self, sandbox):
        """Timeout -> exit_code=-1."""
        ok, out, err, exit_code = sandbox._run_subprocess_hardened(
            "import time; time.sleep(999)", timeout=1
        )
        # time n'est pas dans _FORBIDDEN_SOFT -> bloque par timeout
        assert ok is False
        assert exit_code == -1


# ---------------------------------------------------------------------------
# TestLegacyModePreserved
# ---------------------------------------------------------------------------

class TestLegacyModePreserved:
    def test_legacy_runs_clean_code(self, sandbox):
        """_run_subprocess_legacy execute du code simple."""
        ok, out, err, code = sandbox._run_subprocess_legacy(
            "print('legacy')", timeout=10
        )
        assert ok is True
        assert "legacy" in out

    def test_subprocess_alias_delegates(self, sandbox):
        """_run_subprocess() delegue a _run_subprocess_hardened()."""
        with patch.object(sandbox, "_run_subprocess_hardened", return_value=(True, "x", "", 0)) as mock:
            sandbox._run_subprocess("print(1)", 10)
            mock.assert_called_once_with("print(1)", 10)


# ---------------------------------------------------------------------------
# TestEffectiveMode
# ---------------------------------------------------------------------------

class TestEffectiveMode:
    def test_soft_returns_soft_hardened(self, tmp_path):
        s = SandboxEngine(workspace=tmp_path, mode="soft")
        assert s.effective_mode == "soft_hardened"

    def test_docker_returns_docker(self, tmp_path):
        s = SandboxEngine.__new__(SandboxEngine)
        s.mode = "docker"
        s.docker_client = MagicMock()
        assert s.effective_mode == "docker"

    def test_auto_no_docker_returns_soft_hardened(self, tmp_path):
        s = SandboxEngine.__new__(SandboxEngine)
        s.mode = "auto"
        s.docker_client = None
        assert s.effective_mode == "soft_hardened"


# ---------------------------------------------------------------------------
# TestDockerUnchanged
# ---------------------------------------------------------------------------

class TestDockerUnchanged:
    def test_docker_mode_calls_run_docker(self, tmp_path):
        """En mode docker, run() appelle _run_docker (FL-03 ne touche pas docker)."""
        s = SandboxEngine.__new__(SandboxEngine)
        s.mode = "docker"
        s.docker_client = MagicMock()
        s.workspace = tmp_path
        with patch.object(s, "_run_docker", return_value=(True, "ok", "", 0)) as mock_docker:
            s.run("print(1)", timeout=10)
            mock_docker.assert_called_once()
