# -*- coding: utf-8-sig -*-
"""
user_context_learner.py - LCCA V10 / Mode Projets
Sprint PROJ-08 - UserContextLearner : apprentissage auto fin de session

Analyse les corrections/patterns de la session et les ecrit dans le WAL
via UserContextLoader. Appele par save_project() dans ProjectOrchestrator.

Invariants (repris de PROJ-06) :
  - Max 3 signaux auto_detected par session (guard UserContextLoader)
  - Champs sensibles (identity.*, communication.language) : jamais auto_detected
  - 0 appel LLM — deduction purement deterministique depuis les donnees session
  - 0 exception propagee — mode degrade silencieux partout
  - Deduplication Jaccard >= 0.85 avant ecriture WAL
  - Session avec 0 echanges → 0 signal emis

Signaux detectes :
  - user_corrections   : messages commencant par "non", "pas ca", "corrige", "change"
  - explicit_commands  : "appelle-moi", "utilise le ton", "reponds en", "taille modules"
  - coding_style_hints : patterns recurrents dans les diffs/corrections code
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.user_context import UserContextLoader, UserContextState

log = logging.getLogger(__name__)

# Seuil Jaccard pour deduplication des signaux (coherent avec ObserverAgent)
JACCARD_DEDUP_THRESHOLD = 0.85

# Patterns de correction explicite (insensibles a la casse, apres normalisation)
_CORRECTION_PATTERNS = [
    r"^non[,\s]",
    r"^pas ca",
    r"^pas comme",
    r"^corrige",
    r"^change ",
    r"^modifie ",
    r"^appelle.moi",
]

# Patterns de commandes explicites (extraient une valeur)
_EXPLICIT_COMMAND_PATTERNS = [
    # "appelle-moi Adham" / "je m'appelle Adham"
    (r"appelle.moi\s+(\w+)", "identity.name"),
    (r"je m'?appelle\s+(\w+)", "identity.name"),
    # "reponds en anglais" / "en francais"
    (r"r[eé]ponds\s+en\s+(anglais|fran[cç]ais|arabe|espagnol|allemand)", "communication.language"),
    (r"parle.moi\s+en\s+(anglais|fran[cç]ais|arabe|espagnol|allemand)", "communication.language"),
    # "utilise un ton formel" / "ton plus casual"
    (r"ton\s+(formel|casual|d[eé]tendu|professionnel)", "communication.tone"),
    (r"plus\s+(formel|casual|d[eé]tendu)", "communication.tone"),
    # "taille modules" / "fichiers plus courts"
    (r"fichiers?\s+(?:de\s+)?moins de\s+(\d+)\s*(?:kb|KB|Ko)", "learned.preferred_file_size"),
    (r"modules?\s+(?:de\s+)?moins de\s+(\d+)\s*(?:kb|KB|Ko)", "learned.preferred_file_size"),
]

# Mapping langue → code ISO
_LANG_MAP = {
    "anglais": "en",
    "francais": "fr",
    "français": "fr",
    "arabe": "ar",
    "espagnol": "es",
    "allemand": "de",
}

# Mapping ton → valeur normalisee
_TONE_MAP = {
    "formel": "formal",
    "casual": "casual",
    "détendu": "casual",
    "detenu": "casual",
    "professionnel": "formal",
}


# ---------------------------------------------------------------------------
# Signal de session detecte
# ---------------------------------------------------------------------------

@dataclass
class SessionSignal:
    """Signal d'apprentissage detecte depuis la session."""
    field: str           # cle pointee (ex: "communication.tone")
    old_value: Any       # valeur precedente (depuis state)
    new_value: Any       # valeur proposee
    source: str          # "auto_detected" | "user_correction" | "explicit_command"
    confidence: float    # 0.0 → 1.0 (utilise pour le tri, pas pour filtre)
    raw_text: str        # fragment de message source (debug)


# ---------------------------------------------------------------------------
# UserContextLearner
# ---------------------------------------------------------------------------

class UserContextLearner:
    """
    Detecte les signaux d'apprentissage depuis la session et les ecrit en WAL.

    Usage (dans ProjectOrchestrator.save_project()) :
        learner = UserContextLearner()
        learner.learn_from_session(state, loader, session_messages)
    """

    def learn_from_session(
        self,
        state: "UserContextState",
        loader: "UserContextLoader",
        session_messages: list[dict],
    ) -> int:
        """
        Analyse les messages de session et ecrit les signaux dans le WAL.

        session_messages : liste de dicts {"role": "user"|"assistant", "content": str}

        Retourne le nombre de signaux ecrits en WAL.
        """
        if not session_messages:
            return 0

        try:
            signals = self._detect_signals(state, session_messages)
            signals = self._deduplicate(signals, state)
            written = 0
            for sig in signals:
                ok = loader.append_wal(
                    state,
                    sig.field,
                    sig.old_value,
                    sig.new_value,
                    sig.source,
                )
                if ok:
                    written += 1
                    log.info(
                        "PROJ-08 WAL : %s=%s (source=%s conf=%.2f)",
                        sig.field, sig.new_value, sig.source, sig.confidence,
                    )
            return written
        except Exception as exc:
            log.warning("UserContextLearner.learn_from_session : erreur silencieuse : %s", exc)
            return 0

    # ---- Detection ---------------------------------------------------------

    def _detect_signals(
        self,
        state: "UserContextState",
        messages: list[dict],
    ) -> list[SessionSignal]:
        """Collecte tous les signaux detectables depuis la liste de messages."""
        signals: list[SessionSignal] = []
        user_msgs = [
            m["content"]
            for m in messages
            if m.get("role") == "user" and m.get("content")
        ]

        for text in user_msgs:
            normalized = text.strip().lower()
            signals.extend(self._detect_explicit_commands(state, text, normalized))
            signals.extend(self._detect_corrections(state, text, normalized))

        # Tri par confiance decroissante — les plus forts en premier
        signals.sort(key=lambda s: s.confidence, reverse=True)
        return signals

    def _detect_explicit_commands(
        self,
        state: "UserContextState",
        text: str,
        normalized: str,
    ) -> list[SessionSignal]:
        """Detecte les commandes explicites de mise a jour du contexte."""
        signals = []
        for pattern, target_field in _EXPLICIT_COMMAND_PATTERNS:
            m = re.search(pattern, normalized, re.IGNORECASE)
            if not m:
                continue

            raw_val = m.group(1) if m.lastindex and m.lastindex >= 1 else ""
            new_value = self._normalize_value(target_field, raw_val)
            if new_value is None:
                continue

            from core.user_context import _get_nested
            old_value = _get_nested(state.data, target_field)
            if old_value == new_value:
                continue  # deja a jour

            signals.append(SessionSignal(
                field=target_field,
                old_value=old_value,
                new_value=new_value,
                source="explicit_command",
                confidence=0.95,
                raw_text=text[:120],
            ))
        return signals

    def _detect_corrections(
        self,
        state: "UserContextState",
        text: str,
        normalized: str,
    ) -> list[SessionSignal]:
        """
        Detecte les signaux de correction implicites.
        Identifie les patterns de rejet/correction mais n'extrait PAS
        de valeur specifique — marque uniquement le niveau de friction.
        """
        signals = []
        is_correction = any(
            re.match(p, normalized, re.IGNORECASE)
            for p in _CORRECTION_PATTERNS
        )
        if not is_correction:
            return signals

        # Correction de ton : "non, sois plus concis" / "moins de details"
        if re.search(r"(concis|court|bref|moins de d[eé]tail)", normalized):
            old = state.verbosity
            if old != "concise":
                signals.append(SessionSignal(
                    field="communication.verbosity",
                    old_value=old,
                    new_value="concise",
                    source="auto_detected",
                    confidence=0.70,
                    raw_text=text[:120],
                ))

        if re.search(r"(d[eé]tail|d[eé]veloppe|explique plus)", normalized):
            old = state.verbosity
            if old != "verbose":
                signals.append(SessionSignal(
                    field="communication.verbosity",
                    old_value=old,
                    new_value="verbose",
                    source="auto_detected",
                    confidence=0.65,
                    raw_text=text[:120],
                ))

        return signals

    # ---- Deduplication Jaccard ---------------------------------------------

    def _deduplicate(
        self,
        signals: list[SessionSignal],
        state: "UserContextState",
    ) -> list[SessionSignal]:
        """
        Filtre les signaux dont la valeur est trop proche d'une valeur
        deja connue dans le state (Jaccard lexical >= JACCARD_DEDUP_THRESHOLD).

        Cohérent avec ObserverAgent (pattern LCCA - pas cosine).
        """
        unique: list[SessionSignal] = []
        seen_fields: set[str] = set()

        for sig in signals:
            # Un seul signal par champ par session
            if sig.field in seen_fields:
                continue

            # Dedup valeur vs state courant
            from core.user_context import _get_nested
            current_val = _get_nested(state.data, sig.field)
            if current_val is not None:
                score = _jaccard(str(current_val), str(sig.new_value))
                if score >= JACCARD_DEDUP_THRESHOLD:
                    log.debug(
                        "PROJ-08 dedup Jaccard %.2f >= %.2f : %s skipped",
                        score, JACCARD_DEDUP_THRESHOLD, sig.field,
                    )
                    continue

            unique.append(sig)
            seen_fields.add(sig.field)

        return unique

    # ---- Normalisation valeurs ---------------------------------------------

    @staticmethod
    def _normalize_value(field: str, raw: str) -> Optional[Any]:
        """Normalise la valeur brute extraite selon le champ cible."""
        raw = raw.strip().lower()
        if field == "communication.language":
            return _LANG_MAP.get(raw)
        if field == "communication.tone":
            return _TONE_MAP.get(raw)
        if field == "identity.name":
            return raw.capitalize() if raw else None
        if field == "learned.preferred_file_size":
            return f"< {raw.upper()} par module"
        return raw if raw else None


# ---------------------------------------------------------------------------
# Helper Jaccard lexical (tokenisation mots)
# ---------------------------------------------------------------------------

def _jaccard(a: str, b: str) -> float:
    """Jaccard lexical sur les tokens (mots). Insensible a la casse."""
    if not a and not b:
        return 1.0
    set_a = set(re.findall(r"\w+", a.lower()))
    set_b = set(re.findall(r"\w+", b.lower()))
    if not set_a and not set_b:
        return 1.0
    union = set_a | set_b
    inter = set_a & set_b
    return len(inter) / len(union)
