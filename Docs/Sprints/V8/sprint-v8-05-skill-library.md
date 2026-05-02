# Sprint V8-05 — SkillLibrary + SkillExtractor
<!-- AI-READY | Sprint V8 | Phase beta | 2026-04-20 -->

## Objectif

Implémenter le **pattern Voyager/SAGE** : les fonctions validées sont stockées et réutilisées.  
Au lieu de régénérer le même code à chaque fois, LCCA capitalise sur ce qui a marché.

> **Invariant V8-Règle-17** : `SkillLibrary.store()` exige un `ExecutionReceipt` valide avant tout stockage.

---

## Fichiers à créer / modifier

| # | Fichier | Opération |
|---|---------|-----------|
| 1 | `core/skill_library.py` | CREATE |
| 2 | `core/memory_engine.py` | PATCH — ajouter `lcca_skills` à `_VALID_COLLECTIONS` |
| 3 | `config.py` | PATCH — `AGENT_MIN_QUALITY_SCORE = 70`, `SKILL_MAX_BODY_LINES = 20`, `SKILL_MAX_PER_PROMPT = 3` |
| 4 | `tests/test_skill_library.py` | CREATE — 14 tests |

---

## Spécification : `core/skill_library.py`

```python
# core/skill_library.py
"""
Skill Library V8 — Pattern Voyager/SAGE adapté à LCCA.
Stocke les fonctions Python validées en sandbox, les réutilise par RAG.

V8-Règle-17 : store() exige un ExecutionReceipt signé et vérifié.
"""
import ast
import hashlib
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict

from core.memory_engine import MemoryEngine
from core.receipt_store import ExecutionReceipt, verify_receipt
import config

log = logging.getLogger("lcca.skill_library")

_COLLECTION = "lcca_skills"


@dataclass
class Skill:
    skill_id: str           # MD5 du corps complet
    name: str               # Nom de la fonction
    signature: str          # "def validate_email(email: str) -> bool:"
    body: str               # Code complet de la fonction
    body_summary: str       # Résumé ≤ 200 chars (extrait docstring ou première ligne)
    source_spec: str        # spec_id ou task_id d'origine
    usage_count: int = 0
    success_rate: float = 1.0
    quality_score: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Skill":
        return cls(**{k: d.get(k, "") for k in cls.__dataclass_fields__})

    @classmethod
    def make_skill_id(cls, body: str) -> str:
        return hashlib.md5(body.encode()).hexdigest()[:12]


class SkillLibrary:
    """
    Bibliothèque de skills réutilisables.
    Stockage : MemoryEngine collection lcca_skills.
    Recherche : embeddings ChromaDB.
    """
    MAX_SKILLS_PER_PROMPT: int = getattr(config, "SKILL_MAX_PER_PROMPT", 3)
    MAX_BODY_LINES: int = getattr(config, "SKILL_MAX_BODY_LINES", 20)
    # Budget tokens : max 30% du contexte (ContextAssembler.MAX_CONTEXT_TOKENS)
    MAX_PROMPT_CHARS: int = getattr(config, "MAX_CONTEXT_TOKENS", 8000) * 4 * 30 // 100

    def __init__(self, memory: Optional[MemoryEngine] = None):
        self._memory = memory or MemoryEngine()

    # ── Store ─────────────────────────────────────────────────────────

    def store(self, skill: Skill, receipt: ExecutionReceipt) -> bool:
        """
        Stocke un skill. V8-Règle-17 : receipt doit être vérifié.
        Retourne True si stocké, False sinon.
        """
        if not verify_receipt(receipt):
            log.warning("skill_library.store rejected: receipt HMAC invalide skill=%s", skill.skill_id)
            return False

        try:
            self._memory.store(
                collection=_COLLECTION,
                content=skill.body,
                metadata={
                    "skill_id": skill.skill_id,
                    "name": skill.name,
                    "signature": skill.signature,
                    "body_summary": skill.body_summary,
                    "source_spec": skill.source_spec,
                    "usage_count": str(skill.usage_count),
                    "success_rate": str(skill.success_rate),
                    "quality_score": str(skill.quality_score),
                }
            )
            log.info("skill_library.store OK skill=%s name=%s", skill.skill_id, skill.name)
            return True
        except Exception as exc:
            log.debug("skill_library.store error: %s", exc)
            return False

    def extract_and_store(self, code: str, receipt: ExecutionReceipt,
                          source_intent: str, quality_score: int) -> int:
        """
        Extrait les fonctions du code, stocke les valides.
        Retourne le nombre de skills stockés.
        """
        functions = self._extract_functions(code)
        stored = 0
        for name, signature, body in functions:
            skill = Skill(
                skill_id=Skill.make_skill_id(body),
                name=name,
                signature=signature,
                body=body,
                body_summary=self._extract_summary(body),
                source_spec=receipt.task_id,
                quality_score=quality_score,
            )
            if self.store(skill, receipt):
                stored += 1
        return stored

    # ── Search ────────────────────────────────────────────────────────

    def search(self, query: str, n: int = 5) -> List[Skill]:
        """Recherche sémantique dans lcca_skills."""
        try:
            results = self._memory.search(query, n=n)
            # La collection lcca_skills n'est pas dans les clés normalisées de search()
            # → on passe par le client directement si disponible
            raw = getattr(self._memory, "_search_collection", None)
            if raw is None:
                return []
            entries = raw(_COLLECTION, query, n)
            skills = []
            for entry in entries:
                meta = getattr(entry, "metadata", {}) or {}
                meta["body"] = getattr(entry, "content", "")
                try:
                    skills.append(Skill.from_dict(meta))
                except Exception:
                    continue
            return skills
        except Exception as exc:
            log.debug("skill_library.search error: %s", exc)
            return []

    # ── Prompt rendering ──────────────────────────────────────────────

    def render_as_prompt(self, skills: List[Skill]) -> str:
        """
        Formate les skills en few-shot examples.
        Budget : MAX_SKILLS_PER_PROMPT skills, MAX_BODY_LINES lignes chacun.
        Max 30% du budget contexte (V8-Règle budget tokens, Addendum 1.2).
        """
        if not skills:
            return ""

        top = skills[:self.MAX_SKILLS_PER_PROMPT]
        lines = ["# Skills disponibles pour cette tâche\n"]

        for s in top:
            body_display = self._truncate_body(s.body, self.MAX_BODY_LINES)
            lines += [
                f"## {s.name}",
                f"Signature: `{s.signature}`",
                f"Résumé: {s.body_summary}",
                "```python",
                body_display,
                "```\n",
            ]

        prompt = "\n".join(lines)

        # Vérification budget chars (~4 chars/token)
        if len(prompt) > self.MAX_PROMPT_CHARS:
            return self._render_minimal(top)

        return prompt

    def inject_skill_as_module(self, skill: Skill, namespace: dict):
        """
        Injecte un skill dans un namespace Python.
        Usage sandbox sans réécriture LLM (Addendum 2.2).
        """
        exec(compile(skill.body, f"<skill_{skill.name}>", "exec"), namespace)

    def deduplicate(self) -> int:
        """
        Supprime les doublons (même signature). Usage ObserverAgent.
        Retourne le nombre de doublons supprimés.
        """
        # TODO Sprint V8-08 : ObserverAgent appellera cette méthode périodiquement
        return 0

    # ── Helpers privés ────────────────────────────────────────────────

    def _extract_functions(self, code: str):
        """Extrait les fonctions via ast. Retourne [(name, signature, body)]."""
        results = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return results

        lines = code.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            name = node.name
            args = ast.unparse(node.args) if hasattr(ast, "unparse") else ""
            returns = (f" -> {ast.unparse(node.returns)}"
                       if node.returns and hasattr(ast, "unparse") else "")
            signature = f"def {name}({args}){returns}:"
            # Extraire le corps depuis les lignes source
            start = node.lineno - 1
            end = node.end_lineno if hasattr(node, "end_lineno") else start + 20
            body = "\n".join(lines[start:end])
            results.append((name, signature, body))
        return results

    def _extract_summary(self, body: str) -> str:
        """Extrait docstring ou première ligne. ≤ 200 chars."""
        lines = body.strip().splitlines()
        in_doc = False
        summary = []
        for line in lines[1:]:  # Sauter "def ..."
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.startswith("'''"):
                in_doc = not in_doc
                content = stripped.strip('"""').strip("'''").strip()
                if content:
                    summary.append(content)
                continue
            if in_doc:
                summary.append(stripped)
        result = " ".join(summary)[:200]
        return result or (lines[0][:200] if lines else "")

    def _truncate_body(self, body: str, max_lines: int) -> str:
        lines = body.splitlines()
        if len(lines) <= max_lines:
            return body
        truncated = lines[:max_lines]
        truncated.append(f"# ... ({len(lines) - max_lines} lignes tronquées)")
        return "\n".join(truncated)

    def _render_minimal(self, skills: List[Skill]) -> str:
        """Fallback si budget dépassé : signature + résumé uniquement."""
        lines = ["# Signatures de skills pertinents\n"]
        for s in skills:
            lines.append(f"- `{s.signature}`  # {s.body_summary}")
        return "\n".join(lines)
```

---

## Patch `core/memory_engine.py`

```python
# Dans _VALID_COLLECTIONS, ajouter :
_VALID_COLLECTIONS = frozenset({
    "lcca_solutions", "lcca_context", "lcca_failures",
    "lcca_patches", "lcca_specs",
    "lcca_skills",     # V8 — Skill Library
    "lcca_receipts",   # V8 — Audit trail A2A
})
```

---

## Ajouts `config.py`

```python
# V8 — Agents
AGENT_MIN_QUALITY_SCORE = 70       # Seuil qualité pour stockage skill
SKILL_MAX_BODY_LINES = 20          # Max lignes affichées dans le prompt
SKILL_MAX_PER_PROMPT = 3           # Max skills injectés par prompt
```

---

## Checklist des tests (`tests/test_skill_library.py`)

### TestSkillExtraction
- [ ] `test_extract_functions_from_code` — extrait 2 fonctions d'un code avec 2 defs
- [ ] `test_extract_no_functions_from_empty` — "" → []
- [ ] `test_extract_summary_from_docstring` — docstring extraite correctement
- [ ] `test_extract_summary_fallback_first_line` — sans docstring → première ligne

### TestSkillStore
- [ ] `test_store_requires_valid_receipt` — receipt invalide (tampered) → False
- [ ] `test_store_with_valid_receipt` — receipt valide → True + memory.store appelé
- [ ] `test_extract_and_store_counts_functions` — 3 defs → 3 tentatives store

### TestSkillSearch
- [ ] `test_search_returns_list` — résultat toujours une list (même si erreur mémoire)
- [ ] `test_search_failure_returns_empty` — MemoryEngine lève → []

### TestSkillPromptRendering
- [ ] `test_render_as_prompt_max_3` — 10 skills → seulement 3 dans le prompt
- [ ] `test_render_empty_returns_empty_string` — [] → ""
- [ ] `test_prompt_budget_respected` — prompt > MAX_PROMPT_CHARS → version minimale
- [ ] `test_truncate_body_adds_comment` — corps 30 lignes → commentaire "(X lignes tronquées)"
- [ ] `test_inject_skill_as_module` — exec dans namespace → fonction disponible

---

## Nouveauté : `novelty_score` dans SkillLibrary

```python
# Méthode optionnelle — utilisée par KarpathyLoop (Sprint V8-07)
def novelty_score(self, candidate_code: str, previous_codes: List[str]) -> float:
    """
    1.0 = entièrement nouveau, 0.0 = déjà vu.
    Empêche KarpathyLoop de converger vers un optimum local déjà exploré.
    """
    import difflib
    if not previous_codes:
        return 1.0
    similarities = [
        difflib.SequenceMatcher(None, candidate_code, p).ratio()
        for p in previous_codes
    ]
    return 1.0 - max(similarities)
```

---

## Notes

- **Déduplication** : `deduplicate()` est un stub V8.0 — implémentée par ObserverAgent en V8.1.
- **`_search_collection`** : hook privé sur MemoryEngine pour accéder directement à `lcca_skills`. Si non disponible → `search()` retourne `[]` (graceful degradation).
- **`ast.unparse`** disponible Python 3.9+. Le projet cible Python 3.11+ (002-tech-context) — pas de fallback nécessaire.
