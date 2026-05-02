"""
Smoke tests Sprint 01 — Validation environnement LCCA V5 Fusion.
Lancer avec : pytest tests/test_smoke.py -v
"""
import sys
import pytest
from pathlib import Path
from importlib.metadata import version, PackageNotFoundError


# ── Environnement Python ──────────────────────────────────────────────────────

def test_python_version():
    """Python 3.11+ requis."""
    assert sys.version_info >= (3, 11), (
        f"Python 3.11+ requis, trouvé {sys.version}"
    )


# ── Dépendances importables ───────────────────────────────────────────────────

@pytest.mark.skipif(
    sys.version_info >= (3, 14),
    reason="libcst pas compatible Python 3.14+ (pydantic v1 constraint)"
)
def test_libcst_importable():
    """libcst doit être installé >= 1.1.0.
    Note: libcst n'expose pas __version__ directement → importlib.metadata.
    """
    import libcst  # doit être importable sans erreur
    v = version("libcst")   # ex: "1.1.0"
    major, minor, *_ = (int(x) for x in v.split("."))
    assert (major, minor) >= (1, 1), f"libcst >= 1.1.0 requis, trouvé {v}"


@pytest.mark.skipif(
    sys.version_info >= (3, 14),
    reason="chromadb/pydantic.v1 incompatible Python 3.14+ (ConfigError: chroma_server_nofile)"
)
def test_chromadb_importable():
    import chromadb
    assert chromadb is not None


def test_pyyaml_importable():
    import yaml
    assert yaml is not None


def test_pytest_importable():
    import pytest as _pytest
    assert _pytest is not None


# ── Arborescence dossiers ─────────────────────────────────────────────────────

def test_directory_structure():
    base = Path("D:/LLMCodeAgent")
    required = ["core", "workspace", "transactions", "tests", "utils", "logs"]
    missing = [d for d in required if not (base / d).exists()]
    assert not missing, f"Dossiers manquants : {missing}"


# ── Config importable ─────────────────────────────────────────────────────────

def test_config_importable():
    from config import BASE_DIR, WORKSPACE_DIR, TRANSACTIONS_DIR, WAL_PATH, MAX_FILES_PER_TX
    assert BASE_DIR.exists(), f"BASE_DIR introuvable : {BASE_DIR}"
    assert WORKSPACE_DIR.exists()
    assert TRANSACTIONS_DIR.exists()
    assert MAX_FILES_PER_TX == 3


# ── Logger importable et fonctionnel ─────────────────────────────────────────

def test_logger_importable():
    from utils.logger import get_logger
    log = get_logger("smoke_test")
    assert log is not None
    log.info("Smoke test logger OK")


def test_logger_idempotent():
    """Appeler get_logger deux fois ne doit pas doubler les handlers."""
    from utils.logger import get_logger
    log1 = get_logger("idempotent_test")
    handler_count = len(log1.handlers)
    log2 = get_logger("idempotent_test")
    assert len(log2.handlers) == handler_count, "Handlers dupliqués !"


# ── Packages core importables ─────────────────────────────────────────────────

def test_core_package_importable():
    import core
    assert hasattr(core, "__version__")


def test_utils_package_importable():
    import utils
    assert utils is not None
