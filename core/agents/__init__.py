# -*- coding: utf-8-sig -*-
"""
LCCA V8 -- Package agents.
Contient les agents cognitifs du systeme multi-agent V8.

Agents disponibles :
    - ArchitectAgent  (Sprint V8-03) ✅
    - CoderAgent      (Sprint V8-03) ✅
    - ReviewerAgent   (Sprint V8-04) ✅
    - TesterAgent     (Sprint V8-04) ✅
    - ObserverAgent   (Sprint V8-07) ✅
    - EducatorAgent   (ED-01)        ✅

Sous-modules Reviewer (REFACTO-09) :
    - ReviewerValidator  -- _check_syntax, _build_reflection
    - ReviewerLlmAnalyzer -- analyse qualite LLM (quality_score, issues, suggestions)

Sous-modules Observer (REFACTO-08) :
    - ObserverReporter -- make_report_id, should_archive, archive_old_receipts, store_snapshot

Sous-modules Educator (REFACTO-08) :
    - EducatorIngester -- process_repo, ingest, _extract_symbols
    - EducatorCurator  -- run_curation, run_diff, export_sft_pairs, deprecate_stale_skills

Sous-modules Coder (REFACTO-07) :
    - CoderBuilder    -- CODER_SYSTEM, build_coder_prompt, format_skills_context, build_patch

Sous-modules Architect (REFACTO-06) :
    - ArchitectDecomposer -- detection domaine, decomposition heuristique + LLM, parsing JSON

Sous-modules Tester (REFACTO-05) :
    - TesterReceiptBuilder -- construction, signature et persistance des ExecutionReceipts

Sous-modules Educator (REFACTO-02) :
    - EducatorGitHub  -- couche reseau GitHub
    - EducatorFilter  -- 7 regles de filtrage LCCA

Sous-modules Observer (REFACTO-03) :
    - ObserverAnalyzer -- detection low_quality, duplicates, snapshot

Sous-modules Orchestrateur (REFACTO-04) :
    - KarpathyLoop   -- boucle Architect->Coder->Reviewer->Tester
    - LoopResult     -- resultat intermediaire de la boucle

Bus et contrats :
    - A2ALocalBus     (Sprint V8-01)
    - A2AMessage      (Sprint V8-01)
    - TaskContract    (Sprint V8-01)

Cards et registry :
    - AgentCard       (Sprint V8-02)
    - RecoveryPolicy  (Sprint V8-02)
    - AgentRegistry   (Sprint V8-02)

Base :
    - BaseAgent       (Sprint V8-03) ✅
    - AgentResult     (Sprint V8-03) ✅
"""

from .a2a_bus import A2ALocalBus, A2AMessage, TaskContract
from .agent_card import AgentCard, AgentRegistry, RecoveryPolicy
from .base_agent import AgentResult, BaseAgent
from .architect_agent import ArchitectAgent
from .coder_agent import CoderAgent
from .reviewer_agent import ReviewerAgent
from .reviewer_validator import _check_syntax, _build_reflection  # REFACTO-09
from .reviewer_analyzer import ReviewerLlmAnalyzer                # REFACTO-09
from .tester_agent import TesterAgent
from .observer_agent import ObserverAgent
from .architect_decomposer import ArchitectDecomposer  # REFACTO-06
from .coder_builder import build_coder_prompt, format_skills_context, build_patch  # REFACTO-07
from .observer_reporter import ObserverReporter, make_report_id, should_archive  # REFACTO-08
from .educator_ingester import EducatorIngester  # REFACTO-08
from .educator_curator import EducatorCurator    # REFACTO-08
from .tester_runner import TesterReceiptBuilder  # REFACTO-05
from .observer_analyzer import ObserverAnalyzer  # REFACTO-03
from .orchestrator_loop import KarpathyLoop, LoopResult  # REFACTO-04
from .educator_agent import EducatorAgent
from .educator_github import EducatorGitHub
from .educator_filter import EducatorFilter
from .agent_orchestrator import AgentOrchestrator, OrchestratorResult
from core.skill_library import SkillLibrary, SkillEntry

__all__ = [
    # V8-01
    "A2ALocalBus",
    "A2AMessage",
    "TaskContract",
    # V8-02
    "AgentCard",
    "AgentRegistry",
    "RecoveryPolicy",
    # V8-03
    "BaseAgent",
    "AgentResult",
    "ArchitectAgent",
    "CoderAgent",
    # V8-04
    "ReviewerAgent",
    "TesterAgent",
    # REFACTO-09
    "ReviewerLlmAnalyzer",
    "_check_syntax",
    "_build_reflection",
    # V8-07
    "ObserverAgent",
    # REFACTO-06
    "ArchitectDecomposer",
    # REFACTO-07
    "build_coder_prompt",
    "format_skills_context",
    "build_patch",
    # REFACTO-08
    "ObserverReporter",
    "make_report_id",
    "should_archive",
    "EducatorIngester",
    "EducatorCurator",
    # REFACTO-05
    "TesterReceiptBuilder",
    # REFACTO-03
    "ObserverAnalyzer",
    # REFACTO-04
    "KarpathyLoop",
    "LoopResult",
    # V9.1
    "EducatorAgent",
    # REFACTO-02
    "EducatorGitHub",
    "EducatorFilter",
    # V8-05
    "SkillLibrary",
    "SkillEntry",
    # V8-06
    "AgentOrchestrator",
    "OrchestratorResult",
]
