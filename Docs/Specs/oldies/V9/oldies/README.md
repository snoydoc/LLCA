# LCCA V9 — Dossier de Spécifications Techniques
<!-- AI-READY | LCCA V9 Specs | Version 9.0.0-draft | 2026-04-20 -->

Rédigé le **2026-04-20** pour review par une IA de codage avant implémentation.  
Auteur : analyse automatique de la codebase V8 + recherches approfondies.

---

## Contenu du dossier

| Fichier | Périmètre |
|---------|-----------|
| `README.md` | Index + contexte global (ce fichier) |
| `spec-v9-01-llm-performance.md` | Axe 2.1 — Optimisation LLM (Qwen quantification, tri-modèle, streaming, keep_alive) |
| `spec-v9-02-llm-quality.md` | Axe 2.2 — Qualité des réponses (few-shot, boucle de correction, AST context, JSON mode) |
| `spec-v9-03-agentic-rag.md` | Axe 2.3 — LLM + Web ciblé (Repo-RAG, web auto, HyDE, doc retrieval) |
| `spec-v9-04-training-pipeline.md` | Axe 2.4 — Entraînement LCCA (SFT, GRPO, pipeline continu) |
| `spec-v9-05-creative-agents.md` | Axe 3 — Agents créatifs (QAAgent, DocAgent, mode Pair Programmer, Analytics, TTS, Mémoire épisodique) |

---

## Contexte V8 (état actuel)

LCCA est un agent de codage local transactionnel (Python + Electron/React).

**Architecture en place :**
- `core/agents/` — Pipeline multi-agent V8 : ArchitectAgent → CoderAgent → ReviewerAgent → TesterAgent → ObserverAgent
- `AgentOrchestrator` — KarpathyLoop (max 20 itérations, stagnation détectée à 3)
- `WebSearchEngine` — Multi-moteurs (DDG + Brave + Wikipedia), cache TTL adaptatif
- `MemoryEngine` — 6 collections ChromaDB (lcca_solutions, lcca_failures, lcca_context, lcca_patches, lcca_specs, lcca_skills)
- `SkillLibrary` — Stockage/retrieval de fonctions Python validées
- `McpServer` — JSON-RPC 2.0 stdio, 12 tools
- `SpecGenerator` / `SpecValidator` — Spec Layer V7.2 (15 règles)
- UI Electron/React — Chat avec streaming tokens, Command Palette, ContextPanel

**Stack LLM :**
- Modèle léger : `qwen2.5-coder:7b` (60s/génération CPU, ~4GB RAM)
- Modèle lourd : `qwen2.5-coder:14b` (180s/génération CPU, ~9GB RAM)
- Machine : Lenovo P50 — 16GB RAM, CPU uniquement pour Ollama (pas de GPU dédié)

**Tests :** 525+ passing, 0 failed (au 2026-04-20)

---

## Principes directeurs V9

1. **Pas de rupture de contrat** — toute modification préserve les interfaces existantes (rétrocompat)
2. **Silencieux en cas d'échec** — tout nouveau composant doit gérer ses exceptions sans crasher le flux principal
3. **Testable dès la conception** — chaque spec inclut les fixtures et assertions attendues
4. **CPU-first** — les optimisations sont conçues pour Lenovo P50 sans GPU dédié
5. **Incrémental** — chaque sprint est indépendant et déployable sans les autres

---

## Priorités d'implémentation

| Priorité | Sprint | Titre | Effort estimé |
|----------|--------|-------|---------------|
| P0 | V9-01-A | Quantification Q4_K_M + keep_alive | 0.5 jour |
| P0 | V9-01-B | Tri-modèle adaptatif (3b/7b/14b) | 1 jour |
| P0 | V9-02-A | Few-shot SkillLibrary dans PromptBuilder | 1 jour |
| P0 | V9-02-B | Boucle de correction post-génération | 1 jour |
| P1 | V9-03-A | Repository-RAG CoderAgent | 2 jours |
| P1 | V9-02-C | AST context dans SpecGenerator | 1 jour |
| P1 | V9-03-B | Web search auto dans ArchitectAgent | 1.5 jour |
| P2 | V9-04-A | Pipeline collecte données SFT | 2 jours |
| P2 | V9-05-A | QAAgent autonome | 2 jours |
| P2 | V9-05-B | DocAgent auto-documentation | 2 jours |
| P3 | V9-04-B | GRPO fine-tuning | 3 jours |
| P3 | V9-05-C | Mode Pair Programmer (HITL) | 2 jours |
| P3 | V9-03-C | HyDE memory search | 1 jour |
| P4 | V9-05-D | Dashboard Analytics | 2 jours |
| P4 | V9-05-E | Mémoire épisodique (graphe) | 3 jours |
| P4 | V9-05-F | TTS local (Kokoro/Piper) | 1 jour |
