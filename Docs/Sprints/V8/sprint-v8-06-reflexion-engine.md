# Sprint V8-06 — ReflexionEngine + lcca_failures enrichi
<!-- AI-READY | Sprint V8 | Phase beta | 2026-04-20 -->

## Objectif

Implémenter le **pattern ExpeL** : les échecs génèrent des réflexions structurées réutilisables.  
Au lieu de répéter les mêmes erreurs, LCCA capitalise sur ses propres échecs via RAG.

> **Décision Addendum 3.1** : pas de collection `lcca_reflexions` séparée. Le champ `reflection` est ajouté aux entrées `lcca_failures`. Cohérence avec la collection existante.

> **V8-Règle-19** : les réflexions sont produites par ≥ 2 agents (Reviewer + Tester). L'AgentOrchestrator les combine avant stockage.

---

## Fichiers à créer / modifier

| # | Fichier | Opération |
|---|---------|-----------|
| 1 | `core/reflexion_engine.py` | CREATE |
| 2 | `core/memory_engine.py` | PATCH — `store_failure_with_reflection()` helper |
| 3 | `tests/test_reflexion_engine.py` | CREATE — 10 tests |

---

## Spécification : `core/reflexion_engine.py`

```python
# core/reflexion_engine.py
"""
ReflexionEngine V8 — Pattern ExpeL / Multi-Agent Reflexion.
Génère des réflexions structurées depuis les échecs, les stocke dans lcca_failures.
RAG sur lcca_failures pour injecter les échecs pertinents dans les futurs prompts.

V8-Règle-19 : les réflexions nécessitent consensus ≥ 2 agents avant stockage.
"""
import hashlib
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Optional

from core.memory_engine import MemoryEngine
from core.llm_generator import LLMGenerator
import config

log = logging.getLogger("lcca.reflexion")

_FAILURE_TYPES = frozenset({
    "SyntaxError", "LogicError", "Timeout", "ResourceExhausted",
    "ValidationError", "SandboxError", "Unknown"
})


@dataclass
class Reflexion:
    """
    Réflexion structurée sur un échec.
    Stockée dans lcca_failures avec le champ 'reflection'.
    """
    task_hash: str           # MD5 de l'intent
    failure_type: str        # Membre de _FAILURE_TYPES
    context: str             # Code ou intent qui a échoué (tronqué à 500 chars)
    reflection: str          # "J'ai oublié d'importer re pour le regex"
    fix: str                 # Le correctif appliqué (ou suggestion)
    verified: bool           # Le fix a-t-il passé sandbox ?
    agents: List[str] = field(default_factory=list)  # Agents ayant contribué

    def __post_init__(self):
        if self.failure_type not in _FAILURE_TYPES:
            self.failure_type = "Unknown"

    def to_dict(self) -> dict:
        return asdict(self)


class ReflexionEngine:
    """
    Génère, stocke, et retrouve des réflexions structurées.

    Usage typique :
        engine = ReflexionEngine()
        reflexion = engine.reflect(
            intent="ajouter JWT",
            error_output="SyntaxError: invalid syntax",
            failure_type="SyntaxError",
            code_that_failed="def validate_token(tok):",  # incomplet
            agent="tester",
        )
        engine.store(reflexion)
    """

    def __init__(
        self,
        memory: Optional[MemoryEngine] = None,
        generator: Optional[LLMGenerator] = None,
    ):
        self._memory = memory or MemoryEngine()
        self._generator = generator

    # ── Génération ────────────────────────────────────────────────────

    def reflect(
        self,
        intent: str,
        error_output: str,
        failure_type: str = "Unknown",
        code_that_failed: str = "",
        agent: str = "unknown",
        fix_applied: str = "",
        verified: bool = False,
    ) -> Reflexion:
        """
        Génère une réflexion via LLM ou fallback heuristique.
        Ne lève jamais — retourne toujours une Reflexion.
        """
        task_hash = hashlib.md5(intent.encode()).hexdigest()[:12]
        context = (code_that_failed or intent)[:500]

        # Génération LLM si disponible
        reflection_text = self._generate_reflection_text(
            intent=intent,
            error_output=error_output,
            context=context,
        )

        return Reflexion(
            task_hash=task_hash,
            failure_type=failure_type,
            context=context,
            reflection=reflection_text,
            fix=fix_applied,
            verified=verified,
            agents=[agent],
        )

    def reflect_on_failure(self, code: str, error_output: str, agent: str) -> str:
        """
        Façade légère pour les agents (Reviewer, Tester).
        Retourne uniquement le texte de réflexion.
        """
        intent = code[:200]  # Proxy : premières lignes comme intent
        r = self.reflect(
            intent=intent,
            error_output=error_output,
            code_that_failed=code,
            agent=agent,
        )
        return r.reflection

    def merge_agent_reflexions(
        self,
        reflexions: List[Reflexion],
        verified: bool = False,
    ) -> Optional[Reflexion]:
        """
        V8-Règle-19 : Combine ≥ 2 réflexions d'agents différents.
        Retourne None si < 2 agents.
        """
        if len(reflexions) < 2:
            log.warning("reflexion_engine.merge: < 2 agents, consensus impossible")
            return None

        agents = list({r.agents[0] for r in reflexions if r.agents})
        combined_text = " | ".join(
            f"[{r.agents[0]}] {r.reflection}" for r in reflexions
        )
        base = reflexions[0]
        return Reflexion(
            task_hash=base.task_hash,
            failure_type=base.failure_type,
            context=base.context,
            reflection=combined_text,
            fix=base.fix,
            verified=verified,
            agents=agents,
        )

    # ── Stockage ──────────────────────────────────────────────────────

    def store(self, reflexion: Reflexion) -> bool:
        """
        Stocke dans lcca_failures avec le champ 'reflection'.
        Silencieux en cas d'erreur (ne jamais bloquer le pipeline).
        """
        try:
            self._memory.store_failure(
                error_type=reflexion.failure_type,
                context=reflexion.context,
                extra_metadata={
                    "reflection": reflexion.reflection,
                    "fix": reflexion.fix,
                    "verified": str(reflexion.verified),
                    "agents": ",".join(reflexion.agents),
                    "task_hash": reflexion.task_hash,
                },
            )
            log.info("reflexion.store OK task_hash=%s agents=%s",
                     reflexion.task_hash, reflexion.agents)
            return True
        except Exception as exc:
            log.debug("reflexion.store error: %s", exc)
            return False

    # ── Recherche RAG ─────────────────────────────────────────────────

    def retrieve_relevant(self, intent: str, n: int = 3) -> List[Reflexion]:
        """
        RAG sur lcca_failures. Retourne les réflexions les plus similaires.
        Utilisé par ArchitectAgent pour éviter de répéter les mêmes erreurs.
        """
        try:
            results = self._memory.search(intent, n=n + 2)
            reflexions = []
            for entry in results.get("failures", []):
                meta = getattr(entry, "metadata", {}) or {}
                if "reflection" not in meta:
                    continue
                content = getattr(entry, "content", "") or ""
                reflexions.append(Reflexion(
                    task_hash=meta.get("task_hash", ""),
                    failure_type=meta.get("failure_type", "Unknown"),
                    context=content[:500],
                    reflection=meta.get("reflection", ""),
                    fix=meta.get("fix", ""),
                    verified=meta.get("verified", "False") == "True",
                    agents=meta.get("agents", "").split(","),
                ))
            return reflexions[:n]
        except Exception as exc:
            log.debug("reflexion.retrieve error: %s", exc)
            return []

    def render_as_context(self, reflexions: List[Reflexion]) -> str:
        """
        Formate les réflexions en contexte in-context pour le LLM.
        Pattern ExpeL : les échecs passés comme negative examples.
        """
        if not reflexions:
            return ""
        lines = ["# Échecs précédents à éviter\n"]
        for r in reflexions[:3]:  # Max 3 pour le budget contexte
            lines += [
                f"**Erreur** ({r.failure_type}): {r.context[:150]}",
                f"**Réflexion**: {r.reflection[:200]}",
                f"**Correctif**: {r.fix[:150] or 'non documenté'}\n",
            ]
        return "\n".join(lines)

    # ── Helpers ───────────────────────────────────────────────────────

    def _generate_reflection_text(self, intent: str, error_output: str, context: str) -> str:
        """Génère la réflexion via LLM ou fallback heuristique."""
        if self._generator is not None:
            try:
                system = (
                    "Tu es un expert en débogage Python. "
                    "Analyse l'erreur et génère une réflexion courte (≤ 2 phrases) "
                    "expliquant la cause racine et le correctif. Réponds en français."
                )
                user = (
                    f"Intent : {intent}\n"
                    f"Contexte code : {context[:300]}\n"
                    f"Erreur : {error_output[:300]}"
                )
                result = self._generator.generate_text(system, user)
                if isinstance(result, str) and result.strip():
                    return result.strip()[:500]
            except Exception as exc:
                log.debug("reflexion._generate_reflection LLM failed: %s", exc)

        # Fallback heuristique sans LLM
        error_short = error_output[:200] if error_output else "erreur inconnue"
        return f"Échec lors de '{intent[:100]}'. Erreur : {error_short}"
```

---

## Patch `core/memory_engine.py`

Ajouter la méthode helper `store_failure()` si elle n'existe pas :

```python
def store_failure(self, error_type: str, context: str, extra_metadata: dict = None) -> bool:
    """
    Helper pour stocker dans lcca_failures avec métadonnées enrichies (V8).
    """
    metadata = {"error_type": error_type, **(extra_metadata or {})}
    return self.store(
        collection="lcca_failures",
        content=context,
        metadata=metadata,
    )
```

---

## Checklist des tests (`tests/test_reflexion_engine.py`)

### TestReflexionGeneration
- [ ] `test_reflect_returns_reflexion` — retourne toujours une Reflexion
- [ ] `test_reflect_unknown_failure_type` — type inconnu → "Unknown"
- [ ] `test_reflect_on_failure_returns_string` — façade légère retourne str
- [ ] `test_reflect_no_llm_fallback` — sans générateur → heuristique (pas d'erreur)
- [ ] `test_context_truncated_to_500` — code 1000 chars → context[:500]

### TestReflexionMerge
- [ ] `test_merge_two_agents` — reviewer + tester → Reflexion merged, agents=["reviewer","tester"]
- [ ] `test_merge_single_agent_returns_none` — 1 seul agent → None (Règle 19)
- [ ] `test_merge_combined_text_contains_both` — texte merged contient "[reviewer]" ET "[tester]"

### TestReflexionStore
- [ ] `test_store_returns_true_on_success` — memory.store_failure appelé → True
- [ ] `test_store_failure_doesnt_raise` — mémoire indisponible → False, pas d'exception

### TestReflexionRetrieve
- [ ] `test_retrieve_returns_list` — résultat toujours List[Reflexion]
- [ ] `test_retrieve_filters_no_reflection_field` — entrées sans "reflection" ignorées
- [ ] `test_render_as_context_max_3` — 5 réflexions → max 3 dans le rendu
- [ ] `test_render_empty_returns_empty_string` — [] → ""

---

## Intégration dans le pipeline

L'AgentOrchestrator (Sprint V8-08) orchestrera le consensus :

```python
# Dans AgentOrchestrator._handle_rejection()
reflexions = [
    reviewer_reflexion,   # from ReviewerAgent payload
    tester_reflexion,     # from TesterAgent payload
]
merged = self._reflexion.merge_agent_reflexions(reflexions, verified=False)
if merged:
    self._reflexion.store(merged)
```

---

## Notes

- `store_failure()` sur MemoryEngine : vérifier que la méthode existe dans la V7.2. Si absent, l'ajouter comme wrapper de `store(collection="lcca_failures", ...)`.
- Le champ `agents` dans les métadonnées ChromaDB est sérialisé en CSV (`"reviewer,tester"`) car ChromaDB n'accepte que les types scalaires.
- **Pas de collection `lcca_reflexions`** — décision ferme de l'Addendum 3.1. Ne pas créer cette collection.
