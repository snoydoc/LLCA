# -*- coding: utf-8-sig -*-
"""
LCCA V8 -- CoderBuilder : helpers purs pour CoderAgent.

Responsabilites :
    - Constante systeme LLM (_CODER_SYSTEM)
    - Construction du prompt utilisateur (_build_coder_prompt)
    - Formatage du contexte skills (_format_skills_context)
    - Construction du patch edit_batch (_build_patch)

Aucune dependance vers BaseAgent / bus / MCP.
Importable seul dans les tests unitaires.

REFACTO-07 : extrait de coder_agent.py.
"""
from __future__ import annotations

from .a2a_bus import TaskContract


# ---------------------------------------------------------------------------
# Constante systeme LLM
# ---------------------------------------------------------------------------

CODER_SYSTEM = (
    "You are LCCA CoderAgent, an expert Python code generator. "
    "Generate ONLY valid Python 3.11 code. "
    "No explanations, no markdown fences. "
    "Use type hints, docstrings, PEP 8. "
    "Raise NotImplementedError for unknown logic."
)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_coder_prompt(
    intent: str,
    domain: str,
    skills_ctx: str,
    fix_hints: list[str] | None = None,
    last_quality_score: int | None = None,
) -> str:
    """
    Construit le prompt utilisateur pour le LLM.
    FL-01 : enrichi avec fix_hints et last_quality_score si disponibles.

    intent             : l'intent brut du contrat (ex: "add a parse_json function")
    domain             : domaine detecte par ArchitectAgent (ui, api, database, ...)
    skills_ctx         : contexte textuel des skills injectes (peut etre vide)
    fix_hints          : FL-01 -- instructions de correction (optionnel)
    last_quality_score : FL-01 -- score iteration precedente (optionnel)
    """
    lines = [
        f"Domain: {domain}",
        f"Task: {intent}",
    ]

    # FL-01 : score precedent
    if last_quality_score is not None and last_quality_score < 100:
        lines.append(f"\nPrevious attempt quality score: {last_quality_score}/100")

    # FL-01 : instructions de correction obligatoires
    if fix_hints:
        lines.append("\nRequired fixes for this iteration:")
        for hint in fix_hints:
            lines.append(f"  - {hint}")

    if skills_ctx:
        lines.append(f"\nAvailable skills (reuse if relevant):\n{skills_ctx}")
    lines.append(
        "\nGenerate a Python function or module that fulfills the task. "
        "Output ONLY the Python code:"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Skills context formatter
# ---------------------------------------------------------------------------

def format_skills_context(skills: list) -> str:
    """
    Formate la liste de skills en texte injectable dans le prompt.

    Chaque skill peut etre un dict avec 'content'/'body' ou une str.
    Limite : 3 premiers skills, 200 chars chacun.
    """
    parts = []
    for i, skill in enumerate(skills[:3]):
        if isinstance(skill, dict):
            body = skill.get("content") or skill.get("body") or str(skill)
        else:
            body = str(skill)
        parts.append(f"[skill {i+1}] {body[:200]}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Patch builder (structure edit_batch)
# ---------------------------------------------------------------------------

def build_patch(contract: TaskContract, skills: list, generated_code: str = "") -> dict:
    """
    Construit un patch edit_batch depuis un contrat.

    V8-08 : ajoute generated_code dans le payload.
            Si generated_code non vide, cree une operation "create" au format
            attendu par _tool_edit_batch : {"files": [{"path", "action", "code"}]}

    FIX-EDITBATCH-01 : champ renomme "edits" -> "files" pour compat _tool_edit_batch.
    Le path cible est lu depuis contract.context["target_path"] si present,
    sinon derive en snake_case depuis l'intent.
    """
    files = []
    if generated_code:
        # Priorite 1 : path explicite injecte par l'orchestrateur/NL
        target_path = contract.context.get("target_path") if isinstance(contract.context, dict) else None
        if not target_path:
            # Derive un nom de fichier depuis l'intent (snake_case, .py)
            slug = "_".join(contract.intent.lower().split()[:5])
            slug = "".join(c if c.isalnum() or c == "_" else "_" for c in slug)
            target_path = f"{slug}.py"
        files.append({
            "path":   target_path,
            "action": "create",
            "code":   generated_code,
        })

    return {
        "task_id":        contract.task_id,
        "intent":         contract.intent,
        "domain":         contract.domain,
        "skills":         skills,
        "generated_code": generated_code,
        "files":          files,
        "context":        contract.context,
        "constraints":    contract.constraints,
    }


# ---------------------------------------------------------------------------
# Aliases prive (retrocompat interne si quelqu'un importait les _ depuis coder_agent)
# ---------------------------------------------------------------------------
_CODER_SYSTEM          = CODER_SYSTEM
_build_coder_prompt    = build_coder_prompt
_format_skills_context = format_skills_context
_build_patch           = build_patch
