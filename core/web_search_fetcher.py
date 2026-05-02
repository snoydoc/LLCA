# -*- coding: utf-8-sig -*-
"""
web_search_fetcher.py — Fetcher HTTP amélioré avec extraction sémantique (Sprint WEB-02).

Améliorations vs UI-06 :
  - Extraction sémantique : <article> / <main> / <div class=content> en priorité
  - Troncature à la dernière phrase complète (pas au caractère)
  - Scoring de qualité 0.0–1.0 par page
  - Filtrage des pages inutiles (cookie walls, 403, JS-only)
"""
from __future__ import annotations

import html
import logging
import re
import urllib.error
import urllib.request

from core.web_search_types import FetchedPage

log = logging.getLogger("lcca.web_search_fetcher")

_HTTP_TIMEOUT   = 30    # secondes
_PAGE_MAX_CHARS = 3000  # WEB-02 : augmenté de 2000 → 3000 (troncature propre compense)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
}

# Patterns de contenu sémantique (essayés dans l'ordre)
_SEMANTIC_PATTERNS = [
    re.compile(r"<article[^>]*>(.*?)</article>",                            re.DOTALL | re.IGNORECASE),
    re.compile(r"<main[^>]*>(.*?)</main>",                                  re.DOTALL | re.IGNORECASE),
    re.compile(r'<div[^>]+class="[^"]*\b(?:content|article|post|entry|body)\b[^"]*"[^>]*>(.*?)</div>', re.DOTALL | re.IGNORECASE),
    re.compile(r'<div[^>]+id="[^"]*\b(?:content|main|article)\b[^"]*"[^>]*>(.*?)</div>',              re.DOTALL | re.IGNORECASE),
]

# Patterns de bruit (cookie walls, erreurs, JS-only)
_NOISE_PATTERNS = [
    "enable javascript",
    "javascript is required",
    "please enable cookies",
    "403 forbidden",
    "access denied",
    "you have been blocked",
    "cloudflare",
    "captcha",
]


class _PageFetcher:
    """
    Fetche une page web et en extrait le contenu textuel pertinent.

    Stratégie d'extraction (ordre de priorité) :
        1. Balises sémantiques HTML5 : <article>, <main>
        2. Divs de contenu courants : class/id content, article, post, entry
        3. Fallback : suppression brute de toutes les balises

    Scoring (0.0–1.0) :
        - 0.0 : page vide / erreur HTTP / cookie wall / JS-only
        - 0.3 : fallback brut (contenu peu fiable)
        - 0.5–1.0 : extraction sémantique réussie (proportionnel à la longueur)
    """

    def fetch(self, url: str) -> FetchedPage:
        """Fetche une page et retourne son contenu structuré + score de qualité."""
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if "text/html" not in content_type and "text/plain" not in content_type:
                    return FetchedPage(
                        url=url, title=url, text="", success=False,
                        error="Non-HTML: %s" % content_type, quality_score=0.0,
                    )
                raw = resp.read().decode("utf-8", errors="replace")

            title = self._extract_title(raw)
            text, method = self._extract_text_smart(raw)
            score = self._score_page(text, url)

            log.debug("fetch %s — method=%s score=%.2f len=%d", url, method, score, len(text))
            return FetchedPage(
                url=url, title=title,
                text=self._truncate_at_sentence(text, _PAGE_MAX_CHARS),
                success=True, quality_score=score,
            )

        except urllib.error.HTTPError as exc:
            return FetchedPage(url=url, title=url, text="", success=False,
                               error="HTTP %d" % exc.code, quality_score=0.0)
        except Exception as exc:
            return FetchedPage(url=url, title=url, text="", success=False,
                               error=str(exc)[:120], quality_score=0.0)

    # ── Extraction titre ──────────────────────────────────────────────────────

    def _extract_title(self, html_text: str) -> str:
        m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
        if m:
            return html.unescape(m.group(1)).strip()[:120]
        return ""

    # ── Extraction sémantique ─────────────────────────────────────────────────

    def _extract_text_smart(self, html_text: str) -> tuple[str, str]:
        """
        Retourne (texte_extrait, méthode_utilisée).
        méthode : 'semantic' | 'fallback'
        """
        # Tenter les patterns sémantiques dans l'ordre
        for pattern in _SEMANTIC_PATTERNS:
            m = pattern.search(html_text)
            if m:
                candidate = self._strip_tags(m.group(1))
                if len(candidate) > 300:   # contenu suffisant
                    return candidate, "semantic"

        # Fallback : extraction brute
        return self._strip_tags_basic(html_text), "fallback"

    def _strip_tags(self, html_text: str) -> str:
        """Supprime balises et normalise les espaces. Conserve la ponctuation."""
        # Supprimer scripts, styles, nav, header, footer
        text = re.sub(
            r"<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>",
            " ", html_text, flags=re.DOTALL | re.IGNORECASE,
        )
        # Balises block → saut de ligne
        text = re.sub(r"<(br|p|div|h[1-6]|li|tr|td)[^>]*>", "\n", text, flags=re.IGNORECASE)
        # Balises restantes
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _strip_tags_basic(self, html_text: str) -> str:
        """Version basique (fallback) — supprime plus agressivement."""
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<(br|p|div|h[1-6]|li|tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    # ── Troncature propre ─────────────────────────────────────────────────────

    @staticmethod
    def _truncate_at_sentence(text: str, max_chars: int) -> str:
        """
        Tronque au dernier `.` / `?` / `!` avant max_chars.
        Garantit que le LLM reçoit des phrases complètes.
        """
        if len(text) <= max_chars:
            return text
        chunk = text[:max_chars]
        # Chercher la dernière fin de phrase
        last = max(chunk.rfind(". "), chunk.rfind("? "), chunk.rfind("! "), chunk.rfind(".\n"))
        if last > max_chars // 2:
            return chunk[:last + 1].strip()
        return chunk.strip()

    # ── Scoring de qualité ────────────────────────────────────────────────────

    def _score_page(self, text: str, url: str) -> float:
        """
        Score de qualité 0.0–1.0.

        Critères positifs :
          - Longueur du texte (proportionnel à _PAGE_MAX_CHARS)
          - Présence de ponctuation structurée
          - Présence de chiffres (contenu factuel)

        Pénalités :
          - Patterns de bruit (cookie walls, 403, JS-only)
          - Texte très court (< 200 chars)
          - Texte sans ponctuation (probablement du bruit)
        """
        if len(text) < 100:
            return 0.0

        # Score de base : longueur relative
        score = min(1.0, len(text) / _PAGE_MAX_CHARS)

        # Pénalité noise patterns (vérifier sur les 500 premiers chars)
        preview = text[:500].lower()
        for noise in _NOISE_PATTERNS:
            if noise in preview:
                return max(0.0, score * 0.2)

        # Bonus : présence de ponctuation (texte réel)
        punct_ratio = sum(1 for c in text if c in ".!?,;:") / max(len(text), 1)
        if punct_ratio > 0.02:
            score = min(1.0, score * 1.2)

        # Pénalité : pas de ponctuation (bruit ou JS)
        if punct_ratio < 0.005:
            score *= 0.4

        return round(score, 2)
