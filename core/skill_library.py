# -*- coding: utf-8-sig -*-
"""
LCCA V8 -- SkillLibrary : stockage et injection de snippets qualifies.

Responsabilites :
    1. extract_and_store(code, receipt, source_intent, quality_score)
       -> extrait les fonctions / classes du code valide
       -> stocke dans lcca_skills (MemoryEngine) si receipt OK + score >= seuil
    2. retrieve(prompt, n) -> list[SkillEntry]
       -> recherche semantique dans lcca_skills
    3. format_for_prompt(entries) -> str
       -> formate les entries en bloc injectables dans un prompt LLM
       (max SKILL_MAX_BODY_LINES lignes par skill, max SKILL_MAX_PER_PROMPT skills)

V8-Regle-17 : aucun skill stocke sans ExecutionReceipt valide.
V8-Regle-20 : ne modifie jamais core/ directement.

Usage::

    lib = SkillLibrary()
    lib.extract_and_store(code, receipt, intent="parse_ast", quality_score=85)
    entries = lib.retrieve("ast parsing function")
    prompt_snippet = lib.format_for_prompt(entries)
"""
from __future__ import annotations

import ast
import hashlib
import logging
from dataclasses import dataclass, asdict
from typing import Optional

from config import (
    AGENT_MIN_QUALITY_SCORE,
    SKILL_MAX_BODY_LINES,
    SKILL_MAX_PER_PROMPT,
)
from core.receipt_store import ExecutionReceipt, verify_receipt

log = logging.getLogger("lcca.skill_library")


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class SkillEntry:
    """
    Un skill extrait d'un code valide et signe.

    Attributes:
        skill_id       : MD5 12 chars du body.
        name           : Nom de la fonction / classe.
        body           : Code source complet (max SKILL_MAX_BODY_LINES lignes).
        source_intent  : Intent original (contexte metier).
        quality_score  : Score CodeEvaluator au moment de la capture.
        receipt_task_id: task_id du receipt ayant signe ce skill.
        source_type    : "internal" | "external" (ED-03 Educator).
        commit_hash    : SHA court du commit GitHub source (ED-03 Educator).
    """
    skill_id:        str
    name:            str
    body:            str
    source_intent:   str
    quality_score:   int
    receipt_task_id: str
    source_type:     str = "internal"   # ED-03 : retro-compat via valeur par defaut
    commit_hash:     str = ""           # ED-03 : hash court commit GitHub

    def to_dict(self) -> dict:
        return {
            "skill_id"       : self.skill_id,
            "name"           : self.name,
            "body"           : self.body,
            "source_intent"  : self.source_intent,
            "quality_score"  : self.quality_score,
            "receipt_task_id": self.receipt_task_id,
            "source_type"    : self.source_type,
            "commit_hash"    : self.commit_hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SkillEntry":
        return cls(
            skill_id        = d.get("skill_id", ""),
            name            = d.get("name", ""),
            body            = d.get("body", ""),
            source_intent   = d.get("source_intent", ""),
            quality_score   = int(d.get("quality_score", 0)),
            receipt_task_id = d.get("receipt_task_id", ""),
            source_type     = d.get("source_type", "internal"),  # retro-compat
            commit_hash     = d.get("commit_hash", ""),
        )


# ---------------------------------------------------------------------------
# Helpers module-level (testables unitairement)
# ---------------------------------------------------------------------------

def _make_skill_id(body: str) -> str:
    """MD5 12 chars du corps -- identique au pattern LCCA."""
    return hashlib.md5(body.encode("utf-8")).hexdigest()[:12]


def _truncate_body(body: str, max_lines: int = SKILL_MAX_BODY_LINES) -> str:
    """Tronque le corps a max_lines lignes. Ajoute '# ...' si tronque."""
    lines = body.splitlines()
    if len(lines) <= max_lines:
        return body
    return "\n".join(lines[:max_lines]) + "\n# ..."


def extract_top_level(code: str) -> list[tuple[str, str]]:
    """
    Extrait les fonctions et classes de premier niveau d'un bloc Python.

    Retourne une liste de (nom, code_source).
    Retourne [] si syntaxe invalide ou code vide.
    """
    if not code or not code.strip():
        return []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        log.debug("extract_top_level: SyntaxError -- code invalide")
        return []

    results: list[tuple[str, str]] = []
    lines = code.splitlines(keepends=True)

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        # Noeud de premier niveau uniquement (pas imbrique)
        if not isinstance(getattr(node, "col_offset", None), int):
            continue
        if node.col_offset != 0:
            continue

        start = node.lineno - 1
        end   = node.end_lineno  # type: ignore[attr-defined]
        body  = "".join(lines[start:end])
        results.append((node.name, body))

    return results


# ---------------------------------------------------------------------------
# SkillLibrary
# ---------------------------------------------------------------------------

class SkillLibrary:
    """
    Bibliotheque de skills V8.

    Args:
        memory_engine       : MemoryEngine injecte. Si None, cree une instance.
        min_quality_score   : Seuil sous lequel le skill n'est pas stocke
                              (defaut : config.AGENT_MIN_QUALITY_SCORE).
        max_body_lines      : Troncature du corps pour le prompt.
        max_per_prompt      : Nombre max de skills injectes par prompt.
    """

    def __init__(
        self,
        memory_engine=None,
        min_quality_score: int = AGENT_MIN_QUALITY_SCORE,
        max_body_lines: int = SKILL_MAX_BODY_LINES,
        max_per_prompt: int = SKILL_MAX_PER_PROMPT,
    ) -> None:
        if memory_engine is None:
            from core.memory_engine import MemoryEngine
            memory_engine = MemoryEngine()
        self._mem = memory_engine
        self._min_quality = min_quality_score
        self._max_body_lines = max_body_lines
        self._max_per_prompt = max_per_prompt

    # ------------------------------------------------------------------
    # API principale
    # ------------------------------------------------------------------

    def extract_and_store(
        self,
        code: str,
        receipt: ExecutionReceipt,
        source_intent: str = "",
        quality_score: int = 0,
    ) -> list[str]:
        """
        Extrait les fonctions/classes du code valide et les stocke dans
        lcca_skills.

        V8-Regle-17 : si le receipt n'est pas valide, aucun skill n'est stocke.

        Args:
            code           : Code Python source (valide, passe le sandbox).
            receipt        : ExecutionReceipt signe par TesterAgent.
            source_intent  : Intent d'origine (pour la recherche semantique).
            quality_score  : Score CodeEvaluator (0-100).

        Returns:
            Liste des skill_id stockes. Vide si aucun skill qualifie.
        """
        # Regle 17 : verifier integrite receipt
        if not verify_receipt(receipt):
            log.warning(
                "[skill_library] Receipt invalide pour task_id=%s -- aucun skill stocke",
                receipt.task_id,
            )
            return []

        # Seuil qualite
        if quality_score < self._min_quality:
            log.debug(
                "[skill_library] quality_score=%d < %d -- skip",
                quality_score, self._min_quality,
            )
            return []

        # Extraction AST
        top_level = extract_top_level(code)
        if not top_level:
            log.debug("[skill_library] aucun symbole top-level extrait")
            return []

        stored_ids: list[str] = []
        for name, body in top_level:
            truncated = _truncate_body(body, self._max_body_lines)
            skill_id  = _make_skill_id(truncated)

            entry = SkillEntry(
                skill_id=skill_id,
                name=name,
                body=truncated,
                source_intent=source_intent,
                quality_score=quality_score,
                receipt_task_id=receipt.task_id,
            )

            result = self._mem.store("lcca_skills", {
                "skill_id":        skill_id,
                "name":            name,
                "code":            truncated,     # cle "code" pour _extract_content()
                "source_intent":   source_intent,
                "quality_score":   quality_score,
                "receipt_task_id": receipt.task_id,
            })

            if result.stored:
                stored_ids.append(skill_id)
                log.info("[skill_library] stored skill %s (%s)", skill_id, name)
            else:
                log.debug("[skill_library] store rejected: %s", result.reason)

        return stored_ids

    def retrieve(
        self,
        prompt: str,
        n: int = SKILL_MAX_PER_PROMPT,
    ) -> list[SkillEntry]:
        """
        Recherche semantique dans lcca_skills.

        Args:
            prompt : Texte de la requete (intent ou question).
            n      : Nombre max de skills retournes.

        Returns:
            Liste de SkillEntry triee par pertinence.
        """
        results = self._mem.search(prompt, n=n)
        skill_entries = results.get("skills", [])

        entries: list[SkillEntry] = []
        for mem_entry in skill_entries:
            meta = mem_entry.metadata or {}
            body = mem_entry.content or ""
            entry = SkillEntry(
                skill_id=meta.get("skill_id", _make_skill_id(body)),
                name=meta.get("name", "unknown"),
                body=body,
                source_intent=meta.get("source_intent", ""),
                quality_score=int(meta.get("quality_score", 0)),
                receipt_task_id=meta.get("receipt_task_id", ""),
            )
            entries.append(entry)

        return entries[: self._max_per_prompt]

    def record_usage(self, skill_id: str) -> None:
        """
        Enregistre l'utilisation d'un skill dans la boucle KarpathyLoop.

        Incremente le compteur "used_count" dans les metadonnees du skill.
        Silencieux si skill_id inconnu ou MemoryEngine indisponible.

        Args:
            skill_id : identifiant du skill (12 chars MD5).
        """
        try:
            self._mem.store("lcca_skill_usage", {
                "skill_id": skill_id,
                "event": "used",
            })
            log.debug("[skill_library] record_usage skill_id=%s", skill_id)
        except Exception as exc:
            log.debug("[skill_library] record_usage error: %s", exc)

    def record_outcome(self, skill_id: str, success: bool) -> None:
        """
        Enregistre le resultat d'une iteration ayant utilise un skill.

        Stocke l'evenement "success" ou "failure" dans lcca_skill_usage.
        Silencieux si skill_id inconnu ou MemoryEngine indisponible.

        Args:
            skill_id : identifiant du skill.
            success  : True si le Tester a valide le code, False sinon.
        """
        event = "success" if success else "failure"
        try:
            self._mem.store("lcca_skill_usage", {
                "skill_id": skill_id,
                "event": event,
            })
            log.debug(
                "[skill_library] record_outcome skill_id=%s event=%s",
                skill_id, event,
            )
        except Exception as exc:
            log.debug("[skill_library] record_outcome error: %s", exc)

    def format_for_prompt(self, entries: list[SkillEntry]) -> str:
        """
        Formate une liste de SkillEntry en bloc injectable dans un prompt LLM.

        Format :
            ## Skill: <name> (score=<quality_score>)
            <body>
            ---

        Retourne une chaine vide si entries est vide.
        """
        if not entries:
            return ""

        parts: list[str] = ["### Skills disponibles (exemples valides):\n"]
        for entry in entries[: self._max_per_prompt]:
            truncated = _truncate_body(entry.body, self._max_body_lines)
            parts.append(
                f"## Skill: {entry.name} (score={entry.quality_score})\n"
                f"```python\n{truncated}\n```\n---\n"
            )
        return "\n".join(parts)
