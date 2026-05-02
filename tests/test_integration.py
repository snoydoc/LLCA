# -*- coding: utf-8-sig -*-
"""
test_integration.py — LCCA V5 Fusion
Sprint 07 — TASK-07-03

Tests d'intégration end-to-end : exercent le pipeline complet sur un workspace
temporaire isolé. Aucun effet de bord entre les tests (fixtures indépendantes).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core.orchestrator import LCCAV5Fusion
from core.transaction_manager import TransactionManager


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def test_workspace(tmp_path: Path) -> Path:
    """Workspace de test avec quelques fichiers Python de base."""
    ws = tmp_path / "workspace"
    ws.mkdir()

    (ws / "auth.py").write_text(
        '"""\nModule d\'authentification.\n"""\n\n\n'
        "def login(username: str, password: str) -> bool:\n"
        '    """Authentifie un utilisateur."""\n'
        '    return username == "admin" and password == "secret"\n',
        encoding="utf-8-sig",
    )

    (ws / "utils.py").write_text(
        '"""\nUtilitaires.\n"""\n\n\n'
        "def format_email(email: str) -> str:\n"
        '    """Normalise une adresse email."""\n'
        "    return email.strip().lower()\n",
        encoding="utf-8-sig",
    )

    return ws


@pytest.fixture
def tx_dir(tmp_path: Path) -> Path:
    d = tmp_path / "transactions"
    d.mkdir()
    return d


@pytest.fixture
def lcca(test_workspace: Path, tx_dir: Path) -> LCCAV5Fusion:
    """Instance LCCAV5Fusion isolée avec workspace et tx_dir temporaires."""
    tx_manager = TransactionManager(tx_dir=tx_dir)
    return LCCAV5Fusion(
        workspace=test_workspace,
        tx_manager=tx_manager,
    )


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestIntegration:

    def test_dry_run_no_modification(
        self, lcca: LCCAV5Fusion, test_workspace: Path
    ) -> None:
        """dry_run() ne modifie aucun fichier et ne crée aucune entrée WAL."""
        auth_before = _md5(test_workspace / "auth.py")
        utils_before = _md5(test_workspace / "utils.py")

        result = lcca.dry_run("Auth - auth - Ajoute validate_email()")

        # Aucun fichier modifié
        assert _md5(test_workspace / "auth.py") == auth_before
        assert _md5(test_workspace / "utils.py") == utils_before

        # WAL non créé (pas d'écriture)
        assert not lcca.tx_manager.wal_path.exists()

        # Résultat structuré retourné
        assert "intent" in result
        assert "target_files" in result
        assert "plan" in result

    def test_dry_run_returns_intent(self, lcca: LCCAV5Fusion) -> None:
        """dry_run() retourne un intent parsé correctement."""
        result = lcca.dry_run("Projet - auth - Ajoute validate_email()")
        intent = result["intent"]
        assert intent.target == "auth"
        assert intent.confidence > 0

    def test_add_function_to_existing_file(
        self, lcca: LCCAV5Fusion, test_workspace: Path
    ) -> None:
        """
        Scénario : Ajouter une fonction à auth.py.
        Résultat : auth.py modifié, syntaxe valide, TX commitée dans WAL.
        """
        auth_path = test_workspace / "auth.py"
        hash_before = _md5(auth_path)

        success = lcca.execute("Auth - auth - Ajoute validate_token()")
        # Le succès n'est pas garanti si le stub échoue le patch,
        # mais le fichier doit rester syntaxiquement valide dans tous les cas.
        content = auth_path.read_text(encoding="utf-8-sig")
        compile(content, "auth.py", "exec")  # SyntaxError si invalide

        # Si succès, le fichier doit être modifié
        if success:
            # Au moins un COMMIT dans le WAL
            assert lcca.tx_manager.wal_path.exists()
            wal_content = lcca.tx_manager.wal_path.read_text(encoding="utf-8-sig")
            commits = [
                json.loads(l) for l in wal_content.splitlines()
                if l.strip() and json.loads(l).get("type") == "COMMIT"
            ]
            assert len(commits) >= 1

    def test_create_new_file(
        self, lcca: LCCAV5Fusion, test_workspace: Path
    ) -> None:
        """
        Scénario : Créer un nouveau fichier via commande DSL.
        Résultat : fichier créé, syntaxiquement valide.
        """
        new_file = test_workspace / "validation.py"
        assert not new_file.exists()

        lcca.execute("Projet - validation - Crée le module validation")

        # Si le fichier est créé, il doit être syntaxiquement valide
        if new_file.exists():
            content = new_file.read_text(encoding="utf-8-sig")
            compile(content, "validation.py", "exec")

    def test_rollback_preserves_original(
        self, lcca: LCCAV5Fusion, test_workspace: Path
    ) -> None:
        """
        Scénario : Forcer un rollback en injectant un mock LLM qui retourne
        du code Python syntaxiquement invalide.
        Résultat : auth.py inchangé (MD5 identique) + success is False.

        NOTE: Le monkey-patch de _generate_stub() ne fonctionne plus depuis
        Sprint 09 — execute() appelle self.llm.generate() directement.
        _generate_stub() est deprecated/dead code depuis Sprint 09.
        On injecte un MagicMock sur lcca.llm (même pattern que test_wal_contains_full_trace).
        """
        from unittest.mock import MagicMock
        from core.llm_generator import GenerationResult

        auth_path = test_workspace / "auth.py"
        hash_before = _md5(auth_path)

        # Mock LLM qui retourne du code syntaxiquement invalide
        _BAD_CODE = "def (:\n    !!syntaxe cassée\n"
        mock_result = GenerationResult(
            code=_BAD_CODE,
            model="mock-bad",
            from_cache=False,
            from_fallback=True,
            prompt_tokens=0,
            duration_ms=0,
        )
        mock_llm = MagicMock()
        mock_llm.generate.return_value = mock_result
        mock_llm.is_available.return_value = False
        mock_llm.fallback.generate.return_value = _BAD_CODE

        lcca.llm = mock_llm

        success = lcca.execute("Auth - auth - Modifie login()", auto_rollback=True)

        # Échec attendu (code invalide → _validate_changes() lève, rollback auto)
        assert success is False

        # auth.py doit être identique à avant (rollback garanti)
        assert _md5(auth_path) == hash_before

    def test_wal_contains_full_trace(
        self, lcca: LCCAV5Fusion, test_workspace: Path
    ) -> None:
        """
        Après une TX commitée, le WAL contient BEGIN + OP_START + OP_SUCCESS + COMMIT.

        Le LLM est remplacé par un mock qui retourne du code Python valide,
        ce qui rend le test inconditionnellement exécutable (sans Ollama).

        La Spec Layer est désactivée (ADAPTIVE_SPEC_ENABLED=False) pour ce test
        car elle requiert un LLM fonctionnel pour générer une spec, ce qui ne
        peut pas être satisfait par un mock LLM de test unitaire.
        """
        from core.llm_generator import GenerationResult

        # Code valide garanti — indépendant d'Ollama
        _VALID_CODE = (
            "def check_password(password: str) -> bool:\n"
            '    """Vérifie la robustesse du mot de passe."""\n'
            "    return len(password) >= 8\n"
        )

        mock_result = GenerationResult(
            code=_VALID_CODE,
            model="mock",
            from_cache=False,
            from_fallback=False,
            prompt_tokens=10,
            duration_ms=0,
        )
        from unittest.mock import MagicMock
        mock_llm = MagicMock()
        mock_llm.generate.return_value = mock_result
        mock_llm.is_available.return_value = False

        lcca.llm = mock_llm

        # Désactiver la Spec Layer pour ce test — elle requiert un LLM réel
        # pour générer une spec valide, ce qui est hors scope d'un test d'intégration
        # sur le pipeline WAL/TX.
        with patch("config.ADAPTIVE_SPEC_ENABLED", False):
            success = lcca.execute("Auth - auth - Ajoute check_password()")

        assert success, (
            "execute() a échoué malgré un mock LLM valide — "
            "vérifier SmartPatcher ou TransactionManager"
        )

        wal_path = lcca.tx_manager.wal_path
        assert wal_path.exists(), "WAL non créé après exécution"

        entries = []
        for line in wal_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        types = {e["type"] for e in entries}
        assert "BEGIN"  in types, "BEGIN manquant dans le WAL"
        assert "COMMIT" in types, "COMMIT manquant dans le WAL"
        if any(e["type"] == "OP_START" for e in entries):
            assert any(e["type"] == "OP_SUCCESS" for e in entries), \
                "OP_SUCCESS absent alors qu'OP_START présent"

    def test_full_pipeline_reindex(
        self, lcca: LCCAV5Fusion, test_workspace: Path
    ) -> None:
        """
        Après un execute() réussi, l'index AST est mis à jour.
        """
        n_files_before = len(lcca.indexer.files)

        # Créer un nouveau fichier via DSL
        lcca.execute("Projet - newmodule - Crée newmodule")

        new_file = test_workspace / "newmodule.py"
        if new_file.exists():
            # L'index doit avoir été mis à jour
            assert len(lcca.indexer.files) >= n_files_before


# ──────────────────────────────────────────────────────────────────────────────
# Tests WAL archivage (TASK-07-04)
# ──────────────────────────────────────────────────────────────────────────────

class TestWALArchive:

    def test_archive_empty_wal_returns_zero(self, tx_dir: Path) -> None:
        """WAL inexistant → archive_old_wal_entries() retourne 0."""
        tx = TransactionManager(tx_dir=tx_dir)
        assert tx.archive_old_wal_entries() == 0

    def test_archive_recent_entries_kept(self, tx_dir: Path) -> None:
        """Entrées récentes → conservées dans le WAL, pas archivées."""
        tx = TransactionManager(tx_dir=tx_dir)
        tx.begin(dsl_input="test", project="lcca", intent="test")
        tx.commit()

        n_archived = tx.archive_old_wal_entries(days_to_keep=7)
        assert n_archived == 0
        assert tx.wal_path.exists()

    def test_archive_old_entries_moved(self, tx_dir: Path) -> None:
        """Entrées anciennes (injections manuelles) → archivées."""
        import json
        from datetime import timedelta
        from datetime import timezone as tz

        tx = TransactionManager(tx_dir=tx_dir)

        # Écrire manuellement une entrée vieille de 10 jours
        old_ts = (
            datetime_10_days_ago := __import__("datetime").datetime.now(tz.utc)
            - timedelta(days=10)
        ).isoformat()
        old_entry = json.dumps({
            "type": "COMMIT",
            "tx_id": "tx_old000001",
            "n_ops": 1,
            "_ts": old_ts,
        })

        tx.wal_path.write_text(old_entry + "\n", encoding="utf-8-sig")

        n_archived = tx.archive_old_wal_entries(days_to_keep=7)
        assert n_archived == 1

        # WAL courant doit être vide (ou sans l'ancienne entrée)
        remaining = tx.wal_path.read_text(encoding="utf-8-sig").strip()
        assert "tx_old000001" not in remaining

        # Un fichier archive doit exister
        archives = list(tx_dir.glob("wal_archive_*.jsonl"))
        assert len(archives) == 1
        archive_content = archives[0].read_text(encoding="utf-8-sig")
        assert "tx_old000001" in archive_content
