# -*- coding: utf-8-sig -*-
"""
nl_intent_builder.py — NLPromptBuilder + NLIntentExtractor (Sprint REFACTO-01).

Extrait de nl_parser.py pour réduire sa taille de 20.2 KB à < 8 KB.

Rétrocompatibilité : NLPromptBuilder et NLIntentExtractor sont ré-exportés
depuis nl_parser.py, donc les imports existants continuent de fonctionner.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from core.nl_intent import NLIntent, VALID_ACTIONS

log = logging.getLogger("lcca.nl_intent_builder")


# ──────────────────────────────────────────────────────────────────────────────
# NLPromptBuilder
# ──────────────────────────────────────────────────────────────────────────────

class NLPromptBuilder:
    """
    Construit le prompt envoyé à Qwen2.5-Coder pour analyser une commande NL.

    Le modèle doit retourner UNIQUEMENT un JSON valide,
    sans texte avant ni après, sans balises markdown.
    """

    _SYSTEM = """\
You are a code intent analyzer. Your job is to parse natural language coding commands
and return a structured JSON intent.

You MUST respond with ONLY a valid JSON object. No explanations. No markdown. No text before or after.

The JSON must follow this exact schema:
{
  "action": "<add_function|modify_function|create_file|read_file|delete_function|unknown>",
  "target_file": "<relative path like core/conversation.py, or null if unknown>",
  "symbol": "<function or class name, or null if not applicable>",
  "description": "<clear description of what needs to be done, in the same language as the input>",
  "create_if_missing": <true if file should be created, false otherwise>,
  "confidence": <float 0.0 to 1.0>
}

Rules:
- If the user says "add", "ajoute", "crée une fonction" → action = "add_function"
- If the user says "modifie", "corrige", "change", "fix" → action = "modify_function"
- If the user says "crée un fichier", "nouveau module" → action = "create_file", create_if_missing = true
- If the user says "montre", "affiche", "lis" → action = "read_file"
- If no file is mentioned → target_file = null
- confidence = 1.0 if everything is clear, lower if ambiguous
"""

    def build(self, command: str, project_files: list[str] | None = None) -> tuple[str, str]:
        """
        Construit (system_prompt, user_prompt) pour l'analyse NL.

        Args:
            command       : Commande en langage naturel de l'utilisateur.
            project_files : Liste des fichiers connus du projet.

        Returns:
            (system, user) tuple de prompts.
        """
        ctx = ""
        if project_files:
            files_sample = project_files[:20]
            ctx = f"\n\nKnown project files:\n" + "\n".join(f"  - {f}" for f in files_sample)

        user = f"Parse this coding command:{ctx}\n\nCommand: {command}"
        return self._SYSTEM, user


# ──────────────────────────────────────────────────────────────────────────────
# NLIntentExtractor
# ──────────────────────────────────────────────────────────────────────────────

class NLIntentExtractor:
    """
    Extrait et valide un NLIntent depuis la réponse brute du LLM.

    Gère les cas où le LLM :
    - Retourne du JSON propre ✅
    - Entoure le JSON de markdown fences ⚠️ (on nettoie)
    - Retourne du texte invalide ❌ (on fait un fallback heuristique)
    """

    _FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)

    _VALID_ACTIONS = set(VALID_ACTIONS)

    def extract(self, raw: str, original_command: str) -> NLIntent:
        """
        Parse la réponse brute du LLM en NLIntent.

        Args:
            raw              : Réponse brute d'Ollama.
            original_command : Commande originale (pour fallback et traçabilité).

        Returns:
            NLIntent (from_fallback=True si le parsing a échoué).
        """
        cleaned = self._clean_response(raw)

        try:
            data = json.loads(cleaned)
            return self._build_intent(data, original_command)
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning("JSON parsing échoué (%s) — fallback heuristique sur: %r", exc, raw[:100])
            return self._heuristic_fallback(original_command)

    def _clean_response(self, raw: str) -> str:
        raw = raw.strip()
        matches = self._FENCE_RE.findall(raw)
        if matches:
            return matches[0].strip()
        start = raw.find("{")
        end   = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            return raw[start:end + 1]
        return raw

    def _build_intent(self, data: dict, original_command: str) -> NLIntent:
        action = data.get("action", "unknown")
        if action not in self._VALID_ACTIONS:
            log.warning("Action inconnue '%s' → 'unknown'", action)
            action = "unknown"

        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        return NLIntent(
            action            = action,
            target_file       = data.get("target_file") or None,
            symbol            = data.get("symbol") or None,
            description       = str(data.get("description", original_command)),
            create_if_missing = bool(data.get("create_if_missing", False)),
            confidence        = confidence,
            raw_command       = original_command,
            from_fallback     = False,
        )

    def _heuristic_fallback(self, command: str) -> NLIntent:
        """
        Construit un NLIntent à la règle depuis la commande brute.
        Utilisé si Ollama est indisponible ou si le JSON est invalide.
        """
        cmd_lower = command.lower()

        if any(kw in cmd_lower for kw in ("ajoute", "add ", "ajouter", "nouvelle fonction")):
            action = "add_function"
        elif any(kw in cmd_lower for kw in ("modifie", "corrige", "fix", "change ", "modifier", "corriger")):
            action = "modify_function"
        elif any(kw in cmd_lower for kw in ("crée un fichier", "nouveau fichier", "create file", "nouveau module")):
            action = "create_file"
        elif any(kw in cmd_lower for kw in ("montre", "affiche", "show", "read ", "lis ")):
            action = "read_file"
        else:
            action = "unknown"

        file_match = re.search(r"([A-Za-z]:[/\\][^\s\]]+\.py|[\w/\\]+\.py)", command)
        if file_match:
            raw_path = file_match.group(1)
            # Path absolu Windows (D:\...) → garder tel quel pour context["target_path"]
            # Path relatif → normaliser separateurs
            target_file = raw_path.replace("\\", "/") if not re.match(r"[A-Za-z]:", raw_path) else raw_path
        else:
            target_file = None

        symbol_match = re.search(r"(?:fonction|function|def|méthode|method)\s+([\w_]+)", cmd_lower)
        symbol = symbol_match.group(1) if symbol_match else None

        log.info(
            "Fallback heuristique : action=%s target=%s symbol=%s",
            action, target_file, symbol
        )

        return NLIntent(
            action            = action,
            target_file       = target_file,
            symbol            = symbol,
            description       = command,
            create_if_missing = (action == "create_file"),
            confidence        = 0.3,
            raw_command       = command,
            from_fallback     = True,
        )
