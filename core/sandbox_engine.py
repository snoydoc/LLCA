"""
SandboxEngine V7 — Exécution isolée de code Python.

Deux modes :
  - soft   : subprocess isolé (sys.executable, cwd=workspace, timeout)
  - docker : container éphémère python:3.11-slim, réseau none, ro, 512m RAM
  - auto   : docker si disponible, sinon soft

Règles LCCA :
  - sys.executable TOUJOURS (jamais "python" hardcodé)
  - Pas d'injection shell (list argv, pas f-string)
  - Encodage utf-8 partout
  - Aucune dépendance non-stdlib sauf `docker` (optionnel)
"""
from __future__ import annotations

import ast
import copy
import os
import sys
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

# docker SDK est optionnel (Docker non requis en mode soft)
try:
    import docker as _docker_sdk  # type: ignore
    _DOCKER_AVAILABLE = True
except ImportError:
    _docker_sdk = None  # type: ignore
    _DOCKER_AVAILABLE = False


# ── FL-03 : imports interdits en mode soft-hardened ─────────────────────────
# stdlib uniquement (ast, json, pathlib, re...) reste autorise.
# Modules ci-dessous ouvrent des surfaces d'attaque trop larges.
_FORBIDDEN_SOFT: frozenset = frozenset({
    "subprocess", "socket", "pty", "ctypes",
    "importlib", "zipimport", "multiprocessing", "winreg",
    "os",          # open() reste autorise, mais os.system/popen non
    "shutil",      # copie de fichiers hors workspace
    "ftplib", "smtplib", "http", "urllib",  # reseau
})


# ── Type alias ────────────────────────────────────────────────────────────────
RunResult = Tuple[bool, str, str, int]
# (success, stdout, stderr, exit_code)


class SandboxEngine:
    r"""
    Moteur d'exécution sandboxé pour code Python généré par LCCA.

    Usage minimal::

        engine = SandboxEngine(workspace=Path(r"D:\LLMCodeAgent\workspace"))
        ok, out, err, code = engine.run("print('hello')")

    Modes :
        ``soft``   – subprocess (toujours disponible)
        ``docker`` – container éphémère (Docker SDK requis)
        ``auto``   – docker si disponible, sinon soft
    """

    def __init__(
        self,
        workspace: Optional[Path] = None,
        mode: str = "auto",
    ) -> None:
        from config import WORKSPACE_DIR, SANDBOX_MODE  # import tardif pour testabilité

        self.workspace: Path = workspace or WORKSPACE_DIR
        self.mode: str = mode if mode != "auto_from_config" else SANDBOX_MODE

        # Tentative connexion Docker
        self.docker_client = None
        if self.mode in ("docker", "auto"):
            if _DOCKER_AVAILABLE:
                try:
                    self.docker_client = _docker_sdk.from_env()
                except Exception:
                    if self.mode == "docker":
                        raise RuntimeError(
                            "Docker requis (mode='docker') mais non disponible."
                        )
                    # mode auto → repli soft
            elif self.mode == "docker":
                raise RuntimeError(
                    "Le package 'docker' n'est pas installé. "
                    "Faites : pip install docker"
                )

    # ── API publique ──────────────────────────────────────────────────────────

    @property
    def effective_mode(self) -> str:
        """Retourne le mode effectif (resoud 'auto' apres la tentative Docker)."""
        if self.mode == "soft":
            return "soft_hardened"   # FL-03 : soft → soft_hardened
        if self.mode == "docker":
            return "docker"
        # auto
        return "docker" if self.docker_client is not None else "soft_hardened"

    def run(
        self,
        code: str,
        file_path: Optional[str] = None,
        timeout: int = 30,
    ) -> RunResult:
        """
        Exécute ``code`` en isolation.

        Args:
            code:      Source Python à exécuter.
            file_path: Nom logique du fichier (utilisé uniquement en mode docker
                       pour le volume bind-mount).
            timeout:   Limite d'exécution en secondes (défaut : 30).

        Returns:
            ``(success, stdout, stderr, exit_code)``
        """
        if timeout <= 0:
            raise ValueError(f"timeout doit être > 0, reçu {timeout}")

        if self.effective_mode in ("soft", "soft_hardened"):
            return self._run_subprocess_hardened(code, timeout)
        return self._run_docker(code, file_path, timeout)

    def run_file(
        self,
        file_path: Path,
        timeout: int = 30,
    ) -> RunResult:
        """
        Exécute un fichier .py existant dans le workspace.

        Args:
            file_path: Chemin absolu vers le fichier Python.
            timeout:   Limite d'exécution en secondes.
        """
        if not file_path.exists():
            return False, "", f"Fichier introuvable : {file_path}", -1

        code = file_path.read_text(encoding="utf-8-sig")  # utf-8-sig : BOM Windows stripé automatiquement
        return self.run(code, file_path=file_path.name, timeout=timeout)

    # ── Modes d'exécution ─────────────────────────────────────────────────────

    # FL-03 : helpers pré-scan AST ───────────────────────────────────────────

    def _prescan_imports(self, code: str) -> Optional[str]:
        """
        FL-03 : Analyse AST du code et retourne le premier import interdit
        trouve dans `_FORBIDDEN_SOFT`, ou None si tout est OK.

        Silencieux sur SyntaxError (le sandbox lui-meme la detectera).
        Utilise AST — jamais de regex.
        """
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return None   # SyntaxError geree par le sandbox, pas par le prescan

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in _FORBIDDEN_SOFT:
                        return root   # FL-03 : retourne le root, pas le nom complet
            elif isinstance(node, ast.ImportFrom):
                mod = (node.module or "").split(".")[0]
                if mod in _FORBIDDEN_SOFT:
                    return mod   # FL-03 : retourne le root, pas node.module complet
        return None

    def _run_subprocess_hardened(self, code: str, timeout: int) -> RunResult:
        """
        FL-03 : Mode soft durci.

        1. Pre-scan AST des imports interdits (exit_code=-2 si bloque).
        2. PYTHONPATH='' — stdlib disponible, packages venv parent bloques.
        3. cwd = repertoire temporaire isole (pas workspace direct).

        Invariants :
        - exit_code=-2 = import bloque (distinct de -1 = timeout/exception)
        - PYTHONPATH='' ne bloque pas stdlib (json, pathlib, ast...)
        - self.workspace non modifie
        """
        forbidden = self._prescan_imports(code)
        if forbidden:
            return (
                False, "",
                f"Import interdit bloque par sandbox : {forbidden}",
                -2,
            )

        env = copy.copy(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = ""   # coupe les packages venv, stdlib reste intact

        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                result = subprocess.run(
                    [sys.executable, "-c", code],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=tmpdir,         # FL-03 : tmpdir isole, pas workspace
                    env=env,
                )
                return (
                    result.returncode == 0,
                    result.stdout,
                    result.stderr,
                    result.returncode,
                )
            except subprocess.TimeoutExpired:
                return False, "", f"Timeout apres {timeout}s", -1
            except Exception as exc:
                return False, "", str(exc), -1

    def _run_subprocess_legacy(self, code: str, timeout: int) -> RunResult:
        """
        FL-03 : Ancienne implementation soft conservee pour retrocompat.
        N'est plus appelee par run() — disponible pour les tests de regression.
        """
        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.workspace),
            )
            return (
                result.returncode == 0,
                result.stdout,
                result.stderr,
                result.returncode,
            )
        except subprocess.TimeoutExpired:
            return False, "", f"Timeout apres {timeout}s", -1
        except Exception as exc:
            return False, "", str(exc), -1

    def _run_subprocess(self, code: str, timeout: int) -> RunResult:
        """Alias retrocompat -> deleguea _run_subprocess_hardened (FL-03)."""
        return self._run_subprocess_hardened(code, timeout)

    def _run_docker(
        self,
        code: str,
        file_path: Optional[str],
        timeout: int,
    ) -> RunResult:
        r"""
        Mode Docker : container éphémère ``python:3.11-slim``.

        Caractéristiques sécurité :
        - ``network_mode="none"``  → pas d'accès réseau
        - ``read_only=True``       → filesystem container en lecture seule
        - ``mem_limit="512m"``     → limite RAM
        - ``cpu_quota=100000``     → 1 CPU core
        - Volume workspace monté en ``ro``

        Le code est écrit dans un fichier temporaire dans le workspace
        (accessible via bind-mount) puis supprimé après l'exécution.
        """
        if self.docker_client is None:
            # Repli soft si docker_client perdu après __init__
            return self._run_subprocess(code, timeout)

        # Fichier temporaire visible depuis le container via le bind-mount
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            dir=str(self.workspace),
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp.write(code)
            temp_path = Path(tmp.name)
            container_file = f"/sandbox/{temp_path.name}"

        try:
            container = self.docker_client.containers.run(
                image="python:3.11-slim",
                command=[sys.executable, container_file],  # liste argv, pas f-string
                volumes={
                    str(self.workspace): {"bind": "/sandbox", "mode": "ro"},
                },
                network_mode="none",
                mem_limit="512m",
                cpu_quota=100_000,      # 1 CPU core (100 000 / 100 000)
                read_only=True,
                detach=True,
                stdout=True,
                stderr=True,
            )

            try:
                result = container.wait(timeout=timeout)
                raw_logs = container.logs(stdout=True, stderr=True)
                logs = raw_logs.decode("utf-8", errors="replace")
                exit_code: int = result.get("StatusCode", -1)
                return (exit_code == 0, logs, "", exit_code)
            except Exception as exc:  # noqa: BLE001
                try:
                    container.kill()
                except Exception:
                    pass
                return False, "", str(exc), -1
            finally:
                try:
                    container.remove(force=True)
                except Exception:
                    pass

        finally:
            temp_path.unlink(missing_ok=True)
