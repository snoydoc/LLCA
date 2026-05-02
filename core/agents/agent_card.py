# -*- coding: utf-8-sig -*-
"""
LCCA V8 -- Identite et contrats des agents.

Chaque agent expose une AgentCard avec ses capabilities et sa RecoveryPolicy.
AgentRegistry = lookup centralise des AgentCards disponibles.

V8-Regle-20 : aucun agent ne modifie core/ directement.
V8-Regle-21 : toute communication passe par A2ALocalBus (pas d'import ici).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Capabilities reconnues du systeme V8
# ---------------------------------------------------------------------------
VALID_CAPABILITIES = frozenset({
    "planning",
    "decomposition",
    "code_generation",
    "ast_patching",
    "validation",
    "static_analysis",
    "sandbox_execution",
    "metric_collection",
    "memory_search",
    "memory_store",
    "skill_extraction",
    "skill_injection",
    "receipt_signing",
    "error_reflection",
    "maintenance",
    "llm_generation",       # V8-08 : CoderAgent genere via LLMGenerator
    "external_curation",    # V9.1 : EducatorAgent
    "skill_ingestion",      # V9.1 : EducatorAgent
    "github_fetch",         # V9.1 : EducatorAgent
    "llm_review",           # V9-08 : ReviewerAgent analyse LLM qualite code
})

# ---------------------------------------------------------------------------
# Allowlist MCP par agent (V8-Regle-20 : enforcement statique)
# Aucun agent ne peut appeler un tool qui n'est pas dans sa liste.
# ---------------------------------------------------------------------------
AGENT_MCP_ALLOWLIST: Dict[str, frozenset] = {
    "architect":  frozenset({"memory_search", "project_search", "generate_spec"}),
    "coder":      frozenset({"edit_batch", "memory_search"}),
    "reviewer":   frozenset({"validate_spec", "analyze_error", "memory_search"}),
    "tester":     frozenset({"sandbox_run", "evaluate_quality"}),
    "observer":   frozenset({"memory_search", "memory_store"}),
    "nl_adapter": frozenset(),
    "educator":   frozenset(),  # V9.1 : pas de tool MCP direct (passe par educator_status)
}


# ---------------------------------------------------------------------------
# RecoveryPolicy
# ---------------------------------------------------------------------------
@dataclass
class RecoveryPolicy:
    """
    Politique de recuperation d'un agent en cas d'echec.

    on_failure : "rollback" | "retry" | "escalate"
        - rollback  : annuler la tache, signaler l'echec
        - retry     : retenter jusqu'a max_retries
        - escalate  : transmettre a fallback_agent
    retry_conditions : liste de types d'erreurs retryables (vide = toutes)
    """

    max_retries: int = 1
    retry_delay_sec: float = 0.5
    fallback_agent: Optional[str] = None
    on_failure: str = "rollback"
    retry_conditions: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        assert self.on_failure in ("rollback", "retry", "escalate"), (
            "on_failure invalide: %s — valeurs acceptees : rollback, retry, escalate"
            % self.on_failure
        )

    def should_retry(self, error_type: str, attempt: int) -> bool:
        """Retourne True si l'agent doit retenter apres cette erreur."""
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
            "retry_conditions": list(self.retry_conditions),
        }


# ---------------------------------------------------------------------------
# AgentCard
# ---------------------------------------------------------------------------
@dataclass
class AgentCard:
    """
    Identite publique d'un agent V8.

    Utilisee par A2ALocalBus pour router et valider les messages.
    Immuable apres instanciation (validation dans __post_init__).
    """

    name: str
    version: str
    capabilities: List[str]
    mcp_tools: frozenset
    recovery_policy: RecoveryPolicy
    description: str = ""

    def __post_init__(self) -> None:
        assert self.name in AGENT_MCP_ALLOWLIST, (
            "Agent non enregistre dans AGENT_MCP_ALLOWLIST: %s" % self.name
        )
        for cap in self.capabilities:
            assert cap in VALID_CAPABILITIES, (
                "Capability inconnue: %s" % cap
            )

    def can_use_tool(self, tool: str) -> bool:
        """Verifie si l'agent a le droit d'utiliser ce tool MCP."""
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


# ---------------------------------------------------------------------------
# Politiques par defaut (une par agent)
# ---------------------------------------------------------------------------
ARCHITECT_POLICY = RecoveryPolicy(
    max_retries=2,
    on_failure="escalate",
    fallback_agent=None,   # Architect est le dernier recours
)

CODER_POLICY = RecoveryPolicy(
    max_retries=1,
    on_failure="rollback",
    fallback_agent="architect",
    retry_conditions=["SyntaxError"],
)

REVIEWER_POLICY = RecoveryPolicy(
    max_retries=0,
    on_failure="escalate",
    fallback_agent="architect",
)

TESTER_POLICY = RecoveryPolicy(
    max_retries=2,
    on_failure="retry",
    retry_conditions=["Timeout", "ResourceExhausted"],
)

OBSERVER_POLICY = RecoveryPolicy(
    max_retries=0,
    on_failure="rollback",
)


# ---------------------------------------------------------------------------
# AgentRegistry
# ---------------------------------------------------------------------------
class AgentRegistry:
    """
    Registre global des AgentCards disponibles.

    Pattern : factory classmethod AgentRegistry.default()
    -> pas de singleton global pour rester testable facilement.
    """

    def __init__(self) -> None:
        self._cards: Dict[str, AgentCard] = {}

    def register(self, card: AgentCard) -> None:
        """Enregistre une AgentCard. Ecrase l'existante si meme nom."""
        self._cards[card.name] = card

    def get(self, name: str) -> Optional[AgentCard]:
        """Retourne la carte de l'agent ou None."""
        return self._cards.get(name)

    def all_agents(self) -> List[str]:
        """Liste des noms d'agents enregistres."""
        return list(self._cards.keys())

    def can_use_tool(self, agent_name: str, tool: str) -> bool:
        """Verifie si l'agent peut utiliser ce tool (safe : retourne False si absent)."""
        card = self.get(agent_name)
        return card is not None and card.can_use_tool(tool)

    @classmethod
    def default(cls) -> "AgentRegistry":
        """Registry pre-peuplee avec les 5 agents V8 de base."""
        registry = cls()

        registry.register(AgentCard(
            name="architect",
            version="8.0.0",
            capabilities=["planning", "decomposition", "memory_search"],
            mcp_tools=AGENT_MCP_ALLOWLIST["architect"],
            recovery_policy=ARCHITECT_POLICY,
            description="Planifie et decompose les taches en sous-contrats A2A",
        ))

        registry.register(AgentCard(
            name="coder",
            version="8.0.0",
            capabilities=["code_generation", "ast_patching", "skill_injection"],
            mcp_tools=AGENT_MCP_ALLOWLIST["coder"],
            recovery_policy=CODER_POLICY,
            description="Genere le code et applique les patches ACID",
        ))

        registry.register(AgentCard(
            name="reviewer",
            version="8.0.0",
            capabilities=["validation", "static_analysis", "error_reflection"],
            mcp_tools=AGENT_MCP_ALLOWLIST["reviewer"],
            recovery_policy=REVIEWER_POLICY,
            description="Valide la coherence et detecte les regressions",
        ))

        registry.register(AgentCard(
            name="tester",
            version="8.0.0",
            capabilities=["sandbox_execution", "metric_collection", "receipt_signing"],
            mcp_tools=AGENT_MCP_ALLOWLIST["tester"],
            recovery_policy=TESTER_POLICY,
            description="Execute le sandbox et produit les ExecutionReceipts",
        ))

        registry.register(AgentCard(
            name="observer",
            version="8.0.0",
            capabilities=["maintenance", "memory_search", "memory_store"],
            mcp_tools=AGENT_MCP_ALLOWLIST["observer"],
            recovery_policy=OBSERVER_POLICY,
            description="Maintenance memoire : dedoublonnage skills, archivage receipts",
        ))

        return registry
