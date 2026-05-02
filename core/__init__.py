# -*- coding: utf-8-sig -*-
"""LCCA V8 Core Package.
Sprint 14 : Spec Layer Core.
Sprint 15 : Spec Layer Integration.
Sprint 20 : Migration SpecEntry V7.2 (VALID_DOMAINS, VALID_GENERATED_BY, champs V7.2).
Sprint 22 : Cleanup legacy -- suppression SpecValidationResult.
V8-01    : A2A Bus SQLite3 + TaskContract + ReceiptStore.
"""

from .transaction_manager import TransactionManager
from .ast_indexer import ASTIndexer, Symbol, FileIndex
from .smart_patcher import SmartPatcher
from .dependency_graph import DependencyGraph
from .planner import Planner, MultiFilePlanner, Plan, PatchOperation, PlannedOperation, OpPriority
from .orchestrator import Orchestrator, LCCAV5Fusion
from .dsl_parser import DSLParser, Intent
from .file_selector import FileSelector
from .mempalace_client import MemPalaceClient, MemoryEntry
from .context_assembler import ContextAssembler
# from .mempalace_adapter import ExistingMemPalaceAdapter  # MIG-02 archivé
from .recovery_service import RecoveryService
from .executor import Executor
from .executor import ValidationResult as ExecutorValidationResult
from .error_analyzer import ErrorAnalyzer, ErrorReport
# from .orchestrator_medi import MediBotOrchestrator  # MIG-02 archivé
from .llm_generator import (
    LLMGenerator, GenerationResult, OllamaClient,
    PromptBuilder, CodeExtractor, FallbackGenerator,
)
from .nl_parser import NLParser, NLIntent, NLPromptBuilder, NLIntentExtractor
from .nl_orchestrator import NLOrchestrator, NLResult, NLSession
from .code_evaluator import CodeEvaluator, EvaluationResult, CriterionScore
from .spec_entry import SpecEntry, make_spec_id, VALID_DOMAINS, VALID_GENERATED_BY
from .cognitive_patterns import (
    CognitivePattern, DeepReasoningPattern,
    SpecFormatterPattern, SpecValidatorPattern,
)
from .spec_validator import RuleChecker, RULE_REGISTRY, SpecValidatorService
from .spec_generator import SpecGeneratorService
from .spec_complexity import SpecComplexityEstimator
from .spec_promoter import SpecPromoter

# ── V8 -- A2A Bus + Receipts ──────────────────────────────────────────────────
from .agents.a2a_bus import A2ALocalBus, A2AMessage, TaskContract
from .receipt_store import ExecutionReceipt, sign_receipt, verify_receipt

__version__ = "8.0.0-alpha"
__author__ = "LCCA"

__all__ = [
    # V5/V7 -- conserves integralement
    "TransactionManager", "ASTIndexer", "Symbol", "FileIndex",
    "SmartPatcher", "DependencyGraph",
    "Planner", "MultiFilePlanner", "Plan", "PatchOperation", "PlannedOperation", "OpPriority",
    "Orchestrator", "LCCAV5Fusion",
    "DSLParser", "Intent", "FileSelector",
    "MemPalaceClient", "MemoryEntry", "ContextAssembler",
    "RecoveryService", "Executor", "ExecutorValidationResult",
    "ErrorAnalyzer", "ErrorReport",
    "LLMGenerator", "GenerationResult", "OllamaClient",
    "PromptBuilder", "CodeExtractor", "FallbackGenerator",
    "NLParser", "NLIntent", "NLPromptBuilder", "NLIntentExtractor",
    "NLOrchestrator", "NLResult", "NLSession",
    "CodeEvaluator", "EvaluationResult", "CriterionScore",
    "SpecEntry", "make_spec_id", "VALID_DOMAINS", "VALID_GENERATED_BY",
    "CognitivePattern", "DeepReasoningPattern", "SpecFormatterPattern", "SpecValidatorPattern",
    "RuleChecker", "RULE_REGISTRY", "SpecValidatorService",
    "SpecGeneratorService",
    "SpecComplexityEstimator",
    "SpecPromoter",
    # V8 -- nouveaux modules
    "A2ALocalBus", "A2AMessage", "TaskContract",
    "ExecutionReceipt", "sign_receipt", "verify_receipt",
]
