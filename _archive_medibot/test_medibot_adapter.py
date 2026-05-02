# -*- coding: utf-8-sig -*-
"""
test_medibot_adapter.py — LCCA V5 Fusion
Sprint 08 — TASK-08-04

Tests de l'ExistingMemPalaceAdapter avec mocking filesystem.
N'exige PAS la présence physique de D:\\MediBot.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.mempalace_adapter import ExistingMemPalaceAdapter

_CHROMADB_SKIP = pytest.mark.skipif(
    sys.version_info >= (3, 14),
    reason="chromadb/pydantic.v1 incompatible Python 3.14+"
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_palace_path(tmp_path: Path) -> Path:
    """
    Crée une structure MemPalace factice dans tmp_path.

    Arborescence :
        tmp_path/
        └── Mempalace/
            └── memory_palace/
                ├── identity.txt
                ├── chroma.sqlite3
                └── specs/
                    ├── architecture.md
                    └── rdv-spec.md
    """
    palace = tmp_path / "Mempalace" / "memory_palace"
    palace.mkdir(parents=True)

    # Fichiers requis
    (palace / "identity.txt").write_text(
        "Je suis MediBot, assistant médical LCCA.",
        encoding="utf-8-sig",
    )
    (palace / "chroma.sqlite3").write_bytes(b"SQLite format 3\x00")  # magic bytes

    # Specs
    specs = palace / "specs"
    specs.mkdir()
    (specs / "architecture.md").write_text(
        "# Architecture MediBot\nModule RDV : gestion des rendez-vous médicaux.",
        encoding="utf-8-sig",
    )
    (specs / "rdv-spec.md").write_text(
        "# Spec RDV\nvalidation email obligatoire avant confirmation.",
        encoding="utf-8-sig",
    )

    return palace


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestExistingMemPalaceAdapter:

    def test_adapter_loads_identity(self, mock_palace_path: Path) -> None:
        """Identity chargée depuis identity.txt."""
        with patch(
            "core.mempalace_adapter.POSSIBLE_PATHS",
            [mock_palace_path],
        ):
            adapter = ExistingMemPalaceAdapter()

        assert adapter.is_available
        assert "MediBot" in adapter.identity

    def test_adapter_loads_specs(self, mock_palace_path: Path) -> None:
        """Specs .md chargées depuis specs/."""
        with patch(
            "core.mempalace_adapter.POSSIBLE_PATHS",
            [mock_palace_path],
        ):
            adapter = ExistingMemPalaceAdapter()

        assert adapter.is_available
        specs = adapter.specs
        assert len(specs) == 2
        names = {s["name"] for s in specs}
        assert "architecture" in names
        assert "rdv-spec" in names
        # Contenu présent
        all_content = " ".join(s["content"] for s in specs)
        assert "RDV" in all_content

    def test_adapter_fallback_if_no_palace(self, tmp_path: Path) -> None:
        """Si palace introuvable → is_available False, pas d'exception."""
        nonexistent = tmp_path / "nonexistent_palace"
        with patch(
            "core.mempalace_adapter.POSSIBLE_PATHS",
            [nonexistent],
        ):
            adapter = ExistingMemPalaceAdapter()

        assert not adapter.is_available
        assert adapter.identity == ""
        assert adapter.specs == []

    def test_wake_up_medi_returns_context(self, mock_palace_path: Path) -> None:
        """wake_up_medi() retourne identity + specs sans erreur."""
        with patch(
            "core.mempalace_adapter.POSSIBLE_PATHS",
            [mock_palace_path],
        ):
            adapter = ExistingMemPalaceAdapter()

        # Mock le client MemPalace pour éviter ChromaDB réel
        mock_client = MagicMock()
        mock_client.wake_up.return_value = {
            "identity": "",
            "compressed_knowledge": ["knowledge entry"],
            "recent_activity": [],
            "timestamp": "2026-04-17T00:00:00+00:00",
        }
        adapter._client = mock_client

        ctx = adapter.wake_up_medi()

        assert "identity" in ctx
        assert "specs" in ctx
        assert "palace_path" in ctx
        assert "timestamp" in ctx
        assert len(ctx["specs"]) == 2
        assert ctx["palace_path"] is not None
        # Identity depuis identity.txt
        assert "MediBot" in ctx["identity"]

    @_CHROMADB_SKIP
    def test_lcca_collections_isolated(self, mock_palace_path: Path) -> None:
        """
        Les collections lcca_* sont créées séparément.
        Ici on vérifie que _init_lcca_collections() ne plante pas
        et que si chromadb est présent, les noms sont corrects.
        """
        with patch(
            "core.mempalace_adapter.POSSIBLE_PATHS",
            [mock_palace_path],
        ):
            # Mock chromadb pour éviter dépendance optionnelle
            mock_col = MagicMock()
            mock_chroma_client = MagicMock()
            mock_chroma_client.get_or_create_collection.return_value = mock_col

            with patch("chromadb.PersistentClient", return_value=mock_chroma_client):
                adapter = ExistingMemPalaceAdapter()

        # Toutes les collections LCCA sont présentes
        expected = {"lcca_transactions", "lcca_ast_index", "lcca_sessions"}
        assert set(adapter.lcca_collections.keys()) == expected

        # Vérifier que get_or_create_collection a été appelé 3 fois
        assert mock_chroma_client.get_or_create_collection.call_count == 3

        # Vérifier que les noms passés commencent tous par "lcca_"
        called_names = {
            call.args[0]
            for call in mock_chroma_client.get_or_create_collection.call_args_list
        }
        assert all(n.startswith("lcca_") for n in called_names)

    def test_find_relevant_specs(self, mock_palace_path: Path) -> None:
        """find_relevant_specs() retourne les specs pertinentes selon mots-clés."""
        with patch(
            "core.mempalace_adapter.POSSIBLE_PATHS",
            [mock_palace_path],
        ):
            adapter = ExistingMemPalaceAdapter()

        # "rdv" est dans le contenu des deux specs
        result = adapter.find_relevant_specs(["rdv"], max_specs=2)
        assert "rdv" in result.lower() or "RDV" in result

        # Mot-clé absent → chaîne vide
        result_empty = adapter.find_relevant_specs(["xyznotfound"])
        assert result_empty == ""

    def test_wake_up_medi_unavailable(self, tmp_path: Path) -> None:
        """wake_up_medi() sur palace absent retourne dict avec valeurs vides."""
        nonexistent = tmp_path / "no_palace"
        with patch(
            "core.mempalace_adapter.POSSIBLE_PATHS",
            [nonexistent],
        ):
            adapter = ExistingMemPalaceAdapter()

        ctx = adapter.wake_up_medi()
        assert ctx["identity"] == "MemPalace non disponible."
        assert ctx["specs"] == []
        assert ctx["palace_path"] is None
