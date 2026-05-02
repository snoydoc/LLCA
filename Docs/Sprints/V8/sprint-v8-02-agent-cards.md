# Sprint V8-02 — AgentCard + RecoveryPolicy + Registry
<!-- AI-READY | Sprint V8 | Phase alpha | 2026-04-20 -->

## Objectif

Définir l'identité et le contrat de chaque agent V8.  
`AgentCard` = interface publique d'un agent (capabilities, politiques, schémas).  
`RecoveryPolicy` = que faire en cas d'échec (rollback, retry, escalade).  
`AgentRegistry` = lookup des agents disponibles.

Ce sprint ne crée pas encore les agents — il crée leur **contrat structurel**.

---

## Fichiers à créer / modifier

| # | Fichier | Opération |
|---|---------|-----------|
| 1 | `core/agents/agent_card.py` | CREATE — AgentCard + RecoveryPolicy + AgentRegistry |
| 2 | `core/agents/__init__.py` | PATCH — exporter AgentCard, RecoveryPolicy, AgentRegistry |
| 3 | `tests/test_agent_cards.py` | CREATE — 10 tests |

---

## Spécification : `core/agents/agent_card.py`

```python
# core/agents/agent_card.py
"""
Identité et contrats des agents V8.
Chaque agent expose une AgentCard avec ses capabilities et sa RecoveryPolicy.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict

# Capabilities reconnues du système
VALID_CAPABILITIES = frozenset({
    "planning", "decomposition", "code_generation", "ast_patching",
    "validation", "static_analysis", "sandbox_execution", "metric_collection",
    "memory_search", "memory_store", "skill_extraction", "skill_injection",
    "receipt_signing", "error_reflection", "maintenance"
})

# Tools MCP autorisés par agent (enforcement intentionnel — Règle 20)
AGENT_MCP_ALLOWLIST: Dict[str, frozenset] = {
    "architect":  frozenset({"memory_search", "project_search", "generate_spec"}),
    "coder":      frozenset({"edit_batch", "memory_search"}),
    "reviewer":   frozenset({"validate_spec", "analyze_error", "memory_search"}),
    "tester":     frozenset({"sandbox_run", "evaluate_quality"}),
    "observer":   frozenset({"memory_search", "memory_store"}),
    "nl_adapter": frozenset({}),
}


@dataclass
class RecoveryPolicy:
    """
    Politique de récupération par agent.
    Exposée dans AgentCard.on_failure.
    """
    max_retries: int = 1
    retry_delay_sec: float = 0.5
    fallback_agent: Optional[str] = None
    on_failure: str = "rollback"              # "rollback" | "retry" | "escalate"
    retry_conditions: List[str] = field(default_factory=list)

    def __post_init__(self):
        assert self.on_failure in ("rollback", "retry", "escalate"), \
            f"on_failure invalide: {self.on_failure}"

    def should_retry(self, error_type: str, attempt: int) -> bool:
        if self.on_failure != "retry":
            return False
        if attempt >= self.max_retries:
            return False
        return not self.retry_conditions or error_type in self.retry_conditions

    def to_dict(self) -> dict:
        return {
            "max_retries": self.max_retries,
            "retry_delay_sec": self.retry_delay_sec,
            "fallback_agent": self.fallback_agent,
            "on_failure": self.on_failure,
            "retry_conditions": self.retry_conditions,
        }


@dataclass
class AgentCard:
    """
    Identité publique d'un agent.
    Utilisée par A2ALocalBus pour router + valider les messages.
    """
    name: str
    version: str
    capabilities: List[str]
    mcp_tools: frozenset
    recovery_policy: RecoveryPolicy
    description: str = ""

    def __post_init__(self):
        assert self.name in AGENT_MCP_ALLOWLIST, f"Agent non enregistré: {self.name}"
        for cap in self.capabilities:
            assert cap in VALID_CAPABILITIES, f"Capability inconnue: {cap}"

    def can_use_tool(self, tool: str) -> bool:
        return tool in self.mcp_tools

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "capabilities": list(self.capabilities),
            "mcp_tools": sorted(self.mcp_tools),
            "recovery_policy": self.recovery_policy.to_dict(),
            "description": self.description,
        }


# ── Politiques par défaut ────────────────────────────────────────────
ARCHITECT_POLICY = RecoveryPolicy(
    max_retries=2, on_failure="escalate",
    fallback_agent=None  # L'Architect est le dernier recours
)
CODER_POLICY = RecoveryPolicy(
    max_retries=1, on_failure="rollback",
    fallback_agent="architect",
    retry_conditions=["SyntaxError"]
)
REVIEWER_POLICY = RecoveryPolicy(
    max_retries=0, on_failure="escalate",
    fallback_agent="architect"
)
TESTER_POLICY = RecoveryPolicy(
    max_retries=2, on_failure="retry",
    retry_conditions=["Timeout", "ResourceExhausted"]
)
OBSERVER_POLICY = RecoveryPolicy(
    max_retries=0, on_failure="rollback"
)


# ── Registry ─────────────────────────────────────────────────────────
class AgentRegistry:
    """
    Registre global des AgentCards disponibles.
    Singleton léger — instancié au boot de AgentOrchestrator.
    """
    def __init__(self):
        self._cards: Dict[str, AgentCard] = {}

    def register(self, card: AgentCard):
        self._cards[card.name] = card

    def get(self, name: str) -> Optional[AgentCard]:
        return self._cards.get(name)

    def all_agents(self) -> List[str]:
        return list(self._cards.keys())

    def can_use_tool(self, agent_name: str, tool: str) -> bool:
        card = self.get(agent_name)
        return card is not None and card.can_use_tool(tool)

    @classmethod
    def default(cls) -> "AgentRegistry":
        """Registry pré-peuplée avec les 5 agents V8."""
        registry = cls()
        registry.register(AgentCard(
            name="architect", version="8.0.0",
            capabilities=["planning", "decomposition", "memory_search"],
            mcp_tools=AGENT_MCP_ALLOWLIST["architect"],
            recovery_policy=ARCHITECT_POLICY,
            description="Planifie et décompose les tâches en sous-contrats A2A"
        ))
        registry.register(AgentCard(
            name="coder", version="8.0.0",
            capabilities=["code_generation", "ast_patching", "skill_injection"],
            mcp_tools=AGENT_MCP_ALLOWLIST["coder"],
            recovery_policy=CODER_POLICY,
            description="Génère le code et applique les patches ACID"
        ))
        registry.register(AgentCard(
            name="reviewer", version="8.0.0",
            capabilities=["validation", "static_analysis", "error_reflection"],
            mcp_tools=AGENT_MCP_ALLOWLIST["reviewer"],
            recovery_policy=REVIEWER_POLICY,
            description="Valide la cohérence et détecte les régressions"
        ))
        registry.register(AgentCard(
            name="tester", version="8.0.0",
            capabilities=["sandbox_execution", "metric_collection", "receipt_signing"],
            mcp_tools=AGENT_MCP_ALLOWLIST["tester"],
            recovery_policy=TESTER_POLICY,
            description="Exécute le sandbox et produit les ExecutionReceipts"
        ))
        registry.register(AgentCard(
            name="observer", version="8.0.0",
            capabilities=["maintenance", "memory_search", "memory_store"],
            mcp_tools=AGENT_MCP_ALLOWLIST["observer"],
            recovery_policy=OBSERVER_POLICY,
            description="Maintenance mémoire : dédoublonnage skills, archivage receipts"
        ))
        return registry
```

---

## Checklist des tests (`tests/test_agent_cards.py`)

### TestRecoveryPolicy
- [ ] `test_should_retry_on_matching_error` — SyntaxError + coder → True
- [ ] `test_no_retry_if_max_reached` — attempt >= max_retries → False
- [ ] `test_rollback_policy_never_retries` — on_failure="rollback" → False toujours
- [ ] `test_invalid_on_failure_raises` — "give_up" → AssertionError

### TestAgentCard
- [ ] `test_agent_card_to_dict` — tous les champs présents dans le dict
- [ ] `test_unknown_agent_raises` — name hors AGENT_MCP_ALLOWLIST → AssertionError
- [ ] `test_unknown_capability_raises` — capability hors VALID_CAPABILITIES → AssertionError
- [ ] `test_can_use_tool` — architect peut generate_spec, pas sandbox_run

### TestAgentRegistry
- [ ] `test_default_registry_has_5_agents` — architect, coder, reviewer, tester, observer
- [ ] `test_registry_can_use_tool` — architect peut "memory_search", coder ne peut pas "sandbox_run"

---

## Conventions
- `AGENT_MCP_ALLOWLIST` = enforcement statique (V8-Règle-20 : aucun agent ne modifie core/)
- Pas d'import de `A2ALocalBus` ici (dépendance unilatérale : bus → cards, pas l'inverse)
- `AgentRegistry.default()` = classmethod factory, pas de singleton global (testable)
