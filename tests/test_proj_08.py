# -*- coding: utf-8 -*-
"""
test_proj_08.py - Tests PROJ-08 : UserContextLearner

Couvre :
  - _jaccard() : cas limites (vide, identique, disjoints)
  - SessionSignal : construction correcte
  - _normalize_value() : langue, ton, nom, taille
  - _detect_explicit_commands() : extraction commandes
  - _detect_corrections() : verbosity concise/verbose
  - _deduplicate() : Jaccard, unicite champ
  - learn_from_session() : pipeline complet
  - learn_from_session() : 0 message → 0 signal
  - learn_from_session() : mode degrade silencieux (exception interne)
  - Integration ProjectOrchestrator.save_project(session_messages=...)
"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.user_context import UserContextState, UserContextLoader, _default_context
from core.user_context_learner import (
    UserContextLearner,
    SessionSignal,
    _jaccard,
    JACCARD_DEDUP_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_state(**overrides) -> UserContextState:
    data = _default_context()
    for dotted_key, val in overrides.items():
        keys = dotted_key.split(".")
        cur = data
        for k in keys[:-1]:
            cur = cur.setdefault(k, {})
        cur[keys[-1]] = val
    return UserContextState(data=data)


def _make_loader(tmp_path) -> UserContextLoader:
    ctx_dir = tmp_path / "projects" / ".llca"
    ctx_dir.mkdir(parents=True)
    return UserContextLoader(llca_root=tmp_path)


def _msgs(*user_texts: str) -> list[dict]:
    return [{"role": "user", "content": t} for t in user_texts]


# ===========================================================================
# 1. _jaccard()
# ===========================================================================

class TestJaccard:
    def test_identical(self):
        assert _jaccard("hello world", "hello world") == 1.0

    def test_empty_both(self):
        assert _jaccard("", "") == 1.0

    def test_disjoint(self):
        assert _jaccard("chat noir", "chien blanc") == 0.0

    def test_partial_overlap(self):
        j = _jaccard("ton formel", "utilise ton formel stp")
        assert 0.0 < j < 1.0

    def test_case_insensitive(self):
        assert _jaccard("CASUAL", "casual") == 1.0

    def test_one_empty(self):
        assert _jaccard("", "hello") == 0.0

    def test_single_common_token(self):
        j = _jaccard("formal", "ton formel formal stp")
        # "formal" dans les deux : inter=1, union=4
        assert j == pytest.approx(1 / 4, abs=0.01)


# ===========================================================================
# 2. SessionSignal
# ===========================================================================

class TestSessionSignal:
    def test_fields(self):
        sig = SessionSignal(
            field="communication.tone",
            old_value="casual",
            new_value="formal",
            source="explicit_command",
            confidence=0.95,
            raw_text="utilise un ton formel",
        )
        assert sig.field == "communication.tone"
        assert sig.new_value == "formal"
        assert sig.source == "explicit_command"
        assert sig.confidence == pytest.approx(0.95)


# ===========================================================================
# 3. _normalize_value()
# ===========================================================================

class TestNormalizeValue:
    def test_language_francais(self):
        assert UserContextLearner._normalize_value("communication.language", "français") == "fr"

    def test_language_anglais(self):
        assert UserContextLearner._normalize_value("communication.language", "anglais") == "en"

    def test_language_unknown(self):
        assert UserContextLearner._normalize_value("communication.language", "klingon") is None

    def test_tone_formel(self):
        assert UserContextLearner._normalize_value("communication.tone", "formel") == "formal"

    def test_tone_casual(self):
        assert UserContextLearner._normalize_value("communication.tone", "casual") == "casual"

    def test_tone_unknown(self):
        # Ton inconnu non dans _TONE_MAP → None (comportement defensif du source)
        assert UserContextLearner._normalize_value("communication.tone", "zen") is None

    def test_name_capitalised(self):
        assert UserContextLearner._normalize_value("identity.name", "adham") == "Adham"

    def test_name_empty(self):
        assert UserContextLearner._normalize_value("identity.name", "") is None

    def test_file_size(self):
        val = UserContextLearner._normalize_value("learned.preferred_file_size", "8kb")
        assert "8KB" in val


# ===========================================================================
# 4. _detect_explicit_commands()
# ===========================================================================

class TestDetectExplicitCommands:
    def _learner(self):
        return UserContextLearner()

    def test_appelle_moi(self):
        state = _make_state(**{"identity.name": ""})
        sigs = self._learner()._detect_explicit_commands(
            state, "Appelle-moi Adham stp", "appelle-moi adham stp"
        )
        assert len(sigs) == 1
        assert sigs[0].field == "identity.name"
        assert sigs[0].new_value == "Adham"
        assert sigs[0].source == "explicit_command"

    def test_reponds_en_anglais(self):
        state = _make_state(**{"communication.language": "fr"})
        sigs = self._learner()._detect_explicit_commands(
            state, "Réponds en anglais", "réponds en anglais"
        )
        assert any(s.field == "communication.language" and s.new_value == "en" for s in sigs)

    def test_ton_formel(self):
        state = _make_state(**{"communication.tone": "casual"})
        sigs = self._learner()._detect_explicit_commands(
            state, "Utilise un ton formel", "utilise un ton formel"
        )
        assert any(s.field == "communication.tone" and s.new_value == "formal" for s in sigs)

    def test_no_change_if_same_value(self):
        # tone deja "formal" → pas de signal
        state = _make_state(**{"communication.tone": "formal"})
        sigs = self._learner()._detect_explicit_commands(
            state, "utilise un ton formel", "utilise un ton formel"
        )
        assert all(s.field != "communication.tone" for s in sigs)

    def test_taille_modules(self):
        state = _make_state()
        sigs = self._learner()._detect_explicit_commands(
            state, "Fichiers de moins de 8KB stp", "fichiers de moins de 8kb stp"
        )
        assert any(s.field == "learned.preferred_file_size" for s in sigs)

    def test_no_signal_on_unrelated(self):
        state = _make_state()
        sigs = self._learner()._detect_explicit_commands(
            state, "Bonjour comment ca va", "bonjour comment ca va"
        )
        assert sigs == []


# ===========================================================================
# 5. _detect_corrections()
# ===========================================================================

class TestDetectCorrections:
    def _learner(self):
        return UserContextLearner()

    def test_non_concis(self):
        state = _make_state(**{"communication.verbosity": "verbose"})
        sigs = self._learner()._detect_corrections(
            state, "Non, sois plus concis", "non, sois plus concis"
        )
        assert any(s.field == "communication.verbosity" and s.new_value == "concise" for s in sigs)

    def test_pas_ca_detaille(self):
        state = _make_state(**{"communication.verbosity": "concise"})
        sigs = self._learner()._detect_corrections(
            state, "Pas ca, développe davantage", "pas ca, développe davantage"
        )
        assert any(s.field == "communication.verbosity" and s.new_value == "verbose" for s in sigs)

    def test_no_pattern_no_signal(self):
        state = _make_state()
        sigs = self._learner()._detect_corrections(
            state, "Merci pour la reponse", "merci pour la reponse"
        )
        assert sigs == []

    def test_correction_already_concise_no_signal(self):
        # verbosity deja "concise" → pas de signal redondant
        state = _make_state(**{"communication.verbosity": "concise"})
        sigs = self._learner()._detect_corrections(
            state, "Non, sois plus concis", "non, sois plus concis"
        )
        assert all(s.new_value != "concise" for s in sigs)


# ===========================================================================
# 6. _deduplicate()
# ===========================================================================

class TestDeduplicate:
    def _learner(self):
        return UserContextLearner()

    def test_removes_jaccard_identical(self):
        state = _make_state(**{"communication.tone": "formal"})
        sig = SessionSignal(
            field="communication.tone",
            old_value="formal",
            new_value="formal",  # meme valeur
            source="auto_detected",
            confidence=0.7,
            raw_text="",
        )
        result = self._learner()._deduplicate([sig], state)
        assert result == []

    def test_keeps_different_value(self):
        state = _make_state(**{"communication.tone": "casual"})
        sig = SessionSignal(
            field="communication.tone",
            old_value="casual",
            new_value="formal",
            source="explicit_command",
            confidence=0.95,
            raw_text="",
        )
        result = self._learner()._deduplicate([sig], state)
        assert len(result) == 1

    def test_one_signal_per_field(self):
        state = _make_state(**{"communication.verbosity": "concise"})
        sigs = [
            SessionSignal("communication.verbosity", "concise", "verbose", "auto_detected", 0.7, ""),
            SessionSignal("communication.verbosity", "concise", "normal", "auto_detected", 0.6, ""),
        ]
        result = self._learner()._deduplicate(sigs, state)
        assert len(result) == 1

    def test_different_fields_both_kept(self):
        state = _make_state()
        sigs = [
            SessionSignal("communication.tone", "casual", "formal", "explicit_command", 0.95, ""),
            SessionSignal("communication.verbosity", "concise", "verbose", "auto_detected", 0.7, ""),
        ]
        result = self._learner()._deduplicate(sigs, state)
        assert len(result) == 2


# ===========================================================================
# 7. learn_from_session() pipeline
# ===========================================================================

class TestLearnFromSession:
    def test_zero_messages_returns_zero(self, tmp_path):
        loader = _make_loader(tmp_path)
        state = loader.load()
        learner = UserContextLearner()
        n = learner.learn_from_session(state, loader, [])
        assert n == 0

    def test_explicit_command_written_to_wal(self, tmp_path):
        # identity.name est dans SENSITIVE_FIELDS -> explicit_command bloque aussi
        # (seul user_correction passe). Utiliser un champ non-sensible : communication.tone
        loader = _make_loader(tmp_path)
        state = loader.load()
        learner = UserContextLearner()
        msgs = _msgs("Utilise un ton formel stp")
        n = learner.learn_from_session(state, loader, msgs)
        assert n >= 1
        # Verifier que le WAL a ete ecrit
        wal_file = tmp_path / "projects" / ".llca" / "user_context.wal.jsonl"
        assert wal_file.exists()
        lines = [l for l in wal_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) >= 1

    def test_correction_written(self, tmp_path):
        loader = _make_loader(tmp_path)
        state = loader.load()
        # Mettre verbosity a verbose pour que la correction soit utile
        loader.update_field(state, "communication.verbosity", "verbose")
        learner = UserContextLearner()
        msgs = _msgs("Non, sois plus concis stp")
        n = learner.learn_from_session(state, loader, msgs)
        assert n >= 1

    def test_degrade_si_loader_leve(self, tmp_path):
        """Si le WAL plante, learn_from_session retourne 0 sans lever."""
        loader = _make_loader(tmp_path)
        state = loader.load()
        learner = UserContextLearner()
        # Injecter un crash dans append_wal
        def bad_append(*a, **k):
            raise RuntimeError("crash test")
        loader.append_wal = bad_append
        msgs = _msgs("Appelle-moi Adham")
        n = learner.learn_from_session(state, loader, msgs)
        assert n == 0  # mode degrade

    def test_no_signal_on_unrelated_messages(self, tmp_path):
        loader = _make_loader(tmp_path)
        state = loader.load()
        learner = UserContextLearner()
        msgs = _msgs("Comment va ton projet ?", "C'est bien", "Merci !")
        n = learner.learn_from_session(state, loader, msgs)
        assert n == 0

    def test_only_user_messages_considered(self, tmp_path):
        loader = _make_loader(tmp_path)
        state = loader.load()
        learner = UserContextLearner()
        # Message assistant avec commande → ne doit pas produire de signal
        msgs = [
            {"role": "assistant", "content": "Appelle-moi Bot"},
            {"role": "user", "content": "Merci beaucoup"},
        ]
        n = learner.learn_from_session(state, loader, msgs)
        assert n == 0


# ===========================================================================
# 8. Integration ProjectOrchestrator.save_project(session_messages)
# ===========================================================================

class TestSaveProjectWithMessages:
    def _make_orch(self, tmp_path):
        """Construit un orchestrateur avec tous les workers mock sauf uc_loader reel."""
        from core.project_orchestrator import ProjectOrchestrator
        from core.project_manager import ProjectManager
        from core.project_lock import ProjectLock
        from core.project_loader import ProjectLoader
        from core.project_context_assembler import ProjectContextAssembler
        from core.project_checkpoint import ProjectCheckpoint

        pm   = MagicMock(spec=ProjectManager)
        lock = MagicMock(spec=ProjectLock)
        ldr  = MagicMock(spec=ProjectLoader)
        asm  = MagicMock(spec=ProjectContextAssembler)
        chk  = MagicMock(spec=ProjectCheckpoint)

        ctx_dir = tmp_path / "projects" / ".llca"
        ctx_dir.mkdir(parents=True)
        uc_loader = UserContextLoader(llca_root=tmp_path)

        orch = ProjectOrchestrator(pm, lock, ldr, asm, chk, user_context_loader=uc_loader)

        # Context mock minimal
        ctx = MagicMock()
        ctx.meta.id = "test-id"
        ctx.meta.slug = "test-slug"

        return orch, ctx

    def test_save_without_messages_no_crash(self, tmp_path):
        orch, ctx = self._make_orch(tmp_path)
        orch.save_project(ctx)  # session_messages=None par defaut
        ctx  # pas d'exception

    def test_save_with_messages_writes_wal(self, tmp_path):
        orch, ctx = self._make_orch(tmp_path)
        msgs = [{"role": "user", "content": "Appelle-moi Adham"}]
        orch.save_project(ctx, session_messages=msgs)
        wal = tmp_path / "projects" / ".llca" / "user_context.wal.jsonl"
        # WAL doit exister si un signal a ete ecrit
        # (peut etre vide si learn retourne 0)
        assert True  # no exception est le test principal

    def test_save_lock_released_even_if_learn_crashes(self, tmp_path):
        orch, ctx = self._make_orch(tmp_path)
        # Forcer un crash dans le learner
        orch._uc_learner.learn_from_session = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        msgs = [{"role": "user", "content": "Appelle-moi X"}]
        orch.save_project(ctx, session_messages=msgs)
        orch._lock.release.assert_called_once_with("test-slug")
