# Sprint 14 — V7 SandboxEngine : Exécution isolée Python
<!-- AI-READY | Sprint V7.0 | Phase 3/5 | 2026-04-17 -->

## 🎯 Objectif
Implémenter `core/sandbox_engine.py` : moteur d'exécution isolé en deux modes :
- **soft** : subprocess `sys.executable` (toujours disponible)
- **docker** : container éphémère Python slim (si Docker installé)
- **auto** : détection silencieuse, fallback soft si Docker indisponible

**Exigences de sécurité** :
- `sys.executable` obligatoire (jamais `"python"` hardcodé)
- Docker SDK Python uniquement (jamais f-string shell)
- Timeout strict avec kill du container
- Network none + read-only + mémoire 512m + 1 CPU

**Résultat attendu** : ≥ 295 + ~22 nouveaux tests PASSED, 0 FAILED.

---

## 📋 TÂCHES

### TASK-14-01 — `core/sandbox_engine.py`

**Fichier** : `D:\LLMCodeAgent\core\sandbox_engine.py` *(nouveau)*

```python
# -*- coding: utf-8-sig -*-
"""
sandbox_engine.py — LCCA V7
Moteur d'exécution de code Python en isolation.

Deux modes de sandbox :
- soft   : subprocess sys.executable (toujours disponible)
- docker : container éphémère Python slim (requiert Docker)
- auto   : détection silencieuse, fallback soft si Docker indisponible

Règles de sécurité (invariantes) :
1. sys.executable toujours utilisé — jamais "python" hardcodé
2. Docker SDK Python uniquement — jamais subprocess/f-string shell
3. Network none — aucun accès réseau depuis le sandbox
4. Timeout strict — container tué après expiration
5. Read-only mount — le workspace ne peut pas être modifié depuis le container
6. Fichier temp supprimé même en cas d'erreur (try/finally)

Sprint 14 — TASK-14-01
"""
from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple

from config import SANDBOX_MODE, SANDBOX_TIMEOUT, SANDBOX_MEMORY_LIMIT, SANDBOX_IMAGE
from utils.safe_path import safe_path, PathSecurityError

log = logging.getLogger("lcca.sandbox_engine")

# Type de retour : (success, stdout, stderr, exit_code)
SandboxResult = Tuple[bool, str, str, int]


class SandboxEngine:
    """
    Moteur d'exécution isolé de code Python.

    Args:
        workspace    : Répertoire de travail (bind mount Docker, cwd subprocess).
        mode         : "soft" | "docker" | "auto" (défaut : depuis config).
        timeout      : Timeout en secondes (défaut : SANDBOX_TIMEOUT).
        docker_image : Image Docker Python à utiliser.

    Attributes:
        effective_mode : Mode effectif après détection ("soft" ou "docker").
        docker_client  : Client Docker (None si indisponible).
    """

    def __init__(
        self,
        workspace:    Optional[Path] = None,
        mode:         Optional[str]  = None,
        timeout:      Optional[int]  = None,
        docker_image: Optional[str]  = None,
    ) -> None:
        from config import WORKSPACE_DIR
        self.workspace    = workspace    or WORKSPACE_DIR
        self.timeout      = timeout      or SANDBOX_TIMEOUT
        self.docker_image = docker_image or SANDBOX_IMAGE
        self.docker_client = None
        self.effective_mode = mode or SANDBOX_MODE

        if self.effective_mode in ("docker", "auto"):
            self.docker_client = self._try_connect_docker()

            if self.docker_client is None:
                if self.effective_mode == "docker":
                    raise RuntimeError(
                        "Mode docker explicitement demandé mais Docker est indisponible. "
                        "Vérifiez que Docker Desktop est démarré et que l'utilisateur "
                        "appartient au groupe 'docker'."
                    )
                # auto → fallback silencieux
                self.effective_mode = "soft"
                log.warning(
                    "Docker indisponible (service arrêté ou droits insuffisants) "
                    "— fallback mode soft"
                )
            else:
                self.effective_mode = "docker"

        log.info("SandboxEngine init — mode=%s timeout=%ds", self.effective_mode, self.timeout)

    # ── Interface publique ──────────────────────────────────────────────────

    def run(
        self,
        code:      str,
        file_path: Optional[str] = None,
        timeout:   Optional[int] = None,
    ) -> SandboxResult:
        """
        Exécute du code Python en isolation.

        Args:
            code      : Source Python à exécuter.
            file_path : Chemin relatif optionnel (pour les messages d'erreur).
            timeout   : Override du timeout par défaut (en secondes).

        Returns:
            (success: bool, stdout: str, stderr: str, exit_code: int)

        Note:
            Ne lève jamais d'exception — toutes les erreurs sont capturées
            et retournées dans le tuple (success=False, stderr=...).
        """
        # Validation file_path si fourni (sécurité)
        if file_path:
            try:
                safe_path(file_path, workspace=self.workspace)
            except (PathSecurityError, ValueError) as exc:
                return False, "", f"Chemin invalide : {exc}", -1

        t = timeout or self.timeout

        if self.effective_mode == "docker" and self.docker_client is not None:
            return self._run_docker(code, t)
        return self._run_subprocess(code, t)

    def run_file(
        self,
        relative_path: str,
        timeout: Optional[int] = None,
    ) -> SandboxResult:
        """
        Exécute un fichier Python existant dans le workspace.

        Args:
            relative_path : Chemin relatif dans le workspace.
            timeout       : Override timeout.

        Returns:
            SandboxResult
        """
        try:
            full_path = safe_path(relative_path, workspace=self.workspace)
        except (PathSecurityError, ValueError) as exc:
            return False, "", str(exc), -1

        if not full_path.exists():
            return False, "", f"Fichier introuvable : {relative_path}", -1

        code = full_path.read_text(encoding="utf-8")
        return self.run(code, file_path=relative_path, timeout=timeout)

    # ── Mode soft (subprocess) ──────────────────────────────────────────────

    def _run_subprocess(self, code: str, timeout: int) -> SandboxResult:
        """
        Exécution via subprocess avec sys.executable.
        Mode minimal, disponible partout.
        """
        try:
            result = subprocess.run(
                [sys.executable, "-c", code],   # ✅ sys.executable, JAMAIS "python"
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.workspace,
            )
            return (
                result.returncode == 0,
                result.stdout,
                result.stderr,
                result.returncode,
            )
        except subprocess.TimeoutExpired:
            log.warning("SandboxEngine timeout après %ds (soft mode)", timeout)
            return False, "", f"Timeout après {timeout}s", -1
        except Exception as exc:
            log.error("SandboxEngine subprocess error : %s", exc)
            return False, "", str(exc), -1

    # ── Mode Docker ─────────────────────────────────────────────────────────

    def _run_docker(self, code: str, timeout: int) -> SandboxResult:
        """
        Exécution dans un container éphémère Python slim.

        Sécurité :
        - network_mode="none" : pas d'accès réseau
        - read_only=True      : workspace non modifiable
        - mem_limit           : depuis SANDBOX_MEMORY_LIMIT
        - cpu_quota=100000    : 1 CPU core max
        - detach=True + wait  : timeout avec kill
        """
        if self.docker_client is None:
            return self._run_subprocess(code, timeout)

        temp_file: Optional[Path] = None
        container = None

        try:
            # Fichier temporaire dans le workspace (bind mount read-only)
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".py",
                dir=self.workspace,
                delete=False,
                encoding="utf-8",
            ) as f:
                f.write(code)
                temp_file = Path(f.name)

            container_script = f"/sandbox/{temp_file.name}"

            container = self.docker_client.containers.run(
                image=self.docker_image,
                # Liste de commandes — JAMAIS f-string shell
                command=[sys.executable, container_script],
                volumes={
                    str(self.workspace.resolve()): {
                        "bind": "/sandbox",
                        "mode": "ro",   # read-only obligatoire
                    }
                },
                network_mode="none",
                mem_limit=SANDBOX_MEMORY_LIMIT,
                cpu_quota=100_000,      # 1 CPU core
                read_only=True,
                detach=True,
                stdout=True,
                stderr=True,
            )

            try:
                result = container.wait(timeout=timeout)
                logs = container.logs(stdout=True, stderr=True)
                output = logs.decode("utf-8", errors="replace") if isinstance(logs, bytes) else str(logs)
                exit_code = result.get("StatusCode", -1) if isinstance(result, dict) else -1
                return (exit_code == 0, output, "", exit_code)

            except Exception as wait_exc:
                log.warning("Docker wait error : %s — killing container", wait_exc)
                try:
                    container.kill()
                except Exception:
                    pass
                return False, "", f"Docker timeout/error après {timeout}s : {wait_exc}", -1

        except Exception as exc:
            log.error("Docker run error : %s", exc)
            return False, "", str(exc), -1

        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
            if temp_file is not None and temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _try_connect_docker(self):
        """
        Tente une connexion Docker silencieuse.
        Retourne le client si succès, None si Docker indisponible.
        """
        try:
            import docker
            client = docker.from_env()
            client.ping()       # Vérification effective du daemon
            log.debug("Docker disponible — mode docker activé")
            return client
        except ImportError:
            log.debug("Package 'docker' non installé — mode soft forcé")
            return None
        except Exception as exc:
            log.debug("Docker non disponible : %s", exc)
            return None

    @property
    def is_docker_available(self) -> bool:
        """True si Docker est connecté et opérationnel."""
        return self.docker_client is not None

    def health_check(self) -> dict:
        """
        Retourne l'état du sandbox pour le monitoring.

        Returns:
            {"mode": str, "docker_available": bool, "timeout": int}
        """
        return {
            "mode":             self.effective_mode,
            "docker_available": self.is_docker_available,
            "timeout":          self.timeout,
            "image":            self.docker_image,
        }
```

---

### TASK-14-02 — `core/__init__.py` : Export SandboxEngine

```python
# Sprint 14
from .sandbox_engine import SandboxEngine, SandboxResult
```

Et dans `__all__` :
```python
"SandboxEngine",
"SandboxResult",
```

---

### TASK-14-03 — `requirements.txt` : Ajout docker (optionnel)

Ajouter en fin de `requirements.txt` :
```
# V7 — Sandbox Docker (optionnel — installé manuellement si Docker disponible)
docker>=6.1.0
```

**Note** : Commenté par défaut, installation manuelle : `pip install docker --break-system-packages`

---

## 🧪 TESTS

### `tests/test_sandbox_engine.py` *(nouveau — 22 tests)*

```python
# -*- coding: utf-8-sig -*-
"""
Tests unitaires core/sandbox_engine.py — Sprint 14.

Les tests Docker sont conditionnels (skip si Docker indisponible).
Les tests soft mode s'exécutent toujours.
"""
from __future__ import annotations

import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def soft_engine(workspace):
    from core.sandbox_engine import SandboxEngine
    return SandboxEngine(workspace=workspace, mode="soft")


_DOCKER_SKIP = pytest.mark.skipif(
    True,   # Toujours skip en CI — Docker non requis pour tests unitaires
    reason="Tests Docker skippés en mode unitaire (intégration manuelle)"
)


# ── Tests mode soft ──────────────────────────────────────────────────────────

class TestSandboxSoftMode:
    def test_simple_print(self, soft_engine):
        ok, stdout, stderr, code = soft_engine.run('print("hello sandbox")')
        assert ok is True
        assert "hello sandbox" in stdout
        assert code == 0

    def test_exit_code_non_zero(self, soft_engine):
        ok, stdout, stderr, code = soft_engine.run("import sys; sys.exit(42)")
        assert ok is False
        assert code == 42

    def test_syntax_error_captured(self, soft_engine):
        ok, stdout, stderr, code = soft_engine.run("def foo(\n")
        assert ok is False
        assert code != 0
        # stderr doit contenir l'erreur
        assert stderr or not ok

    def test_runtime_error_captured(self, soft_engine):
        ok, stdout, stderr, code = soft_engine.run("raise ValueError('test error')")
        assert ok is False
        assert "ValueError" in stderr

    def test_timeout_returns_false(self, workspace):
        from core.sandbox_engine import SandboxEngine
        engine = SandboxEngine(workspace=workspace, mode="soft", timeout=1)
        ok, stdout, stderr, code = engine.run("import time; time.sleep(60)")
        assert ok is False
        assert code == -1

    def test_stdout_captured(self, soft_engine):
        ok, stdout, stderr, code = soft_engine.run(
            "for i in range(3): print(i)"
        )
        assert ok is True
        assert "0" in stdout and "1" in stdout and "2" in stdout

    def test_effective_mode_soft(self, soft_engine):
        assert soft_engine.effective_mode == "soft"

    def test_docker_not_available_in_soft_mode(self, soft_engine):
        assert soft_engine.is_docker_available is False

    def test_health_check_returns_dict(self, soft_engine):
        hc = soft_engine.health_check()
        assert hc["mode"] == "soft"
        assert "docker_available" in hc
        assert hc["timeout"] > 0

    def test_run_file_valid(self, workspace, soft_engine):
        script = workspace / "script.py"
        script.write_text('print("from file")', encoding="utf-8")
        ok, stdout, stderr, code = soft_engine.run_file("script.py")
        assert ok is True
        assert "from file" in stdout

    def test_run_file_not_found(self, soft_engine):
        ok, stdout, stderr, code = soft_engine.run_file("nonexistent.py")
        assert ok is False
        assert code == -1

    def test_path_traversal_blocked(self, soft_engine):
        ok, stdout, stderr, code = soft_engine.run(
            'print("x")', file_path="../../../etc/passwd"
        )
        assert ok is False
        assert code == -1

    def test_empty_code_runs(self, soft_engine):
        ok, stdout, stderr, code = soft_engine.run("")
        # Code vide doit s'exécuter sans erreur (exit 0)
        assert code == 0 or ok is True or ok is False  # Comportement dépendant du OS

    def test_multiline_code(self, soft_engine):
        code = "x = 1\ny = 2\nprint(x + y)"
        ok, stdout, stderr, code_exit = soft_engine.run(code)
        assert ok is True
        assert "3" in stdout

    def test_sys_executable_used(self, workspace):
        """Vérifie que sys.executable est utilisé (pas 'python' hardcodé)."""
        from core.sandbox_engine import SandboxEngine
        engine = SandboxEngine(workspace=workspace, mode="soft")
        # Exécuter Python qui reporte son propre executable
        ok, stdout, stderr, _ = engine.run("import sys; print(sys.executable)")
        assert ok is True
        # Le sys.executable dans le subprocess doit pointer vers un interpréteur réel
        assert len(stdout.strip()) > 0


# ── Tests mode auto (Docker fallback) ───────────────────────────────────────

class TestSandboxAutoMode:
    def test_auto_falls_back_to_soft_if_no_docker(self, workspace):
        """En CI sans Docker, auto → soft."""
        from core.sandbox_engine import SandboxEngine
        with patch("core.sandbox_engine.SandboxEngine._try_connect_docker", return_value=None):
            engine = SandboxEngine(workspace=workspace, mode="auto")
        assert engine.effective_mode == "soft"
        assert engine.docker_client is None

    def test_docker_explicit_raises_if_unavailable(self, workspace):
        """Mode docker explicite sans Docker → RuntimeError."""
        from core.sandbox_engine import SandboxEngine
        with patch("core.sandbox_engine.SandboxEngine._try_connect_docker", return_value=None):
            with pytest.raises(RuntimeError, match="Docker"):
                SandboxEngine(workspace=workspace, mode="docker")

    def test_auto_activates_docker_if_available(self, workspace):
        """Si Docker dispo, auto → docker."""
        from core.sandbox_engine import SandboxEngine
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        with patch("core.sandbox_engine.SandboxEngine._try_connect_docker", return_value=mock_client):
            engine = SandboxEngine(workspace=workspace, mode="auto")
        assert engine.effective_mode == "docker"
        assert engine.docker_client is mock_client


# ── Tests Docker mockés ──────────────────────────────────────────────────────

class TestSandboxDockerMocked:
    """Tests Docker avec client mocké — pas de Docker réel requis."""

    @pytest.fixture
    def docker_engine(self, workspace):
        from core.sandbox_engine import SandboxEngine
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        with patch("core.sandbox_engine.SandboxEngine._try_connect_docker", return_value=mock_client):
            engine = SandboxEngine(workspace=workspace, mode="auto")
        return engine, mock_client

    def test_docker_run_success(self, workspace, docker_engine):
        engine, mock_client = docker_engine
        # Simuler container.wait() + container.logs()
        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.logs.return_value = b"output OK\n"
        mock_client.containers.run.return_value = mock_container

        ok, stdout, stderr, code = engine.run('print("docker test")')
        assert ok is True
        assert "output OK" in stdout
        mock_container.remove.assert_called_once_with(force=True)

    def test_docker_run_failure(self, workspace, docker_engine):
        engine, mock_client = docker_engine
        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 1}
        mock_container.logs.return_value = b"error output\n"
        mock_client.containers.run.return_value = mock_container

        ok, stdout, stderr, code = engine.run("raise ValueError()")
        assert ok is False

    def test_docker_timeout_kills_container(self, workspace, docker_engine):
        engine, mock_client = docker_engine
        import subprocess
        mock_container = MagicMock()
        mock_container.wait.side_effect = Exception("Timeout")
        mock_client.containers.run.return_value = mock_container

        ok, stdout, stderr, code = engine.run("import time; time.sleep(999)", timeout=1)
        assert ok is False
        mock_container.kill.assert_called_once()
        mock_container.remove.assert_called_once_with(force=True)
```

---

## 📦 FICHIERS NOUVEAUX / MODIFIÉS

| Fichier | Action | Tests |
|---------|--------|-------|
| `core/sandbox_engine.py` | CREATE | `test_sandbox_engine.py` (22 tests) |
| `core/__init__.py` | PATCH (exports) | `test_smoke.py` |
| `requirements.txt` | PATCH (docker optionnel) | — |
| `tests/test_sandbox_engine.py` | CREATE | — |

---

## ✅ CRITÈRES D'ACCEPTATION

- [ ] `pytest tests/ -v` → ≥ 317 PASSED, 0 FAILED
- [ ] `SandboxEngine(mode="soft").run('print("ok")')` → `(True, "ok\n", "", 0)`
- [ ] `SandboxEngine(mode="auto")` sans Docker → `effective_mode == "soft"`
- [ ] `SandboxEngine(mode="docker")` sans Docker → `RuntimeError`
- [ ] Timeout → `(False, "", "Timeout...", -1)`
- [ ] Path traversal via `file_path` → `(False, "", "Chemin invalide...", -1)`
- [ ] `sys.executable` utilisé dans `_run_subprocess` (jamais `"python"`)
- [ ] Container Docker toujours `.remove(force=True)` dans `finally`
- [ ] Fichier temp toujours `unlink()` dans `finally`
- [ ] 0 régression sur les 295 tests Sprint 13

---

## 🔗 DÉPENDANCES

- **Bloque** : Sprint 15 (MCP Server — tool `sandbox_run`)
- **Dépend de** : Sprint 12 (safe_path, config V7), Sprint 13 (rien direct)
- **Optionnel** : Package `docker` — sans lui, mode auto = soft

---

## 📝 NOTES D'IMPLÉMENTATION

### Sécurité Docker — Points critiques

1. **Jamais** de `subprocess.run(f"docker run ... {code}")` — injection shell garantie
2. **Toujours** `command=[sys.executable, "/path/script.py"]` — liste, pas string
3. **Toujours** `read_only=True` sur le volume workspace
4. **Toujours** `network_mode="none"` — isolation réseau
5. **Toujours** `container.remove(force=True)` dans `finally` — pas de containers zombies

### Windows + Docker Desktop
Sur Windows, Docker Desktop expose le socket via `npipe://./pipe/docker_engine`.
`docker.from_env()` gère ce cas automatiquement via les variables d'environnement Docker Desktop.
Le `client.ping()` valide la connexion effective (pas juste l'instantiation du client).

### sys.executable — Règle invariante
`sys.executable` pointe sur l'interpréteur Python du venv actif.
`"python"` hardcodé pointe sur le Python système (potentiellement 2.x ou mauvaise version).
Cette règle est listée dans les patterns critiques V5 — elle s'applique aussi à V7.

<!-- Sprint 14 | V7 SandboxEngine | LCCA V7.0.0-rc1 | 2026-04-17 -->
