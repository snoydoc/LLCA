# Sprint FL-03 — SandboxEngine : durcissement du mode soft
<!-- AI-READY | LCCA V11 | Sprint FL-03 | Priorité P0 | Effort 0.5j | Statut : 🔲 À FAIRE -->

## Objectif

Durcir le mode `soft` de `SandboxEngine` sans Docker ni dépendances externes.
Actuellement, le code LLM s'exécute en mode soft avec `cwd=D:\LLMCodeAgent\workspace`
et `sys.executable` du venv parent — accès complet au filesystem LCCA.

**Un seul fichier touché. Zéro dépendances ajoutées (ast, copy, tempfile = stdlib).**

## Diagnostic précis (lu dans `core/sandbox_engine.py`)

```python
# Mode soft actuel — AVANT FL-03
subprocess.run(
    [sys.executable, "-c", code],
    capture_output=True, text=True,
    timeout=timeout,
    cwd=str(self.workspace),      # ← D:\LLMCodeAgent\workspace accessible
)
# Pas de restriction PYTHONPATH → tous les packages du venv accessibles
# Pas de pré-scan imports → subprocess, socket, ctypes autorisés
```

Mode `auto` → Docker si disponible, sinon soft. Sur la machine cible (NVIDIA M2002M,
Docker non garanti), le mode soft est le chemin d'exécution par défaut.

## Fichier cible

| # | Fichier | Opération | Lignes estimées |
|---|---------|-----------|-----------------|
| 1 | `core/sandbox_engine.py` | PATCH — 3 ajouts internes | +75 lignes |
| 2 | `tests/test_fl_03.py` | CREATE | ~90 lignes |

## Prérequis

- `core/sandbox_engine.py` — `SandboxEngine`, `_run_subprocess`, `_run_docker` existants ✅
- `subprocess`, `ast`, `copy`, `tempfile` — stdlib Python ✅
- Tests existants `tests/test_sandbox_engine.py` — ne pas casser ✅

## Spécification

### 1. Constante module-level (ajouter après les imports existants)

```python
# FL-03 : imports interdits en mode soft-hardened
# NB : socket interdit car code testé est du code LLM autonome, pas du code LCCA
_FORBIDDEN_SOFT: frozenset[str] = frozenset({
    "subprocess", "socket", "pty", "ctypes",
    "importlib", "zipimport", "multiprocessing", "winreg",
})
```

### 2. Nouvelle méthode `_prescan_imports()` (ajouter dans la classe)

```python
def _prescan_imports(self, code: str) -> Optional[str]:
    """
    FL-03 : Analyse AST du code pour détecter les imports interdits.

    Retourne le nom du premier module interdit trouvé, ou None si le code
    est autorisé. Silencieux sur SyntaxError — le sandbox gère l'exécution.

    Args:
        code: Code Python à analyser (string brute)

    Returns:
        str : premier import interdit (ex: "subprocess"), ou None si OK.
    """
    import ast as _ast
    try:
        tree = _ast.parse(code)
    except SyntaxError:
        return None   # SyntaxError gérée par le subprocess lui-même

    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _FORBIDDEN_SOFT:
                    return alias.name

        elif isinstance(node, _ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if mod in _FORBIDDEN_SOFT:
                return node.module or mod

    return None
```

### 3. Nouvelle méthode `_run_subprocess_hardened()` (ajouter dans la classe)

```python
def _run_subprocess_hardened(self, code: str, timeout: int) -> RunResult:
    """
    FL-03 : Mode soft durci.

    Trois restrictions cumulées sans Docker ni dépendances tierces :
    1. Pré-scan AST des imports (bloquant si import interdit, exit_code=-2)
    2. PYTHONPATH='' → stdlib uniquement, packages venv parent inaccessibles
    3. cwd = répertoire temporaire isolé (pas D:\LLMCodeAgent\workspace)

    Exit codes spéciaux :
        -1 : timeout ou exception Python
        -2 : import interdit bloqué par _prescan_imports (avant exécution)

    Args:
        code    : Code Python à exécuter
        timeout : Timeout en secondes

    Returns:
        RunResult : (success: bool, stdout: str, stderr: str, exit_code: int)
    """
    import copy as _copy
    import tempfile as _tempfile

    # Étape 1 — pré-scan sécurité
    forbidden = self._prescan_imports(code)
    if forbidden:
        log.warning("[sandbox] import bloqué par soft-hardened: %s", forbidden)
        return (
            False,
            "",
            f"Import interdit bloqué par sandbox : {forbidden}",
            -2,
        )

    # Étape 2 — environnement restreint
    import os as _os
    env = _copy.copy(_os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = ""          # stdlib toujours accessible, packages venv non
    env["PYTHONNOUSERSITE"] = "1"   # ignorer site-packages utilisateur

    # Étape 3 — exécution dans répertoire temporaire isolé
    with _tempfile.TemporaryDirectory(prefix="lcca_sandbox_") as tmpdir:
        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmpdir,         # ← répertoire vide, pas workspace
                env=env,
            )
            return (
                result.returncode == 0,
                result.stdout,
                result.stderr,
                result.returncode,
            )

        except subprocess.TimeoutExpired:
            log.warning("[sandbox] soft-hardened timeout (%ds)", timeout)
            return (False, "", f"Timeout après {timeout}s", -1)

        except Exception as exc:
            log.error("[sandbox] soft-hardened exception: %s", exc)
            return (False, "", str(exc), -1)
```

### 4. Renommage + câblage dans `run()` (PATCH — pas de réécriture)

**Renommer** l'existant `_run_subprocess` → `_run_subprocess_legacy` :

```python
# AVANT
def _run_subprocess(self, code: str, timeout: int) -> RunResult:
    ...subprocess.run([sys.executable, "-c", code], cwd=str(self.workspace))...

# APRÈS — FL-03 : renommé pour rétrocompat tests
def _run_subprocess_legacy(self, code: str, timeout: int) -> RunResult:
    """
    Ancien mode soft sans restriction (AVANT FL-03).
    Conservé pour les tests de régression. Ne jamais supprimer.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(self.workspace),
        )
        return (result.returncode == 0, result.stdout, result.stderr, result.returncode)
    except subprocess.TimeoutExpired:
        return (False, "", f"Timeout après {timeout}s", -1)
    except Exception as exc:
        return (False, "", str(exc), -1)
```

**Dans `run()`**, remplacer l'appel `_run_subprocess` par `_run_subprocess_hardened` :

```python
# AVANT
if mode == "soft":
    return self._run_subprocess(code, timeout)

# APRÈS — FL-03
if mode in ("soft", "soft_hardened"):
    return self._run_subprocess_hardened(code, timeout)
elif mode == "soft_legacy":
    return self._run_subprocess_legacy(code, timeout)
```

**Mettre à jour `effective_mode`** pour refléter le nouveau nom :

```python
@property
def effective_mode(self) -> str:
    """Retourne le mode effectivement utilisé."""
    if self.mode == "auto":
        return "docker" if self._docker_available else "soft_hardened"
    if self.mode == "soft":
        return "soft_hardened"     # FL-03 : "soft" → "soft_hardened"
    return self.mode               # "docker", "soft_legacy" inchangés
```

> ⚠️ `_run_docker` n'est **pas touché**. L'interface `run()` publique garde la même
> signature. Le mode `"docker"` n'est pas affecté.

## Tests — `tests/test_fl_03.py`

```python
# tests/test_fl_03.py
"""FL-03 — Tests SandboxEngine mode soft-hardened."""
import pytest
import sys
from unittest.mock import MagicMock, patch
from pathlib import Path


# ── TestPrescanImports ────────────────────────────────────────────────────────

class TestPrescanImports:
    def _engine(self):
        from core.sandbox_engine import SandboxEngine
        return SandboxEngine(workspace=Path("/tmp"), mode="soft")

    def test_subprocess_blocked(self):
        e = self._engine()
        assert e._prescan_imports("import subprocess\nsubprocess.run(['ls'])") == "subprocess"

    def test_socket_blocked(self):
        e = self._engine()
        assert e._prescan_imports("import socket\nsocket.connect(('x',80))") == "socket"

    def test_from_subprocess_blocked(self):
        e = self._engine()
        assert e._prescan_imports("from subprocess import run") == "subprocess"

    def test_json_allowed(self):
        e = self._engine()
        assert e._prescan_imports("import json\nprint(json.dumps({}))") is None

    def test_pathlib_allowed(self):
        e = self._engine()
        assert e._prescan_imports("from pathlib import Path\nPath('/tmp').exists()") is None

    def test_syntax_error_returns_none(self):
        """SyntaxError → None (gérée par le sandbox)."""
        e = self._engine()
        assert e._prescan_imports("def broken(: pass") is None

    def test_ctypes_blocked(self):
        e = self._engine()
        assert e._prescan_imports("import ctypes") == "ctypes"

    def test_empty_code_returns_none(self):
        e = self._engine()
        assert e._prescan_imports("") is None


# ── TestSoftHardenedExecution ─────────────────────────────────────────────────

class TestSoftHardenedExecution:
    def _engine(self):
        from core.sandbox_engine import SandboxEngine
        return SandboxEngine(workspace=Path("D:/LLMCodeAgent"), mode="soft")

    def test_clean_code_succeeds(self):
        """Code sans import interdit s'exécute normalement."""
        engine = self._engine()
        ok, stdout, stderr, code = engine._run_subprocess_hardened(
            "import json\nprint(json.dumps({'a': 1}))", timeout=10
        )
        assert ok is True
        assert '"a": 1' in stdout

    def test_forbidden_import_exit_minus_2(self):
        """Import interdit → exit_code=-2 AVANT toute exécution."""
        engine = self._engine()
        ok, stdout, stderr, code = engine._run_subprocess_hardened(
            "import subprocess\nsubprocess.run(['ls'])", timeout=10
        )
        assert ok is False
        assert code == -2
        assert "subprocess" in stderr

    def test_cwd_is_not_workspace(self):
        """cwd du process est un tmpdir isolé, pas D:\LLMCodeAgent\workspace."""
        engine = self._engine()
        ok, stdout, stderr, code = engine._run_subprocess_hardened(
            "import os; print(os.getcwd())", timeout=10
        )
        assert ok is True
        # Le cwd ne doit pas contenir "LLMCodeAgent"
        assert "LLMCodeAgent" not in stdout

    def test_timeout_respected(self):
        """Boucle infinie → exit_code=-1."""
        engine = self._engine()
        ok, stdout, stderr, code = engine._run_subprocess_hardened(
            "while True: pass", timeout=2
        )
        assert ok is False
        assert code == -1

    def test_syntax_error_caught_by_subprocess(self):
        """SyntaxError dans le code → subprocess retourne un exit_code non nul."""
        engine = self._engine()
        ok, stdout, stderr, code = engine._run_subprocess_hardened(
            "def broken(: pass", timeout=5
        )
        assert ok is False
        # exit_code 1 (SyntaxError Python), pas -2 (import interdit)
        assert code != -2


# ── TestLegacyModePreserved ───────────────────────────────────────────────────

class TestLegacyModePreserved:
    def test_legacy_method_exists(self):
        """_run_subprocess_legacy doit exister (jamais supprimer)."""
        from core.sandbox_engine import SandboxEngine
        assert hasattr(SandboxEngine, "_run_subprocess_legacy")

    def test_soft_legacy_mode_uses_legacy(self):
        """mode='soft_legacy' → _run_subprocess_legacy appelé."""
        from core.sandbox_engine import SandboxEngine
        e = SandboxEngine(workspace=Path("/tmp"), mode="soft_legacy")
        with patch.object(e, "_run_subprocess_legacy", return_value=(True, "ok", "", 0)) as mock:
            e.run("print(1)", timeout=5)
            mock.assert_called_once()


# ── TestEffectiveMode ─────────────────────────────────────────────────────────

class TestEffectiveMode:
    def test_soft_becomes_soft_hardened(self):
        from core.sandbox_engine import SandboxEngine
        e = SandboxEngine(workspace=Path("/tmp"), mode="soft")
        assert e.effective_mode == "soft_hardened"

    def test_auto_no_docker_becomes_soft_hardened(self):
        from core.sandbox_engine import SandboxEngine
        e = SandboxEngine(workspace=Path("/tmp"), mode="auto")
        with patch.object(e, "_docker_available", False):
            assert e.effective_mode == "soft_hardened"

    def test_soft_legacy_unchanged(self):
        from core.sandbox_engine import SandboxEngine
        e = SandboxEngine(workspace=Path("/tmp"), mode="soft_legacy")
        assert e.effective_mode == "soft_legacy"
```

## Critères d'acceptation

- [ ] `pytest tests/test_fl_03.py` : 14 passed
- [ ] `SandboxEngine(mode="soft").run("import subprocess")` → `exit_code=-2`
- [ ] `SandboxEngine(mode="soft").run("import json\nprint(1)")` → `success=True`
- [ ] `SandboxEngine(mode="soft").run("while True: pass", timeout=2)` → `exit_code=-1`
- [ ] `pytest tests/test_sandbox_engine.py` : toujours verts (tests existants)
- [ ] `_run_subprocess_legacy` présent dans le fichier (ne jamais supprimer)

## Protocole d'exécution

```
1. filesystem:read_text_file core/sandbox_engine.py       ← lire l'intégralité
2. filesystem:edit_file core/sandbox_engine.py
   → ajouter _FORBIDDEN_SOFT après les imports existants
   → ajouter _prescan_imports() dans la classe
   → ajouter _run_subprocess_hardened() dans la classe
   → renommer _run_subprocess → _run_subprocess_legacy
   → patcher run() : "soft" / "soft_hardened" → _run_subprocess_hardened
   → mettre à jour effective_mode property
3. filesystem:write_file tests/test_fl_03.py
4. bash: python -c "from core.sandbox_engine import SandboxEngine; print('import OK')"
5. bash: python -m pytest tests/test_fl_03.py -v
6. bash: python -m pytest tests/test_sandbox_engine.py -v
7. bash: python -m pytest tests/ -x -q
```

## ⚠️ Points d'attention

- `PYTHONPATH=""` rend inaccessibles les packages tiers **depuis le code LLM** —
  c'est voulu. Les imports `json`, `ast`, `pathlib`, `os` (stdlib) restent accessibles
  car `PYTHONPATH` n'affecte pas `sys.path` de la stdlib elle-même.
- Le code LCCA lui-même n'utilise jamais `_run_subprocess_hardened` pour s'auto-exécuter.
  Le sandbox n'exécute que du code **généré par le LLM** — l'isolement est correct.
- `_run_subprocess_legacy` : ne jamais supprimer. Utilisé par les tests de régression
  qui verifient le comportement historique pre-FL-03.
- `exit_code=-2` est un code **interne LCCA** (pas un code Python réel).
  Le TesterAgent doit traiter `-2` comme un rejet sécurité, distinct de `-1` (timeout).
- `_prescan_imports` avec `import ast as _ast` : l'alias `_ast` évite toute collision
  si le code scanné contient lui-même `import ast`.

## Mise à jour skills post-sprint

- **001** : FL-03 — `_FORBIDDEN_SOFT`, `_prescan_imports()`, `_run_subprocess_hardened()`, `_run_subprocess_legacy()`, `effective_mode` → `"soft_hardened"`
- **002** : +14 tests test_fl_03.py, état tests ~1580
- **004** : FL-03 TERMINÉ
