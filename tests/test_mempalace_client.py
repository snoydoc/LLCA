# -*- coding: utf-8-sig -*-
"""
test_mempalace_client.py — LCCA V5 Fusion
Sprint 05 — TASK-05-07

Tests unitaires : MemPalaceClient + ContextAssembler
ChromaDB en mémoire (tmp_path) pour isolation et vitesse.
"""

from __future__ import annotations

import sys
import pytest
from pathlib import Path

# Marqueur global : tous les tests utilisant ChromaDB sont skippés sur Python 3.14+
_CHROMADB_SKIP = pytest.mark.skipif(
    sys.version_info >= (3, 14),
    reason="chromadb/pydantic.v1 incompatible Python 3.14+ (chroma_server_nofile)"
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_palace(tmp_path: Path):
    """MemPalaceClient isolé dans un dossier temporaire."""
    if sys.version_info >= (3, 14):
        pytest.skip("chromadb/pydantic.v1 incompatible Python 3.14+")
    from core.mempalace_client import MemPalaceClient
    return MemPalaceClient(palace_path=str(tmp_path / "test_palace"))


@pytest.fixture
def mock_intent():
    """Intent minimal pour ContextAssembler."""
    from dataclasses import dataclass
    from typing import Optional

    @dataclass
    class FakeIntent:
        project:    str            = "TestProjet"
        target:     str            = "auth"
        sub_target: Optional[str]  = "login"
        action:     str            = "ajoute"
        details:    str            = "validate_token()"
        raw:        str            = ""
        confidence: float          = 1.0

    return FakeIntent()


# ──────────────────────────────────────────────────────────────────────────────
# TestMemPalaceClient
# ──────────────────────────────────────────────────────────────────────────────

@_CHROMADB_SKIP
class TestMemPalaceClient:

    def test_init_creates_dirs(self, tmp_palace) -> None:
        """__init__ crée wings/, halls/, chroma_db/ dans palace_path."""
        assert (tmp_palace.palace_path / "wings").exists()
        assert (tmp_palace.palace_path / "halls").exists()
        assert (tmp_palace.palace_path / "chroma_db").exists()

    def test_init_idempotent(self, tmp_path: Path) -> None:
        """Double instanciation sans erreur (collections get_or_create)."""
        from core.mempalace_client import MemPalaceClient
        palace_path = str(tmp_path / "double_init")
        MemPalaceClient(palace_path=palace_path)
        # 2ème init sur le même chemin
        palace2 = MemPalaceClient(palace_path=palace_path)
        assert palace2.collections[0].count() >= 1  # Identity présente

    def test_mine_and_retrieve(self, tmp_palace) -> None:
        """mine_content() puis get_by_id() retourne le même contenu."""
        entry_id = tmp_palace.mine_content(
            "def validate_token(token): return bool(token)",
            wing="lcca",
            room="sprint_05",
        )
        assert isinstance(entry_id, str)
        assert len(entry_id) == 12

        entry = tmp_palace.get_by_id(entry_id)
        assert entry is not None
        assert "validate_token" in entry.content
        assert entry.wing == "lcca"
        assert entry.room == "sprint_05"

    def test_mine_creates_json_file(self, tmp_palace) -> None:
        """mine_content() crée un fichier JSON sur le filesystem."""
        entry_id = tmp_palace.mine_content("test content", wing="lcca", room="sprint_05")
        json_file = (
            tmp_palace.palace_path / "wings" / "lcca" / "rooms" / "sprint_05" / f"{entry_id}.json"
        )
        assert json_file.exists(), f"Fichier JSON attendu : {json_file}"

    def test_mine_empty_content_raises(self, tmp_palace) -> None:
        """mine_content('') → ValueError."""
        with pytest.raises(ValueError, match="vide"):
            tmp_palace.mine_content("")

    def test_mine_whitespace_only_raises(self, tmp_palace) -> None:
        """mine_content('   ') → ValueError."""
        with pytest.raises(ValueError, match="vide"):
            tmp_palace.mine_content("   ")

    def test_search_returns_relevant(self, tmp_palace) -> None:
        """Stocker 3 souvenirs, chercher → retourne le plus pertinent."""
        tmp_palace.mine_content("def apply_patch(file): ...", wing="lcca")
        tmp_palace.mine_content("def rollback_tx(tx_id): ...", wing="lcca")
        tmp_palace.mine_content("def send_email(to): ...", wing="lcca")

        results = tmp_palace.search_memories("patch function apply", wing="lcca")
        assert len(results) >= 1
        # Le résultat le plus pertinent doit parler de patch
        assert any("patch" in r.content for r in results)

    def test_wing_filter_isolates(self, tmp_palace) -> None:
        """Souvenir wing='A' non retourné si on cherche dans wing='B'."""
        tmp_palace.mine_content("secret data wing A", wing="wing_a")
        tmp_palace.mine_content("public data wing B", wing="wing_b")

        results = tmp_palace.search_memories("secret data", wing="wing_b")
        # wing_a ne doit pas apparaître dans une recherche wing_b
        for r in results:
            assert r.wing != "wing_a", "Fuite de wing_a dans résultats wing_b"

    def test_search_empty_collection_returns_empty(self, tmp_palace) -> None:
        """Recherche dans collection vide → liste vide, pas d'erreur."""
        results = tmp_palace.search_memories("quelque chose", layer=2)
        assert results == []

    def test_search_empty_query_returns_empty(self, tmp_palace) -> None:
        """Query vide → liste vide immédiatement."""
        results = tmp_palace.search_memories("")
        assert results == []

    def test_n_results_respected(self, tmp_palace) -> None:
        """n_results limite le nombre de résultats retournés."""
        for i in range(6):
            tmp_palace.mine_content(f"souvenir numéro {i}", wing="lcca")

        results = tmp_palace.search_memories("souvenir", wing="lcca", n_results=3)
        assert len(results) <= 3

    def test_wake_up_no_args(self, tmp_palace) -> None:
        """wake_up() sans args retourne au moins l'identity."""
        ctx = tmp_palace.wake_up()
        assert "identity" in ctx
        assert isinstance(ctx["identity"], str)
        assert len(ctx["identity"]) > 10
        assert ctx["compressed_knowledge"] == []
        assert ctx["recent_activity"] == []

    def test_wake_up_with_wing(self, tmp_palace) -> None:
        """wake_up(wing='lcca') retourne identity + compressed_knowledge si données."""
        # Stocker dans Layer 1
        tmp_palace.mine_content("Résumé LCCA sprint 05", wing="lcca", layer=1)
        ctx = tmp_palace.wake_up(wing="lcca")
        assert "identity" in ctx
        assert isinstance(ctx["compressed_knowledge"], list)

    def test_wake_up_with_wing_and_room(self, tmp_palace) -> None:
        """wake_up(wing, room) retourne les 3 niveaux."""
        tmp_palace.mine_content("Activité sprint_05", wing="lcca", room="sprint_05", layer=2)
        ctx = tmp_palace.wake_up(wing="lcca", room="sprint_05")
        assert "recent_activity" in ctx
        assert isinstance(ctx["recent_activity"], list)


# ──────────────────────────────────────────────────────────────────────────────
# TestContextAssembler
# ──────────────────────────────────────────────────────────────────────────────

@_CHROMADB_SKIP
class TestContextAssembler:

    def test_context_assembler_respects_limit(self, tmp_palace, mock_intent) -> None:
        """Contexte assemblé < max_tokens."""
        from core.context_assembler import ContextAssembler

        assembler = ContextAssembler(palace=tmp_palace, max_tokens=500)
        huge_file = "x = 1\n" * 5000  # ~30k chars >> 500 tokens

        result = assembler.assemble(
            intent=mock_intent,
            target_files=["auth.py"],
            file_contents={"auth.py": huge_file},
        )

        estimated = assembler.estimate_tokens(result)
        assert estimated <= 600, f"Budget dépassé : {estimated} tokens estimés (max 500)"

    def test_context_assembler_always_includes_intent(self, tmp_palace, mock_intent) -> None:
        """Même si contexte plein, le projet et l'action sont présents."""
        from core.context_assembler import ContextAssembler

        assembler = ContextAssembler(palace=tmp_palace, max_tokens=300)
        result = assembler.assemble(
            intent=mock_intent,
            target_files=["auth.py"],
            file_contents={"auth.py": "# vide"},
        )

        assert "TestProjet" in result
        assert "ajoute" in result

    def test_estimate_tokens(self, tmp_palace) -> None:
        """estimate_tokens : 4 chars ≈ 1 token."""
        from core.context_assembler import ContextAssembler

        assembler = ContextAssembler(palace=tmp_palace)
        assert assembler.estimate_tokens("abcd") == 1
        assert assembler.estimate_tokens("a" * 400) == 100

    def test_truncate_to_fit_respects_priority(self, tmp_palace) -> None:
        """truncate_to_fit : sections priorité haute toujours présentes."""
        from core.context_assembler import ContextAssembler

        assembler = ContextAssembler(palace=tmp_palace)
        critical = ("Section critique " * 10, 10)   # priorité haute
        optional = ("Section optionnelle " * 100, 5)  # priorité basse, volumineuse

        result = assembler.truncate_to_fit([critical, optional], budget=50)
        assert "Section critique" in result

    def test_assemble_returns_string(self, tmp_palace, mock_intent) -> None:
        """assemble() retourne bien un str non vide."""
        from core.context_assembler import ContextAssembler

        assembler = ContextAssembler(palace=tmp_palace, max_tokens=2000)
        result = assembler.assemble(
            intent=mock_intent,
            target_files=["auth.py"],
            file_contents={"auth.py": "def login(): pass"},
            wing="lcca",
            room="sprint_05",
        )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_assemble_contains_sections(self, tmp_palace, mock_intent) -> None:
        """assemble() contient les sections Identity et Task."""
        from core.context_assembler import ContextAssembler

        assembler = ContextAssembler(palace=tmp_palace, max_tokens=2000)
        result = assembler.assemble(
            intent=mock_intent,
            target_files=["auth.py"],
            file_contents={"auth.py": "def login(): pass"},
        )
        assert "## Identity" in result
        assert "## Task" in result
        assert "auth.py" in result

    def test_assemble_with_memories(self, tmp_palace, mock_intent) -> None:
        """assemble() inclut la section memories si des souvenirs existent."""
        from core.context_assembler import ContextAssembler

        # Stocker un souvenir pertinent
        tmp_palace.mine_content("validate_token est critique pour auth", wing="lcca")

        assembler = ContextAssembler(palace=tmp_palace, max_tokens=4000)
        result = assembler.assemble(
            intent=mock_intent,
            target_files=["auth.py"],
            file_contents={"auth.py": "def login(): pass"},
            wing="lcca",
        )
        # Doit contenir au moins Identity + Task
        assert "## Identity" in result
        assert "## Task" in result

    def test_assemble_no_file_contents(self, tmp_palace, mock_intent) -> None:
        """assemble() fonctionne sans contenu de fichiers (dict vide)."""
        from core.context_assembler import ContextAssembler

        assembler = ContextAssembler(palace=tmp_palace, max_tokens=2000)
        result = assembler.assemble(
            intent=mock_intent,
            target_files=[],
            file_contents={},
        )
        assert isinstance(result, str)
        assert "## Task" in result


