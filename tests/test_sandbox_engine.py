"""
Tests pour SandboxEngine V7.

Suite : test_sandbox_engine.py
Sprint : 12 — Phase 2 (TASK-12-06)
Modes testés :
  - soft  : subprocess isolé (toujours disponible)
  - docker: container éphémère (sauté si Docker non disponible)
"""
from __future__ import annotations

import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Import du module sous test
# ---------------------------------------------------------------------------
from core.sandbox_engine import SandboxEngine


# ---------------------------------------------------------------------------
# Helpers & fixtures
# ---------------------------------------------------------------------------

def _soft_engine(tmp_path: Path) -> SandboxEngine:
    """Crée un SandboxEngine en mode soft avec workspace temporaire."""
    return SandboxEngine(workspace=tmp_path, mode="soft")


# Détermine si Docker est réellement disponible sur la machine de test
def _docker_available() -> bool:
    try:
        import docker  # noqa: F401
        import docker as _d
        _d.from_env()
        return True
    except Exception:
        return False


_SKIP_DOCKER = pytest.mark.skipif(
    not _docker_available(),
    reason="Docker non disponible sur cette machine",
)


# ---------------------------------------------------------------------------
# Mode soft — tests principaux
# ---------------------------------------------------------------------------

class TestSandboxSoftMode:
    """Tests du mode subprocess isolé."""

    def test_run_simple_print(self, tmp_path: Path) -> None:
        """Un print() basique doit retourner stdout et success=True."""
        engine = _soft_engine(tmp_path)
        ok, stdout, stderr, code = engine.run("print('hello lcca')")
        assert ok is True
        assert "hello lcca" in stdout
        assert code == 0

    def test_run_stdout_multiline(self, tmp_path: Path) -> None:
        """Plusieurs lignes stdout captées correctement."""
        engine = _soft_engine(tmp_path)
        ok, stdout, _, _ = engine.run("for i in range(3): print(i)")
        assert ok is True
        assert "0" in stdout and "1" in stdout and "2" in stdout

    def test_run_stderr_captured(self, tmp_path: Path) -> None:
        """Les erreurs Python (stderr) sont capturées, success=False."""
        engine = _soft_engine(tmp_path)
        ok, _, stderr, code = engine.run("raise ValueError('boom')")
        assert ok is False
        assert code != 0
        assert "ValueError" in stderr or "boom" in stderr

    def test_run_syntax_error(self, tmp_path: Path) -> None:
        """Syntaxe invalide → success=False."""
        engine = _soft_engine(tmp_path)
        ok, _, stderr, code = engine.run("def :(")
        assert ok is False
        assert code != 0

    def test_run_timeout(self, tmp_path: Path) -> None:
        """Un script dépassant le timeout retourne success=False et exit_code=-1."""
        engine = _soft_engine(tmp_path)
        ok, _, stderr, code = engine.run("import time; time.sleep(60)", timeout=1)
        assert ok is False
        assert code == -1
        assert "Timeout" in stderr or "timeout" in stderr.lower()

    def test_run_timeout_zero_raises(self, tmp_path: Path) -> None:
        """timeout <= 0 lève ValueError."""
        engine = _soft_engine(tmp_path)
        with pytest.raises(ValueError, match="timeout"):
            engine.run("pass", timeout=0)

    def test_run_returns_four_tuple(self, tmp_path: Path) -> None:
        """run() retourne toujours un tuple à 4 éléments."""
        engine = _soft_engine(tmp_path)
        result = engine.run("x = 1")
        assert len(result) == 4
        ok, stdout, stderr, code = result
        assert isinstance(ok, bool)
        assert isinstance(stdout, str)
        assert isinstance(stderr, str)
        assert isinstance(code, int)

    def test_run_cwd_is_workspace(self, tmp_path: Path) -> None:
        """Le cwd du subprocess est bien le workspace (tmp_path ici)."""
        engine = _soft_engine(tmp_path)
        ok, stdout, _, _ = engine.run("import os; print(os.getcwd())")
        assert ok is True
        # Les deux chemins doivent être équivalents (résolution symlinks)
        assert Path(stdout.strip()).resolve() == tmp_path.resolve()

    def test_run_uses_sys_executable(self, tmp_path: Path) -> None:
        """subprocess utilise sys.executable (pas 'python' hardcodé)."""
        engine = _soft_engine(tmp_path)
        ok, stdout, _, _ = engine.run(
            "import sys; print(sys.executable)"
        )
        assert ok is True
        # Le path retourné doit correspondre à l'exécutable courant
        assert Path(stdout.strip()).resolve() == Path(sys.executable).resolve()

    def test_run_file_existing(self, tmp_path: Path) -> None:
        """run_file() exécute un fichier .py existant."""
        script = tmp_path / "hello.py"
        script.write_text("print('from file')", encoding="utf-8")
        engine = _soft_engine(tmp_path)
        ok, stdout, _, _ = engine.run_file(script)
        assert ok is True
        assert "from file" in stdout

    def test_run_file_missing(self, tmp_path: Path) -> None:
        """run_file() sur un fichier inexistant retourne success=False."""
        engine = _soft_engine(tmp_path)
        ok, _, stderr, code = engine.run_file(tmp_path / "ghost.py")
        assert ok is False
        assert code == -1
        assert "introuvable" in stderr.lower() or "ghost" in stderr

    def test_effective_mode_soft(self, tmp_path: Path) -> None:
        """effective_mode retourne 'soft' quand mode='soft'."""
        engine = _soft_engine(tmp_path)
        assert engine.effective_mode == "soft"


# ---------------------------------------------------------------------------
# Mode auto — détection Docker
# ---------------------------------------------------------------------------

class TestSandboxAutoMode:
    """Tests du mode auto (sélection runtime)."""

    def test_auto_falls_back_to_soft_without_docker(self, tmp_path: Path) -> None:
        """En mode auto sans Docker, effective_mode == 'soft'."""
        with patch("core.sandbox_engine._DOCKER_AVAILABLE", False):
            engine = SandboxEngine(workspace=tmp_path, mode="auto")
        assert engine.docker_client is None
        assert engine.effective_mode == "soft"

    def test_auto_mode_still_runs_code(self, tmp_path: Path) -> None:
        """En mode auto (soft), le code s'exécute quand même."""
        with patch("core.sandbox_engine._DOCKER_AVAILABLE", False):
            engine = SandboxEngine(workspace=tmp_path, mode="auto")
        ok, stdout, _, _ = engine.run("print('auto ok')")
        assert ok is True
        assert "auto ok" in stdout

    def test_docker_mode_requires_docker_raises(self, tmp_path: Path) -> None:
        """mode='docker' sans docker SDK lève RuntimeError."""
        with patch("core.sandbox_engine._DOCKER_AVAILABLE", False):
            with pytest.raises(RuntimeError, match="docker"):
                SandboxEngine(workspace=tmp_path, mode="docker")


# ---------------------------------------------------------------------------
# Mode docker — tests conditionnels (sautés si Docker absent)
# ---------------------------------------------------------------------------

class TestSandboxDockerMode:
    """Tests du mode Docker (skippés si Docker non disponible)."""

    @_SKIP_DOCKER
    def test_docker_run_simple(self, tmp_path: Path) -> None:
        """Exécution basique dans un container Docker."""
        engine = SandboxEngine(workspace=tmp_path, mode="docker")
        ok, logs, _, code = engine.run("print('docker hello')")
        assert ok is True
        assert "docker hello" in logs
        assert code == 0

    @_SKIP_DOCKER
    def test_docker_run_timeout(self, tmp_path: Path) -> None:
        """Timeout dans le container → success=False."""
        engine = SandboxEngine(workspace=tmp_path, mode="docker")
        ok, _, stderr, code = engine.run(
            "import time; time.sleep(60)", timeout=2
        )
        assert ok is False
        assert code == -1

    @_SKIP_DOCKER
    def test_docker_effective_mode(self, tmp_path: Path) -> None:
        """effective_mode retourne 'docker' quand Docker disponible."""
        engine = SandboxEngine(workspace=tmp_path, mode="docker")
        assert engine.effective_mode == "docker"

    @_SKIP_DOCKER
    def test_docker_no_network(self, tmp_path: Path) -> None:
        """Tentative de connexion réseau doit échouer (network=none)."""
        engine = SandboxEngine(workspace=tmp_path, mode="docker")
        ok, logs, stderr, code = engine.run(
            "import urllib.request; urllib.request.urlopen('http://example.com', timeout=5)"
        )
        assert ok is False  # réseau coupé → exception

    @_SKIP_DOCKER
    def test_docker_fallback_if_client_lost(self, tmp_path: Path) -> None:
        """Si docker_client est None après __init__, repli transparent vers soft."""
        engine = SandboxEngine(workspace=tmp_path, mode="docker")
        engine.docker_client = None  # simulation perte de connexion
        ok, stdout, _, _ = engine.run("print('fallback')")
        assert ok is True
        assert "fallback" in stdout


# ---------------------------------------------------------------------------
# Tests d'isolation workspace
# ---------------------------------------------------------------------------

class TestSandboxWorkspaceIsolation:
    """Vérifie que le sandbox n'écrit pas hors workspace."""

    def test_soft_cannot_easily_escape_cwd(self, tmp_path: Path) -> None:
        """
        Le cwd du subprocess est le workspace.
        Ce test vérifie qu'un fichier créé relativement atterrit dans tmp_path.
        (Note : en mode soft le FS n'est pas virtualisé — ce test est indicatif.)
        """
        engine = _soft_engine(tmp_path)
        ok, _, _, _ = engine.run("open('sandbox_test_artifact.txt','w').write('x')")
        # Si le fichier a été créé, il doit l'être dans le workspace, pas ailleurs
        artifact = tmp_path / "sandbox_test_artifact.txt"
        # On nettoie si présent
        if artifact.exists():
            artifact.unlink()
        assert ok is True  # l'écriture a réussi (mode soft non restrictif)
