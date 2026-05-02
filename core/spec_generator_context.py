# -*- coding: utf-8-sig -*-
"""
spec_generator_context.py — REFACTO-16
Extrait de spec_generator.py : construction du contexte technique SPEC-02.

Responsabilité unique : enrichissement du prompt de génération avec le code LCCA réel.
  - _DOMAIN_FILES     : mappage domain → fichiers LCCA prioritaires
  - _KEYWORD_FILES    : mots-clés intent → fichiers LCCA additionnels
  - _build_technical_context() : lit les 60 premières lignes et construit le contexte
"""
from __future__ import annotations

# ── Mappage domain → fichiers LCCA prioritaires ───────────────────────────────
_DOMAIN_FILES: dict[str, list[str]] = {
    "transaction":   ["core/transaction_manager.py", "core/transaction_types.py"],
    "ast":           ["core/ast_indexer.py", "core/smart_patcher.py"],
    "mcp":           ["core/mcp_server.py", "core/mcp_tool_handlers.py", "core/mcp_tools_schema.py"],
    "sandbox":       ["core/sandbox_engine.py"],
    "memory":        ["core/memory_engine.py", "core/mempalace_client.py"],
    "spec":          ["core/spec_entry.py", "core/spec_generator.py", "core/spec_validator.py"],
    "orchestration": ["core/orchestrator.py", "core/planner.py"],
    "global":        ["config.py", "core/__init__.py"],
}

# ── Mots-clés intent → fichiers LCCA additionnels ────────────────────────────
_KEYWORD_FILES: dict[str, str] = {
    "web":       "core/web_search.py",
    "search":    "core/web_search.py",
    "cache":     "core/web_search_cache.py",
    "nl":        "core/nl_parser.py",
    "chat":      "core/mcp_tool_handlers.py",
    "llm":       "core/llm_generator.py",
    "spec":      "core/spec_generator.py",
    "validator": "core/spec_validator.py",
    "memory":    "core/memory_engine.py",
    "sandbox":   "core/sandbox_engine.py",
    "index":     "core/ast_indexer.py",
    "rag":       "core/memory_engine.py",
    "ollama":    "core/llm_generator.py",
}


def _build_technical_context(intent: str, domain: str, extra_context: str = "") -> str:
    """
    SPEC-02 — Construit un contexte technique enrichi pour le prompt de spec.

    Lit les 60 premières lignes (header + signatures) des fichiers LCCA pertinents
    selon le domaine et les mots-clés de l'intent.

    Stratégie :
      1. Mappage domain → fichiers cibles LCCA (_DOMAIN_FILES)
      2. Enrichissement par mots-clés de l'intent (_KEYWORD_FILES)
      3. Lecture des 60 premières lignes de chaque fichier (max 4 fichiers)
      4. Concaténation avec le contexte existant (RAG specs + user context)

    Args:
        intent        : prompt utilisateur (pour détecter les mots-clés)
        domain        : domaine V7.2
        extra_context : contexte déjà construit — préservé

    Returns:
        Contexte enrichi avec le code source LCCA, ou extra_context seul si aucun fichier.
    """
    from pathlib import Path

    try:
        import config
        base: Path = config.BASE_DIR
    except Exception:
        return extra_context

    target_files: list[str] = list(_DOMAIN_FILES.get(domain, _DOMAIN_FILES["global"]))

    intent_lower = intent.lower()
    for kw, fpath in _KEYWORD_FILES.items():
        if kw in intent_lower and fpath not in target_files:
            target_files.append(fpath)

    snippets: list[str] = []
    for rel_path in target_files[:4]:
        full_path = base / rel_path
        try:
            if not full_path.exists():
                continue
            lines = full_path.read_text(encoding="utf-8-sig").splitlines()[:60]
            content = "\n".join(lines)
            snippets.append(
                f"### `{rel_path}` (60 premières lignes)\n"
                f"```python\n{content}\n```"
            )
        except Exception:
            continue

    if not snippets:
        return extra_context

    code_context = (
        "## Code source LCCA existant (pour ancrer la spec dans le code réel)\n\n"
        + "\n\n".join(snippets)
    )

    if extra_context:
        return f"{extra_context}\n\n{code_context}"
    return code_context
