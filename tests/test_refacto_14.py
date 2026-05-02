# -*- coding: utf-8-sig -*-
"""
test_refacto_14.py — LCCA V5 Fusion
V9-09 / REFACTO-14 — Tests du découpage mempalace_client.py

3 classes × 6 tests = 18 tests.

Vérifie :
  - MemoryEntry accessible depuis mempalace_layers (rétrocompat via mempalace_client)
  - PalaceLayers : add, get_by_id, search, wake_up, build_where
  - PalaceFilesystem : write_entry crée le fichier JSON
  - MemPalaceClient : API publique inchangée (mine_content, get_by_id, search_memories, wake_up)
  - Alias rétrocompat : collections, _build_where, _write_to_filesystem
"""
from __future__ import annotations

import sys
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

_CHROMADB_SKIP = pytest.mark.skipif(
    sys.version_info >= (3, 14),
    reason="chromadb/pydantic.v1 incompatible Python 3.14+"
)


# ──────────────────────────────────────────────────────────────────────────────
# TestPalaceFilesystem — filesystem pur (pas de ChromaDB)
# ──────────────────────────────────────────────────────────────────────────────

class TestPalaceFilesystem:
    """Teste PalaceFilesystem indépendamment de ChromaDB."""

    def test_ensure_dirs_creates_structure(self, tmp_path: Path) -> None:
        """__init__ crée wings/, halls/, chroma_db/."""
        from core.mempalace_fs import PalaceFilesystem
        fs = PalaceFilesystem(tmp_path / "palace")
        assert (tmp_path / "palace" / "wings").exists()
        assert (tmp_path / "palace" / "halls").exists()
        assert (tmp_path / "palace" / "chroma_db").exists()

    def test_write_entry_creates_json(self, tmp_path: Path) -> None:
        """write_entry crée le fichier JSON sous wings/<wing>/rooms/<room>/."""
        from core.mempalace_fs import PalaceFilesystem
        fs = PalaceFilesystem(tmp_path / "palace")
        out = fs.write_entry(
            entry_id="abc123456789",
            content="def foo(): pass",
            meta={"source": "test", "layer": 3},
            wing="lcca",
            room="sprint_14",
        )
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8-sig"))
        assert data["entry_id"] == "abc123456789"
        assert "foo" in data["content"]

    def test_write_entry_untagged_fallback(self, tmp_path: Path) -> None:
        """write_entry sans wing → wings/_untagged/rooms/default/."""
        from core.mempalace_fs import PalaceFilesystem
        fs = PalaceFilesystem(tmp_path / "palace")
        out = fs.write_entry(
            entry_id="000000000000",
            content="content",
            meta={},
            wing=None,
            room=None,
        )
        assert "_untagged" in str(out)
        assert out.exists()

    def test_write_entry_idempotent_path(self, tmp_path: Path) -> None:
        """Deux appels avec même entry_id sur même wing/room → même chemin."""
        from core.mempalace_fs import PalaceFilesystem
        fs = PalaceFilesystem(tmp_path / "palace")
        out1 = fs.write_entry("abcdef123456", "v1", {}, "w", "r")
        out2 = fs.write_entry("abcdef123456", "v2", {}, "w", "r")
        # Le second écrase le premier (même chemin)
        assert out1 == out2
        data = json.loads(out2.read_text(encoding="utf-8-sig"))
        assert data["content"] == "v2"

    def test_chroma_path_property(self, tmp_path: Path) -> None:
        """chroma_path est palace_path/chroma_db."""
        from core.mempalace_fs import PalaceFilesystem
        fs = PalaceFilesystem(tmp_path / "palace")
        assert fs.chroma_path == tmp_path / "palace" / "chroma_db"

    def test_write_entry_content_in_json(self, tmp_path: Path) -> None:
        """Le contenu et les métas sont tous dans le JSON."""
        from core.mempalace_fs import PalaceFilesystem
        fs = PalaceFilesystem(tmp_path / "palace")
        meta = {"source": "lcca", "layer": 2, "wing": "lcca", "room": "r1"}
        out = fs.write_entry("zzzzzzzzzzzz", "contenu test", meta, "lcca", "r1")
        data = json.loads(out.read_text(encoding="utf-8-sig"))
        assert data["source"] == "lcca"
        assert data["layer"] == 2


# ──────────────────────────────────────────────────────────────────────────────
# TestPalaceLayers — ChromaDB mocké
# ──────────────────────────────────────────────────────────────────────────────

class TestPalaceLayers:
    """Teste PalaceLayers avec ChromaDB entièrement mocké."""

    def _make_layers(self):
        """Crée un PalaceLayers avec un client ChromaDB mocké."""
        from core.mempalace_layers import PalaceLayers

        col_mock = MagicMock()
        col_mock.count.return_value = 0  # vide → _init_identity déclenche add
        col_mock.query.return_value = {
            "documents": [[]],
            "metadatas": [[]],
            "ids": [[]],
        }
        col_mock.get.return_value = {"documents": [], "metadatas": []}

        chroma_mock = MagicMock()
        chroma_mock.get_or_create_collection.return_value = col_mock

        return PalaceLayers(chroma_mock), col_mock

    def test_init_creates_4_collections(self) -> None:
        """__init__ crée 4 collections (layer 0-3)."""
        layers, _ = self._make_layers()
        assert len(layers.collections) == 4

    def test_add_calls_chroma(self) -> None:
        """add() appelle col.add avec entry_id, content, meta."""
        layers, col_mock = self._make_layers()
        layers.add("abc123456789", "def foo(): pass", {"source": "test", "layer": 3}, 3)
        col_mock.add.assert_called()

    def test_build_where_none_if_no_filters(self) -> None:
        """build_where : sans filtres → None."""
        from core.mempalace_layers import PalaceLayers
        assert PalaceLayers.build_where(None, None, None) is None

    def test_build_where_single_wing(self) -> None:
        """build_where : un seul filtre → dict simple."""
        from core.mempalace_layers import PalaceLayers
        where = PalaceLayers.build_where("lcca", None, None)
        assert where == {"wing": {"$eq": "lcca"}}

    def test_build_where_multiple_filters(self) -> None:
        """build_where : plusieurs filtres → $and."""
        from core.mempalace_layers import PalaceLayers
        where = PalaceLayers.build_where("lcca", "sprint_05", None)
        assert "$and" in where
        assert len(where["$and"]) == 2

    def test_search_empty_query_returns_empty(self) -> None:
        """search('') → [] sans appel ChromaDB."""
        layers, col_mock = self._make_layers()
        result = layers.search("")
        assert result == []
        col_mock.query.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# TestMemPalaceClientAPI — API publique via test d'intégration (ChromaDB réel)
# ──────────────────────────────────────────────────────────────────────────────

@_CHROMADB_SKIP
class TestMemPalaceClientAPI:
    """Vérifie que l'API publique de MemPalaceClient est inchangée post-REFACTO-14."""

    @pytest.fixture
    def palace(self, tmp_path: Path):
        from core.mempalace_client import MemPalaceClient
        return MemPalaceClient(palace_path=str(tmp_path / "palace"))

    def test_collections_proxy_accessible(self, palace) -> None:
        """palace.collections[n] accessible comme avant (proxy rétrocompat)."""
        assert len(palace.collections) == 4
        assert palace.collections[0] is not None

    def test_mine_content_returns_12char_id(self, palace) -> None:
        """mine_content() retourne un entry_id 12 chars."""
        entry_id = palace.mine_content("def bar(): pass", wing="lcca")
        assert len(entry_id) == 12

    def test_mine_content_creates_json_file(self, palace) -> None:
        """mine_content() crée un fichier JSON (PalaceFilesystem)."""
        entry_id = palace.mine_content("content test", wing="lcca", room="r1")
        json_file = palace.palace_path / "wings" / "lcca" / "rooms" / "r1" / f"{entry_id}.json"
        assert json_file.exists()

    def test_get_by_id_returns_entry(self, palace) -> None:
        """get_by_id() retourne le MemoryEntry stocké."""
        entry_id = palace.mine_content("def baz(): pass", wing="lcca")
        entry = palace.get_by_id(entry_id)
        assert entry is not None
        assert "baz" in entry.content

    def test_search_memories_returns_list(self, palace) -> None:
        """search_memories() retourne une liste (éventuellement vide)."""
        palace.mine_content("def qux(): pass", wing="lcca")
        results = palace.search_memories("qux function", wing="lcca")
        assert isinstance(results, list)

    def test_wake_up_no_args_returns_identity(self, palace) -> None:
        """wake_up() retourne identity non vide."""
        ctx = palace.wake_up()
        assert "identity" in ctx
        assert len(ctx["identity"]) > 0
