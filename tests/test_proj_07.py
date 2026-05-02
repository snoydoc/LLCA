# -*- coding: utf-8 -*-
"""
test_proj_07.py - Tests PROJ-07 : UserContextInjector

Couvre :
  - build(None) → ""
  - build(state vide) → "" ou bloc minimal
  - bloc contient identite + communication
  - bloc contient aliases
  - bloc contient learned (FIFO budget)
  - bloc ne depasse pas MAX_INJECT_CHARS
  - inject_into_context() peuple context.user_prefix
  - inject_into_context() sur objet sans user_prefix : pas d'exception
  - budget FIFO : learned tronque si trop long
  - bloc commence et se termine par les delimiteurs corrects
"""
import pytest
from unittest.mock import MagicMock

from core.user_context import UserContextState, _default_context
from core.user_context_injector import (
    UserContextInjector,
    MAX_INJECT_CHARS,
    MAX_INJECT_TOKENS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(**overrides) -> UserContextState:
    """Cree un UserContextState avec des overrides sur data."""
    data = _default_context()
    for dotted_key, val in overrides.items():
        keys = dotted_key.split(".")
        cur = data
        for k in keys[:-1]:
            cur = cur.setdefault(k, {})
        cur[keys[-1]] = val
    return UserContextState(data=data)


# ===========================================================================
# 1. build(None) / build(empty)
# ===========================================================================

class TestBuildNone:
    def test_none_returns_empty(self):
        inj = UserContextInjector()
        assert inj.build(None) == ""

    def test_all_empty_fields_no_crash(self):
        state = UserContextState(data=_default_context())
        inj = UserContextInjector()
        result = inj.build(state)
        # name vide → pas de ligne identite avec nom
        # le bloc peut quand meme contenir des lignes comm
        assert isinstance(result, str)


# ===========================================================================
# 2. Contenu du bloc
# ===========================================================================

class TestBuildContent:
    def test_contains_name_when_set(self):
        state = _make_state(**{"identity.name": "Adham"})
        result = UserContextInjector().build(state)
        assert "Adham" in result

    def test_contains_tone(self):
        state = _make_state(**{"communication.tone": "formal"})
        result = UserContextInjector().build(state)
        assert "formal" in result

    def test_contains_locale(self):
        state = _make_state(**{"identity.locale": "fr-MA"})
        result = UserContextInjector().build(state)
        assert "fr-MA" in result

    def test_contains_aliases(self):
        state = _make_state(**{"shortcuts.aliases": {"ms": "make spec", "rt": "run tests"}})
        result = UserContextInjector().build(state)
        assert "ms" in result
        assert "rt" in result

    def test_contains_learned_coding_style(self):
        state = _make_state(**{"learned.coding_style": ["snake_case strict", "libcst AST"]})
        result = UserContextInjector().build(state)
        assert "snake_case" in result

    def test_emoji_non_label(self):
        state = _make_state(**{"communication.prefers_emoji": False})
        result = UserContextInjector().build(state)
        assert "non" in result

    def test_emoji_oui_label(self):
        state = _make_state(**{"communication.prefers_emoji": True})
        result = UserContextInjector().build(state)
        assert "oui" in result


# ===========================================================================
# 3. Delimiteurs
# ===========================================================================

class TestDelimiters:
    def test_starts_with_user_context_header(self):
        state = _make_state(**{"identity.name": "Adham"})
        result = UserContextInjector().build(state)
        assert result.startswith("[USER CONTEXT")

    def test_ends_with_closing_tag(self):
        state = _make_state(**{"identity.name": "Adham"})
        result = UserContextInjector().build(state)
        assert result.endswith("[/USER CONTEXT]")

    def test_mentions_token_limit(self):
        state = _make_state(**{"identity.name": "Adham"})
        result = UserContextInjector().build(state)
        assert str(MAX_INJECT_TOKENS) in result


# ===========================================================================
# 4. Budget FIFO
# ===========================================================================

class TestBudget:
    def test_bloc_under_max_chars(self):
        # Contexte avec beaucoup de learned items
        long_items = [f"style_rule_{i}_" + "x" * 50 for i in range(50)]
        state = _make_state(**{"learned.coding_style": long_items})
        result = UserContextInjector().build(state)
        assert len(result) <= MAX_INJECT_CHARS + 200  # marge delimiteurs

    def test_extreme_learned_does_not_crash(self):
        massive = ["x" * 200 for _ in range(200)]
        state = _make_state(**{
            "identity.name": "Adham",
            "learned.coding_style": massive,
        })
        result = UserContextInjector().build(state)
        assert isinstance(result, str)
        assert len(result) > 0


# ===========================================================================
# 5. inject_into_context()
# ===========================================================================

class TestInjectIntoContext:
    def test_populates_user_prefix(self):
        state = _make_state(**{"identity.name": "Adham"})
        ctx = MagicMock()
        ctx.user_prefix = ""
        UserContextInjector().inject_into_context(ctx, state)
        assert "Adham" in ctx.user_prefix

    def test_inject_none_state_sets_empty(self):
        ctx = MagicMock()
        ctx.user_prefix = "old"
        UserContextInjector().inject_into_context(ctx, None)
        assert ctx.user_prefix == ""

    def test_inject_on_object_without_attribute_no_crash(self):
        # Un objet sans user_prefix ne doit pas lever
        class NoPrefix:
            pass
        inj = UserContextInjector()
        state = _make_state(**{"identity.name": "Test"})
        # Ne pas utiliser MagicMock ici — on veut un vrai objet sans l'attribut
        # Mais setattr marche sur les objets custom → on bloque via __slots__
        class Slotted:
            __slots__ = ("other",)
        obj = Slotted()
        obj.other = 1
        # Doit logger warning et ne pas lever d'exception
        inj.inject_into_context(obj, state)

    def test_full_pipeline(self):
        """Smoke test : load → build → inject."""
        from core.user_context import UserContextLoader
        import tempfile, json
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ctx_dir = root / "projects" / ".llca"
            ctx_dir.mkdir(parents=True)
            # Ecrire un user_context.json minimal
            data = _default_context()
            data["identity"]["name"] = "Adham"
            (ctx_dir / "user_context.json").write_text(json.dumps(data), encoding="utf-8")

            loader = UserContextLoader(llca_root=root)
            state = loader.load()
            inj = UserContextInjector()
            prefix = inj.build(state)

            assert "Adham" in prefix
            assert prefix.startswith("[USER CONTEXT")
