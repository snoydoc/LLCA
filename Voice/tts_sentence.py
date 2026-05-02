# Voice/tts_sentence.py
# VOICE-06 -- Sentence splitter pour streaming TTS phrase-par-phrase
# Isolation totale : 0 import depuis core/
# Encodage : utf-8-sig (BOM Windows)

from __future__ import annotations

import re
from typing import Iterator, List

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Longueur minimale d'une phrase pour etre emise (evite les fragments courts)
MIN_SENTENCE_LEN: int = 3

# Longueur maximale d'un segment avant split force (evite les phrases infinies)
MAX_SEGMENT_LEN: int = 200

# Separateurs de phrases (fin de phrase ferme)
_SENTENCE_END = re.compile(r'(?<=[.!?])\s+')

# Separateurs faibles : virgule, point-virgule, tiret long — utilises si le
# segment depasse MAX_SEGMENT_LEN
_WEAK_SPLIT = re.compile(r'(?<=[,;])\s+|(?<=\u2014)\s*')


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------

def split_sentences(text: str) -> List[str]:
    """
    Decoupe un texte en phrases exploitables par le TTS.

    Regles :
    - Separe sur . ! ? suivis d'un espace
    - Si un segment depasse MAX_SEGMENT_LEN : split faible sur , ; --
    - Si toujours trop long : split force a MAX_SEGMENT_LEN caracteres
    - Segments < MIN_SENTENCE_LEN ignores (fragments parasites)
    - Retourne une liste vide si le texte est vide

    Args:
        text : Texte brut a decouper.

    Returns:
        Liste de phrases nettoyees (strip(), non vides).
    """
    if not text or not text.strip():
        return []

    text = text.strip()

    # Premiere passe : split sur fins de phrases
    raw_parts = _SENTENCE_END.split(text)

    sentences: List[str] = []
    for part in raw_parts:
        part = part.strip()
        if not part:
            continue
        if len(part) <= MAX_SEGMENT_LEN:
            if len(part) >= MIN_SENTENCE_LEN:
                sentences.append(part)
        else:
            # Segment trop long : tentative de split faible
            sub_parts = _WEAK_SPLIT.split(part)
            for sub in sub_parts:
                sub = sub.strip()
                if not sub:
                    continue
                if len(sub) <= MAX_SEGMENT_LEN:
                    if len(sub) >= MIN_SENTENCE_LEN:
                        sentences.append(sub)
                else:
                    # Split force : decoupage a MAX_SEGMENT_LEN
                    for chunk in _force_split(sub, MAX_SEGMENT_LEN):
                        if len(chunk) >= MIN_SENTENCE_LEN:
                            sentences.append(chunk)

    return sentences


def iter_sentences(text: str) -> Iterator[str]:
    """
    Version generateur de split_sentences.
    Utile pour le streaming phrase-par-phrase sans construire la liste complete.
    """
    yield from split_sentences(text)


def flush_partial(buffer: str) -> tuple[List[str], str]:
    """
    Extrait les phrases completes d'un buffer partiel (streaming Ollama).

    Le buffer contient du texte en cours de generation. On extrait les phrases
    terminees (finissant par . ! ?) et on retourne le reste dans le buffer.

    Args:
        buffer : Texte accumule depuis le debut du streaming.

    Returns:
        (phrases_completes, reste_non_emis)
    """
    if not buffer:
        return [], ""

    # Chercher la derniere fin de phrase dans le buffer
    matches = list(re.finditer(r'[.!?]', buffer))
    if not matches:
        # Pas de fin de phrase : tout reste dans le buffer
        return [], buffer

    # Couper apres le dernier . ! ? trouve
    last_end = matches[-1].end()
    completed = buffer[:last_end].strip()
    remainder = buffer[last_end:].lstrip()

    if not completed:
        return [], buffer

    phrases = split_sentences(completed)
    return phrases, remainder


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------

def _force_split(text: str, max_len: int) -> List[str]:
    """
    Decoupe un texte trop long en morceaux de max_len caracteres maximum.
    Essaie de couper sur un espace si possible.
    """
    chunks = []
    while len(text) > max_len:
        # Chercher le dernier espace avant max_len
        cut = text.rfind(' ', 0, max_len)
        if cut <= 0:
            cut = max_len
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        chunks.append(text)
    return chunks
