# -*- coding: utf-8-sig -*-
"""
test_proj_11.py - PROJ-11
Tests ProjectContributor - Pipeline de contribution skills locales vers base globale.

5 classes :
  TestContributionResult        -- to_dict(), valeurs par defaut
  TestHelpers                   -- _load_local_skills, _is_confidential, _dedup_local,
                                   _build_global_entry_id, _increment_skills_generated
  TestContributorPalaceAbsent   -- mode degrade silencieux (palace None)
  TestContributorPipeline       -- pipeline complet (scan, dedup, guard, quality, index)
  TestExtractQuality            -- _extract_quality() frontmatter
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from core.project_contributor import (
    ProjectContributor,
    ContributionResult,
    _load_local_skills,
    _is_confidential,
    _dedup_local,
    _build_global_entry_id,
    _increment_skills_generated,
    JACCARD_THRESHOLD,
    _CONFIDENTIAL_MARKER,
)


# ===================================================================
# Helpers
# ===================================================================

def _make_meta(slug="test-proj", pid="pid-001", name="Test Projet"):
    m = MagicMock()
    m.id   = pid
    m.slug = slug
    m.name = name
    return m


def _seed_project(tmp_path: Path, slug: str = "test-proj") -> Path:
    """Cree la structure d'un projet minimal."""
    proj = tmp_path / slug
    (proj / ".llca").mkdir(parents=True)
    (proj / "skills").mkdir()
    meta = {
        "id": "pid-001", "slug": slug, "name": "Test Projet",
        "status": "active", "stats": {"skills_generated": 0},
    }
    (proj / ".llca" / "project.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )
    return proj


def _write_skill(skills_dir: Path, name: str, body: str) -> None:
    skills_dir.mkdir(parents=True, exist_ok=True)
    (skills_dir / f"{name}.md").write_text(body, encoding="utf-8")


def _make_palace(results=None):
    """Fabrique un MemPalaceClient mock."""
    palace = MagicMock()
    palace.search_memories.return_value = results or []
    return palace


# ===================================================================
# TestContributionResult
# ===================================================================

class TestContributionResult:
    def test_defaults(self):
        r = ContributionResult()
        assert r.scanned            == 0
        assert r.skipped_dedup      == 0
        assert r.skipped_global     == 0
        assert r.skipped_quality    == 0
        assert r.skipped_confidential == 0
        assert r.contributed_count  == 0
        assert r.contributed_ids    == []
        assert r.errors             == []
        assert r.palace_available   is True

    def test_to_dict_keys(self):
        r = ContributionResult(scanned=3, contributed_count=1)
        d = r.to_dict()
        for key in (
            "scanned", "skipped_dedup", "skipped_global",
            "skipped_quality", "skipped_confidential",
            "contributed_count", "contributed_ids",
            "errors", "palace_available",
        ):
            assert key in d, f"Cle manquante : {key}"

    def test_to_dict_values(self):
        r = ContributionResult(
            scanned=5, skipped_dedup=1, skipped_global=1,
            skipped_quality=1, skipped_confidential=1,
            contributed_count=1, contributed_ids=["abc"], errors=["err"],
            palace_available=False,
        )
        d = r.to_dict()
        assert d["scanned"] == 5
        assert d["contributed_count"] == 1
        assert d["contributed_ids"] == ["abc"]
        assert d["palace_available"] is False


# ===================================================================
# TestHelpers
# ===================================================================

class TestHelpers:
    # --- _load_local_skills ---
    def test_load_empty_dir(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        assert _load_local_skills(skills_dir) == []

    def test_load_absent_dir(self, tmp_path):
        assert _load_local_skills(tmp_path / "nope") == []

    def test_load_reads_md_files(self, tmp_path):
        skills_dir = tmp_path / "skills"
        _write_skill(skills_dir, "skill_a", "quality_score: 80\nContenu A")
        _write_skill(skills_dir, "skill_b", "quality_score: 70\nContenu B")
        skills = _load_local_skills(skills_dir)
        assert len(skills) == 2
        names = {s["name"] for s in skills}
        assert "skill_a" in names
        assert "skill_b" in names

    def test_load_ignores_non_md(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "readme.txt").write_text("ignore", encoding="utf-8")
        (skills_dir / "skill_c.md").write_text("quality_score: 65\nOk", encoding="utf-8")
        skills = _load_local_skills(skills_dir)
        assert len(skills) == 1
        assert skills[0]["name"] == "skill_c"

    def test_load_ignores_empty_md(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "empty.md").write_text("   ", encoding="utf-8")
        assert _load_local_skills(skills_dir) == []

    # --- _is_confidential ---
    def test_confidential_marker_detected(self):
        assert _is_confidential(f"Chemin : {_CONFIDENTIAL_MARKER}/mon/chemin") is True

    def test_no_marker(self):
        assert _is_confidential("Contenu clean sans marqueur") is False

    # --- _dedup_local ---
    def test_dedup_keeps_unique(self):
        skills = [
            {"name": "a", "body": "alpha beta gamma delta epsilon"},
            {"name": "b", "body": "totally different words here now"},
        ]
        kept, skipped = _dedup_local(skills, JACCARD_THRESHOLD)
        assert len(kept) == 2
        assert skipped == 0

    def test_dedup_removes_near_duplicate(self):
        base = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        skills = [
            {"name": "a", "body": base},
            {"name": "b", "body": base},  # identique => rejet
        ]
        kept, skipped = _dedup_local(skills, JACCARD_THRESHOLD)
        assert len(kept) == 1
        assert skipped == 1

    def test_dedup_empty_list(self):
        kept, skipped = _dedup_local([], JACCARD_THRESHOLD)
        assert kept == []
        assert skipped == 0

    # --- _build_global_entry_id ---
    def test_entry_id_stable(self):
        id1 = _build_global_entry_id("mon-projet", "skill_a")
        id2 = _build_global_entry_id("mon-projet", "skill_a")
        assert id1 == id2

    def test_entry_id_different_slugs(self):
        id1 = _build_global_entry_id("projet-a", "skill_x")
        id2 = _build_global_entry_id("projet-b", "skill_x")
        assert id1 != id2

    def test_entry_id_length(self):
        eid = _build_global_entry_id("p", "s")
        assert len(eid) == 12

    # --- _increment_skills_generated ---
    def test_increment_creates_stat(self, tmp_path):
        pjson = tmp_path / "project.json"
        pjson.write_text(json.dumps({"stats": {}}), encoding="utf-8")
        _increment_skills_generated(pjson)
        data = json.loads(pjson.read_text(encoding="utf-8"))
        assert data["stats"]["skills_generated"] == 1

    def test_increment_adds_to_existing(self, tmp_path):
        pjson = tmp_path / "project.json"
        pjson.write_text(json.dumps({"stats": {"skills_generated": 4}}), encoding="utf-8")
        _increment_skills_generated(pjson)
        data = json.loads(pjson.read_text(encoding="utf-8"))
        assert data["stats"]["skills_generated"] == 5

    def test_increment_atomic_via_tmp(self, tmp_path):
        """Verifie que l'ecriture passe par un fichier .tmp (T-14)."""
        pjson = tmp_path / "project.json"
        pjson.write_text(json.dumps({"stats": {}}), encoding="utf-8")
        _increment_skills_generated(pjson)
        # Le .tmp doit avoir disparu apres replace()
        assert not (tmp_path / "project.tmp").exists()

    def test_increment_silent_on_error(self, tmp_path):
        """Fichier absent -> aucune exception."""
        _increment_skills_generated(tmp_path / "absent.json")  # ne doit pas lever


# ===================================================================
# TestContributorPalaceAbsent
# ===================================================================

class TestContributorPalaceAbsent:
    def test_palace_none_returns_result(self, tmp_path):
        proj = _seed_project(tmp_path)
        skills_dir = proj / "skills"
        _write_skill(skills_dir, "skill_x", "quality_score: 80\nContenu valide")

        contributor = ProjectContributor(palace_client=None, min_quality_score=0)

        # Bloquer l'instanciation automatique du palace
        with patch("core.project_contributor.ProjectContributor._get_palace", return_value=None):
            meta = _make_meta()
            result = contributor.contribute(meta, projects_dir=tmp_path)

        assert isinstance(result, ContributionResult)
        assert result.palace_available is False
        assert result.contributed_count == 0
        assert result.errors == []

    def test_no_skills_dir_returns_empty(self, tmp_path):
        proj = _seed_project(tmp_path)
        # Supprimer le dossier skills
        (proj / "skills").rmdir()

        palace = _make_palace()
        contributor = ProjectContributor(palace_client=palace, min_quality_score=0)
        meta = _make_meta()
        result = contributor.contribute(meta, projects_dir=tmp_path)

        assert result.scanned == 0
        assert result.contributed_count == 0
        palace.mine_content.assert_not_called()

    def test_contribute_never_raises(self, tmp_path):
        """contribute() ne doit jamais lever, meme sur un meta invalide."""
        contributor = ProjectContributor(palace_client=MagicMock())
        # meta sans attribut slug -> AttributeError interne
        bad_meta = object()
        result = contributor.contribute(bad_meta, projects_dir=tmp_path)
        assert isinstance(result, ContributionResult)
        assert len(result.errors) >= 1


# ===================================================================
# TestContributorPipeline
# ===================================================================

class TestContributorPipeline:
    def test_quality_guard_rejects_below_threshold(self, tmp_path):
        proj = _seed_project(tmp_path)
        skills_dir = proj / "skills"
        _write_skill(skills_dir, "low_q", "quality_score: 10\nContenu trop faible")

        palace = _make_palace()
        contributor = ProjectContributor(palace_client=palace, min_quality_score=60)
        meta = _make_meta()
        result = contributor.contribute(meta, projects_dir=tmp_path)

        assert result.scanned == 1
        assert result.skipped_quality == 1
        assert result.contributed_count == 0
        palace.mine_content.assert_not_called()

    def test_confidential_guard_rejects(self, tmp_path):
        proj = _seed_project(tmp_path)
        skills_dir = proj / "skills"
        _write_skill(
            skills_dir, "conf_skill",
            f"quality_score: 90\nChemin {_CONFIDENTIAL_MARKER}/data"
        )

        palace = _make_palace()
        contributor = ProjectContributor(palace_client=palace, min_quality_score=0)
        meta = _make_meta()
        result = contributor.contribute(meta, projects_dir=tmp_path)

        assert result.skipped_confidential == 1
        assert result.contributed_count == 0
        palace.mine_content.assert_not_called()

    def test_global_dedup_rejects_existing(self, tmp_path):
        proj = _seed_project(tmp_path)
        skills_dir = proj / "skills"
        body = "quality_score: 80\nalpha beta gamma delta epsilon zeta eta theta"
        _write_skill(skills_dir, "existing_skill", body)

        # Le palace retourne un resultat similaire
        existing_entry = MagicMock()
        existing_entry.content = "alpha beta gamma delta epsilon zeta eta theta"
        palace = _make_palace(results=[existing_entry])

        contributor = ProjectContributor(palace_client=palace, min_quality_score=0)
        meta = _make_meta()
        result = contributor.contribute(meta, projects_dir=tmp_path)

        assert result.skipped_global == 1
        assert result.contributed_count == 0
        palace.mine_content.assert_not_called()

    def test_successful_contribution(self, tmp_path):
        proj = _seed_project(tmp_path)
        skills_dir = proj / "skills"
        _write_skill(skills_dir, "good_skill", "quality_score: 85\nContenu unique et pertinent")

        palace = _make_palace(results=[])  # aucun doublon global
        contributor = ProjectContributor(palace_client=palace, min_quality_score=0)
        meta = _make_meta()
        result = contributor.contribute(meta, projects_dir=tmp_path)

        assert result.scanned == 1
        assert result.contributed_count == 1
        assert len(result.contributed_ids) == 1
        palace.mine_content.assert_called_once()

    def test_stats_incremented_after_contribution(self, tmp_path):
        proj = _seed_project(tmp_path)
        skills_dir = proj / "skills"
        _write_skill(skills_dir, "skill_stat", "quality_score: 80\nContenu valide pour stats")

        palace = _make_palace(results=[])
        contributor = ProjectContributor(palace_client=palace, min_quality_score=0)
        meta = _make_meta()
        contributor.contribute(meta, projects_dir=tmp_path)

        pjson = proj / ".llca" / "project.json"
        data = json.loads(pjson.read_text(encoding="utf-8"))
        assert data["stats"]["skills_generated"] == 1

    def test_multiple_skills_mixed(self, tmp_path):
        """3 skills : 1 ok, 1 confidentielle, 1 qualite insuffisante."""
        proj = _seed_project(tmp_path)
        skills_dir = proj / "skills"
        _write_skill(skills_dir, "ok_skill",   "quality_score: 75\nContenu propre")
        _write_skill(skills_dir, "conf_skill",  f"quality_score: 90\n{_CONFIDENTIAL_MARKER}/path")
        _write_skill(skills_dir, "low_skill",   "quality_score: 20\nTrop bas")

        palace = _make_palace(results=[])
        contributor = ProjectContributor(palace_client=palace, min_quality_score=60)
        meta = _make_meta()
        result = contributor.contribute(meta, projects_dir=tmp_path)

        assert result.scanned == 3
        assert result.skipped_confidential == 1
        assert result.skipped_quality == 1
        assert result.contributed_count == 1

    def test_mine_content_called_with_correct_wing(self, tmp_path):
        """mine_content() doit cibler la collection 'project_global_skills'."""
        proj = _seed_project(tmp_path)
        skills_dir = proj / "skills"
        _write_skill(skills_dir, "wing_skill", "quality_score: 80\nSkill pour test wing")

        palace = _make_palace(results=[])
        contributor = ProjectContributor(palace_client=palace, min_quality_score=0)
        meta = _make_meta()
        contributor.contribute(meta, projects_dir=tmp_path)

        kwargs = palace.mine_content.call_args[1]
        assert kwargs["wing"] == "project_global_skills"

    def test_mine_content_metadata_contains_slug(self, tmp_path):
        proj = _seed_project(tmp_path, slug="mon-projet")
        skills_dir = proj / "skills"
        _write_skill(skills_dir, "meta_skill", "quality_score: 80\nVerification metadonnees")

        palace = _make_palace(results=[])
        contributor = ProjectContributor(palace_client=palace, min_quality_score=0)
        meta = _make_meta(slug="mon-projet")
        contributor.contribute(meta, projects_dir=tmp_path)

        kwargs = palace.mine_content.call_args[1]
        assert kwargs["metadata"]["project_slug"] == "mon-projet"

    def test_mine_content_error_captured_in_errors(self, tmp_path):
        """Si mine_content() leve, l'erreur est capturee dans result.errors."""
        proj = _seed_project(tmp_path)
        skills_dir = proj / "skills"
        _write_skill(skills_dir, "err_skill", "quality_score: 80\nSkill qui declenche erreur")

        palace = _make_palace(results=[])
        palace.mine_content.side_effect = RuntimeError("palace KO")

        contributor = ProjectContributor(palace_client=palace, min_quality_score=0)
        meta = _make_meta()
        result = contributor.contribute(meta, projects_dir=tmp_path)

        assert result.contributed_count == 0
        assert len(result.errors) == 1
        assert "err_skill" in result.errors[0]


# ===================================================================
# TestExtractQuality
# ===================================================================

class TestExtractQuality:
    def test_quality_score_prefix(self):
        body = "quality_score: 77\nContenu skill"
        assert ProjectContributor._extract_quality(body) == 77

    def test_score_prefix(self):
        body = "score: 55\nContenu skill"
        assert ProjectContributor._extract_quality(body) == 55

    def test_case_insensitive(self):
        body = "Quality_Score: 90\nContenu skill"
        assert ProjectContributor._extract_quality(body) == 90

    def test_missing_returns_zero(self):
        body = "Aucun frontmatter ici\nContenu quelconque"
        assert ProjectContributor._extract_quality(body) == 0

    def test_invalid_value_returns_zero(self):
        body = "quality_score: pas_un_int\nContenu skill"
        assert ProjectContributor._extract_quality(body) == 0

    def test_hash_prefix_stripped(self):
        """La ligne peut commencer par '#' (frontmatter Markdown)."""
        body = "# quality_score: 65\nContenu skill"
        assert ProjectContributor._extract_quality(body) == 65
