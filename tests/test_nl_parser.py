# -*- coding: utf-8-sig -*-
"""
test_nl_parser.py — LCCA V5 Fusion
Sprint 10 — TASK-10-04

Tests unitaires pour NLParser, NLIntentExtractor, NLPromptBuilder.
Tous les tests sont mockés : Ollama n'est PAS requis.

Couverture :
    - NLIntent.is_actionable()
    - NLIntent.to_dsl()
    - NLIntentExtractor.extract() — JSON propre
    - NLIntentExtractor.extract() — JSON dans markdown fence
    - NLIntentExtractor.extract() — JSON avec accolades parasites
    - NLIntentExtractor.extract() — Texte invalide → fallback heuristique
    - NLIntentExtractor._heuristic_fallback() — 5 types d'actions
    - NLPromptBuilder.build() — sans fichiers connus
    - NLPromptBuilder.build() — avec fichiers connus
    - NLParser.parse() — Ollama mocké, réponse JSON valide
    - NLParser.parse() — Ollama mocké, réponse invalide → fallback
    - NLParser.parse() — Ollama inaccessible → fallback
    - NLParser.parse() — commande vide
    - NLParser.is_available() — Ollama disponible (mocké)
    - NLParser.is_available() — Ollama indisponible (mocké)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from core.nl_parser import (
    NLIntent,
    NLIntentExtractor,
    NLParser,
    NLPromptBuilder,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def extractor() -> NLIntentExtractor:
    return NLIntentExtractor()


@pytest.fixture
def prompt_builder() -> NLPromptBuilder:
    return NLPromptBuilder()


@pytest.fixture
def parser() -> NLParser:
    """NLParser configuré sur un Ollama fictif."""
    return NLParser(
        ollama_url="http://localhost:11434",
        model="qwen2.5-coder:14b",
        timeout=5,
        max_tokens=256,
    )


def _make_ollama_response(json_dict: dict) -> str:
    """Simule la réponse brute d'Ollama (/api/chat)."""
    return json.dumps({"message": {"content": json.dumps(json_dict)}})


# ──────────────────────────────────────────────────────────────────────────────
# Tests NLIntent
# ──────────────────────────────────────────────────────────────────────────────

class TestNLIntent:

    def test_is_actionable_true(self):
        intent = NLIntent(
            action="add_function",
            description="Valide un numéro de téléphone",
            raw_command="Ajoute validate_phone",
            confidence=0.9,
        )
        assert intent.is_actionable() is True

    def test_is_actionable_false_unknown(self):
        intent = NLIntent(
            action="unknown",
            description="Je ne sais pas",
            raw_command="???",
            confidence=0.9,
        )
        assert intent.is_actionable() is False

    def test_is_actionable_false_low_confidence(self):
        intent = NLIntent(
            action="add_function",
            description="Ajoute quelque chose",
            raw_command="ajoute quelque chose",
            confidence=0.3,
        )
        assert intent.is_actionable() is False

    def test_is_actionable_false_empty_description(self):
        intent = NLIntent(
            action="add_function",
            description="   ",
            raw_command="...",
            confidence=0.9,
        )
        assert intent.is_actionable() is False

    def test_to_dsl_with_file_and_symbol(self):
        intent = NLIntent(
            action="add_function",
            description="Gère les salutations",
            raw_command="Ajoute handle_greeting",
            target_file="core/conversation.py",
            symbol="handle_greeting",
            confidence=0.95,
        )
        dsl = intent.to_dsl()
        assert "LCCA" in dsl
        assert "conversation" in dsl
        assert "handle_greeting" in dsl
        assert "Ajoute" in dsl

    def test_to_dsl_without_file(self):
        intent = NLIntent(
            action="create_file",
            description="Nouveau module de validation",
            raw_command="Crée un fichier de validation",
            target_file=None,
            confidence=0.8,
        )
        dsl = intent.to_dsl()
        assert "LCCA" in dsl
        assert "unknown" in dsl

    def test_to_dsl_windows_path(self):
        intent = NLIntent(
            action="modify_function",
            description="Corrige le timeout",
            raw_command="Corrige handle_timeout",
            target_file="core\\handlers.py",  # Chemin Windows avec backslash
            symbol="handle_timeout",
            confidence=0.9,
        )
        dsl = intent.to_dsl()
        assert "handlers" in dsl


# ──────────────────────────────────────────────────────────────────────────────
# Tests NLIntentExtractor
# ──────────────────────────────────────────────────────────────────────────────

class TestNLIntentExtractor:

    def test_extract_clean_json(self, extractor):
        """JSON propre retourné directement par le LLM."""
        raw = json.dumps({
            "action": "add_function",
            "target_file": "core/utils.py",
            "symbol": "validate_phone",
            "description": "Valide un numéro de téléphone marocain",
            "create_if_missing": False,
            "confidence": 0.95,
        })
        intent = extractor.extract(raw, "Ajoute validate_phone dans utils.py")
        assert intent.action == "add_function"
        assert intent.target_file == "core/utils.py"
        assert intent.symbol == "validate_phone"
        assert intent.confidence == pytest.approx(0.95)
        assert intent.from_fallback is False

    def test_extract_json_in_markdown_fence(self, extractor):
        """JSON entouré de balises ```json ... ``` (cas courant avec Qwen)."""
        data = {
            "action": "modify_function",
            "target_file": "core/session.py",
            "symbol": "handle_timeout",
            "description": "Corrige le crash quand session est None",
            "create_if_missing": False,
            "confidence": 0.88,
        }
        raw = f"```json\n{json.dumps(data)}\n```"
        intent = extractor.extract(raw, "Corrige handle_timeout")
        assert intent.action == "modify_function"
        assert intent.symbol == "handle_timeout"
        assert intent.from_fallback is False

    def test_extract_json_with_surrounding_text(self, extractor):
        """JSON précédé de texte parasite (modèle bavard)."""
        data = {
            "action": "create_file",
            "target_file": "utils/validators.py",
            "symbol": None,
            "description": "Module de validation",
            "create_if_missing": True,
            "confidence": 0.9,
        }
        raw = f"Here is the parsed intent:\n{json.dumps(data)}\nI hope this helps!"
        intent = extractor.extract(raw, "Crée utils/validators.py")
        assert intent.action == "create_file"
        assert intent.create_if_missing is True
        assert intent.from_fallback is False

    def test_extract_invalid_json_triggers_fallback(self, extractor):
        """Texte non-JSON → fallback heuristique."""
        raw = "I cannot parse this command. Please rephrase."
        intent = extractor.extract(raw, "Ajoute une fonction de validation")
        assert intent.from_fallback is True
        assert intent.action == "add_function"  # Heuristique détecte "Ajoute"
        assert intent.confidence <= 0.3

    def test_extract_unknown_action_normalized(self, extractor):
        """Action non reconnue → normalisée en 'unknown'."""
        raw = json.dumps({
            "action": "teleport_function",  # Action invalide
            "target_file": None,
            "symbol": None,
            "description": "Téléporter une fonction",
            "create_if_missing": False,
            "confidence": 0.5,
        })
        intent = extractor.extract(raw, "teleporte la fonction")
        assert intent.action == "unknown"

    def test_extract_confidence_clamped(self, extractor):
        """La confidence doit être clampée entre 0.0 et 1.0."""
        raw = json.dumps({
            "action": "add_function",
            "target_file": None,
            "symbol": "foo",
            "description": "test",
            "create_if_missing": False,
            "confidence": 99.9,  # Hors limites
        })
        intent = extractor.extract(raw, "ajoute foo")
        assert intent.confidence == pytest.approx(1.0)


# ──────────────────────────────────────────────────────────────────────────────
# Tests NLIntentExtractor — fallback heuristique
# ──────────────────────────────────────────────────────────────────────────────

class TestHeuristicFallback:

    @pytest.mark.parametrize("command,expected_action", [
        ("Ajoute une fonction validate_email dans core/utils.py", "add_function"),
        ("add a new function handle_error",                       "add_function"),
        ("Modifie la fonction parse_message",                     "modify_function"),
        ("Corrige le bug dans handle_timeout",                    "modify_function"),
        ("fix the crash in session manager",                      "modify_function"),
        ("Crée un nouveau fichier utils/helpers.py",              "create_file"),
        ("create file core/validators.py",                        "create_file"),
        ("Montre-moi le contenu de config.py",                    "read_file"),
        ("show the content of main.py",                           "read_file"),
        ("Fais quelque chose de magique",                         "unknown"),
    ])
    def test_heuristic_actions(self, command, expected_action):
        extractor = NLIntentExtractor()
        intent = extractor._heuristic_fallback(command)
        assert intent.action == expected_action
        assert intent.from_fallback is True
        assert intent.confidence <= 0.3

    def test_heuristic_detects_file_path(self):
        extractor = NLIntentExtractor()
        intent = extractor._heuristic_fallback("Ajoute validate dans core/utils.py")
        assert intent.target_file == "core/utils.py"

    def test_heuristic_detects_function_name(self):
        extractor = NLIntentExtractor()
        intent = extractor._heuristic_fallback("Modifie la fonction handle_timeout")
        assert intent.symbol == "handle_timeout"


# ──────────────────────────────────────────────────────────────────────────────
# Tests NLPromptBuilder
# ──────────────────────────────────────────────────────────────────────────────

class TestNLPromptBuilder:

    def test_build_returns_two_strings(self, prompt_builder):
        system, user = prompt_builder.build("Ajoute validate_phone dans utils.py")
        assert isinstance(system, str) and len(system) > 0
        assert isinstance(user, str) and len(user) > 0

    def test_build_contains_command(self, prompt_builder):
        cmd = "Crée un module de gestion des sessions"
        _, user = prompt_builder.build(cmd)
        assert cmd in user

    def test_build_system_contains_json_schema(self, prompt_builder):
        system, _ = prompt_builder.build("test")
        assert "action" in system
        assert "confidence" in system
        assert "target_file" in system

    def test_build_with_project_files_included(self, prompt_builder):
        files = ["core/conversation.py", "core/session.py", "utils/helpers.py"]
        _, user = prompt_builder.build("Ajoute handle_greeting", project_files=files)
        assert "core/conversation.py" in user
        assert "core/session.py" in user

    def test_build_project_files_truncated_to_20(self, prompt_builder):
        """Vérifie que la liste de fichiers est tronquée à 20."""
        files = [f"module_{i}.py" for i in range(50)]
        _, user = prompt_builder.build("test", project_files=files)
        # Seuls les 20 premiers doivent apparaître
        assert "module_0.py" in user
        assert "module_19.py" in user
        assert "module_20.py" not in user


# ──────────────────────────────────────────────────────────────────────────────
# Tests NLParser (avec mock Ollama)
# ──────────────────────────────────────────────────────────────────────────────

class TestNLParser:

    def _mock_urlopen(self, response_json_str: str):
        """Crée un mock d'urllib.request.urlopen retournant une réponse Ollama."""
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = response_json_str.encode("utf-8")
        mock_resp.status = 200
        return mock_resp

    def test_parse_valid_ollama_response(self, parser):
        """Ollama répond avec un JSON valide → NLIntent correct."""
        intent_data = {
            "action": "add_function",
            "target_file": "core/utils.py",
            "symbol": "validate_phone",
            "description": "Valide un numéro de téléphone marocain",
            "create_if_missing": False,
            "confidence": 0.95,
        }
        ollama_body = json.dumps({"message": {"content": json.dumps(intent_data)}})

        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value = self._mock_urlopen(ollama_body)
            intent = parser.parse("Ajoute validate_phone dans core/utils.py")

        assert intent.action == "add_function"
        assert intent.target_file == "core/utils.py"
        assert intent.symbol == "validate_phone"
        assert intent.from_fallback is False

    def test_parse_invalid_ollama_response_triggers_fallback(self, parser):
        """Ollama répond avec du texte invalide → fallback heuristique."""
        ollama_body = json.dumps({"message": {"content": "Sorry, I cannot help with that."}})

        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value = self._mock_urlopen(ollama_body)
            intent = parser.parse("Ajoute une nouvelle fonction")

        assert intent.from_fallback is True
        assert intent.action == "add_function"  # Heuristique détecte "Ajoute"

    def test_parse_ollama_unreachable_triggers_fallback(self, parser):
        """Ollama inaccessible → fallback heuristique (pas d'exception levée)."""
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            intent = parser.parse("Ajoute validate_phone")

        assert intent.from_fallback is True
        assert intent.action == "add_function"

    def test_parse_empty_command(self, parser):
        """Commande vide → NLIntent unknown sans appel Ollama."""
        with patch("urllib.request.urlopen") as mock_open:
            intent = parser.parse("   ")
            mock_open.assert_not_called()  # Pas d'appel réseau si commande vide

        assert intent.action == "unknown"
        assert intent.confidence == 0.0
        assert intent.from_fallback is True

    def test_parse_with_project_files(self, parser):
        """Vérifie que project_files est bien transmis au prompt."""
        intent_data = {
            "action": "read_file",
            "target_file": "core/conversation.py",
            "symbol": None,
            "description": "Lire le fichier conversation",
            "create_if_missing": False,
            "confidence": 0.85,
        }
        ollama_body = json.dumps({"message": {"content": json.dumps(intent_data)}})
        files = ["core/conversation.py", "core/session.py"]

        with patch("urllib.request.urlopen") as mock_open:
            mock_open.return_value = self._mock_urlopen(ollama_body)
            intent = parser.parse("Montre conversation.py", project_files=files)

        assert intent.action == "read_file"
        assert intent.target_file == "core/conversation.py"

    def test_is_available_true(self, parser):
        """Ollama accessible → True."""
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200

        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert parser.is_available() is True

    def test_is_available_false(self, parser):
        """Ollama inaccessible → False (pas d'exception)."""
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            assert parser.is_available() is False


# ---------------------------------------------------------------------------
# Tests patterns Educator ED-04 (NlIntent enum)
# ---------------------------------------------------------------------------

class TestNlEducatorPatterns:

    def test_educator_run_fr(self):
        """'lance la curation' -> NlIntent.EDUCATOR_RUN."""
        from core.nl_parser import parse_nl_intent, NlIntent
        intent, _ = parse_nl_intent("lance la curation")
        assert intent == NlIntent.EDUCATOR_RUN

    def test_educator_run_en(self):
        """'start educator' -> NlIntent.EDUCATOR_RUN."""
        from core.nl_parser import parse_nl_intent, NlIntent
        intent, _ = parse_nl_intent("start educator")
        assert intent == NlIntent.EDUCATOR_RUN

    def test_educator_diff(self):
        """'diff curation' -> NlIntent.EDUCATOR_DIFF."""
        from core.nl_parser import parse_nl_intent, NlIntent
        intent, _ = parse_nl_intent("diff curation")
        assert intent == NlIntent.EDUCATOR_DIFF

    def test_no_match_returns_none(self):
        """Commande non-educator -> (None, {})."""
        from core.nl_parser import parse_nl_intent
        intent, params = parse_nl_intent("Ajoute une fonction foo")
        assert intent is None
        assert params == {}
