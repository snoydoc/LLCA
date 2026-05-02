# -*- coding: utf-8-sig -*-
"""
spec_generator_helpers.py — REFACTO-16
Extrait de spec_generator.py : helpers d'extraction Markdown.

Responsabilité unique : parsing des specs générées par le LLM.
  - _extract_title()      : extrait le titre depuis le Markdown
  - _extract_abstract()   : extrait l'abstract depuis le Markdown
  - _compute_complexity() : score de complexité 0-100 (V7.2)
"""
from __future__ import annotations

import re


def _extract_title(md: str) -> str:
    """Extrait le titre depuis le Markdown généré par le LLM."""
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()[:100]

    # Chercher "## Titre" + ligne suivante (format _SPEC_DIRECT_SYSTEM)
    lines = md.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^##\s+Titre", line.strip(), re.IGNORECASE):
            if i + 1 < len(lines) and lines[i + 1].strip():
                next_line = lines[i + 1].strip()
                if not next_line.startswith("#"):
                    return next_line[:100]

    # Fallback : première ligne non-vide, en retirant les prefixes Markdown
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("<!--"):
            continue
        cleaned = re.sub(r'^#{1,6}\s*', '', s).strip()
        if cleaned:
            return cleaned[:100]

    return "Sans titre"


def _extract_abstract(md: str) -> str:
    """Extrait la section Abstract/Resume depuis le Markdown."""
    lines = md.splitlines()
    in_abstract = False
    parts: list[str] = []
    for line in lines:
        if re.match(r"^#{1,3}\s*(Abstract|Resume)", line, re.IGNORECASE):
            in_abstract = True
            continue
        if in_abstract:
            if line.startswith("#"):
                break
            parts.append(line)
    text = " ".join(parts).strip()
    return text[:500] if text else md[:200]


def _compute_complexity(body_md: str) -> int:
    """
    Algorithme V7.2 : score de complexité sur 100.
    score = min(100, sections * 5 + règles * 3)
    - sections : lignes commençant par "## "
    - règles   : lignes de tableau (commençant par "| ")
    """
    sections = len([ln for ln in body_md.splitlines() if ln.startswith("## ")])
    rules = len([ln for ln in body_md.splitlines() if ln.strip().startswith("| ")])
    return min(100, sections * 5 + rules * 3)
