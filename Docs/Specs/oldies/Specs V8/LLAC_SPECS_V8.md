============================================================
Fichier : 22-roadmap-v8-cognitive-fabric.md
============================================================

# Roadmap V8 — Cognitive Fabric : Du Tool à l'Agent Autonomique
&lt;!-- AI-READY | Roadmap architecture V8 | Version 8.0.0-alpha | 2026-04-18 --&gt;

## Vue d'ensemble

La V7 a intégré la **Spec Layer adaptative** (fichier 21). La V8 franchit le pas vers un **système cognitive autonomique** : LCCA n'est plus un outil que l'utilisateur pilote, mais une **fabric d'agents spécialisés** qui apprennent de leurs échecs, accumulent des compétences réutilisables, et s'auto-améliorent par feedback de sandbox.

&gt; **Principe fondateur V8** :  
&gt; ❌ V7 = l'utilisateur demande, LCCA exécute  
&gt; ✅ V8 = LCCA observe, propose, expérimente, conserve et réutilise

Cette roadmap s'appuie sur les paradigmes validés en production 2026 [^14^][^17^][^22^] : Skill Libraries (Voyager/SAGE), Multi-Agent Reflexion, A2A Protocol, et le Karpathy Loop.

---

## 1. Synthèse des recherches — Ce que la production valide en 2026

| Paradigme | Source clé | Applicabilité LCCA V8 |
|-----------|------------|----------------------|
| **Skill Library** | Voyager / SAGE [^14^] | Stockage de fonctions validées dans `lcca_skills` (réutilisation跨-tâches) |
| **Multi-Agent A2A** | Google A2A Protocol [^15^][^17^] | 4 agents locaux (Architect/Coder/Reviewer/Tester) communiquant par contrats structurés |
| **Reflexion persistante** | ExpeL / Multi-Agent Reflexion [^14^] | Journal structuré des échecs dans `lcca_failures` comme in-context examples |
| **Self-Play RL** | SWE-RL / DeepSWE [^22^] | Injection contrôlée de bugs dans sandbox + entraînement à la correction |
| **Verifiable Execution** | A2A best practices [^17^] | Chaque agent produit un "receipt" (preuve d'exécution) avant transfert |
| **Karpathy Loop** | Autoresearch loop [^14^] | `lcca improve` : boucle autonome generate→sandbox→evaluate→keep |

**Ce qu'on NE fait PAS** (hors scope local) :
- Fine-tuning de poids LLM (nécessite H100/cluster) → remplacé par in-context learning
- API cloud payantes → tout reste sur Ollama local
- Auto-modification du code de LCCA lui-même (risque safety) → amélioration des skills utilisateur uniquement

---

## 2. Architecture V8 — Cognitive Fabric
┌─────────────────────────────────────────────────────────────────────┐
│  COGNITIVE LAYER (V8)                                               │
│  ─────────────────────────────────────────────────────────────────  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────┐ │
│  │  Architect  │  │   Coder     │  │  Reviewer   │  │  Tester   │ │
│  │  (Planner)  │  │  (Executor) │  │  (Critic)   │  │ (Verify)  │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └─────┬─────┘ │
│         │                │                │               │       │
│         └────────────────┴────────────────┘               │       │
│                      A2A Local Bus                        │       │
│         (JSON task contracts + receipts)                  │       │
└─────────────────────────────────────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────────────┐
│  MEMORY FABRIC (V8)                                                 │
│  ─────────────────────────────────────────────────────────────────  │
│  lcca_skills        : Fonctions validées réutilisables (Voyager)   │
│  lcca_specs         : Spécifications architecturelles (V7)          │
│  lcca_failures      : Échecs + réflexions (ExpeL pattern)           │
│  lcca_receipts      : Preuves d'exécution A2A                │
│  lcca_solutions     : Solutions complètes (V7)                      │
└─────────────────────────────────────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────────────┐
│  LCCA V7 CORE (conservé intégralement)                              │
│  ─────────────────────────────────────────────────────────────────  │
│  TransactionManager │ SmartPatcher │ SandboxEngine │ CodeEvaluator  │
│  ASTIndexer         │ LLMGenerator │ MemPalace     │ RecoveryService│
└─────────────────────────────────────────────────────────────────────┘


---

## 3. Ce qu'il faut AJOUTER

### 3.1 Les 4 Agents A2A Locaux

Basé sur le protocole A2A de Google [^15^][^17^], adapté à un bus local (pas HTTP, mais queue Python ou fichiers JSON dans `memory/a2a/`).

#### Agent Card (spécification A2A)

Chaque agent expose une "carte d'identité" :

```python
# core/agents/agent_card.py
@dataclass
class AgentCard:
    name: str
    version: str
    capabilities: List[str]  # ["planning", "decomposition"]
    input_schema: Dict      # JSON schema des tâches acceptées
    output_schema: Dict     # JSON schema des livrables
    endpoint: str           # "local://bus/{name}" (pas HTTP)

Les 4 agents
| Agent         | Rôle                                                       | Outils MCP autorisés                               | Pattern cognitif      |
| ------------- | ---------------------------------------------------------- | -------------------------------------------------- | --------------------- |
| **Architect** | Décomposer la demande en sous-tâches, définir les contrats | `memory_search`, `project_search`, `generate_spec` | Deep reasoning        |
| **Coder**     | Générer le code, appliquer les patches ACID                | `edit_batch`, `memory_search` (skills)             | Spec formatter        |
| **Reviewer**  | Vérifier la cohérence, détecter les régressions            | `validate_spec`, `analyze_error`                   | Spec validator        |
| **Tester**    | Exécuter sandbox, mesurer, produire le receipt             | `sandbox_run`, `evaluate_quality`                  | Verifiable execution  |

Bus A2A local
# core/a2a_bus.py
class A2ALocalBus:
    """
    Bus de message local inter-agent. Pas de réseau.
    Les messages sont des fichiers JSON dans memory/a2a/inbox/{agent}/
    """
    def send(self, to: str, task: TaskContract) -> str:
        # Écriture atomique dans l'inbox cible
        pass
    
    def receive(self, agent: str, timeout: int = 30) -> Optional[TaskContract]:
        # Lecture non bloquante
        pass

3.2 Skill Library — lcca_skills
Pattern Voyager/SAGE adapté  : au lieu de jeter le code généré après usage, on extrait les fonctions réutilisables validées.
# core/skill_library.py
@dataclass
class Skill:
    skill_id: str           # hash du code
    name: str               # "validate_email"
    signature: str          # "def validate_email(email: str) -> bool:"
    body: str               # Code complet
    test_cases: List[dict]  # [{"input": "a@b.com", "expected": True}]
    source_spec: str        # spec_id d'origine
    usage_count: int        # Nombre de réutilisations
    success_rate: float     # Taux de réussite sandbox

class SkillLibrary:
    def search(self, query: str) -> List[Skill]:
        # Recherche sémantique dans MemPalace collection "lcca_skills"
        pass
    
    def store(self, skill: Skill):
        # Stockage si validation sandbox > 0.9
        pass
    
    def render_as_prompt(self, skills: List[Skill]) -> str:
        # Formate les skills en few-shot examples pour le LLM
        pass

Règle d'apprentissage : après chaque sandbox_run réussi, SkillExtractor analyse le code généré. Si une fonction est isolable, bien typée, et testée, elle est候选 pour lcca_skills.
3.3 Reflexion Persistante — lcca_reflexions
Basé sur ExpeL  : chaque échec génère une réflexion structurée réutilisable comme in-context example.
# core/reflexion_engine.py
@dataclass
class Reflexion:
    task_hash: str          # MD5 de l'intent
    failure_type: str       # "SyntaxError", "LogicError", "Timeout"
    context: str            # Code qui a échoué
    reflection: str         # "J'ai oublié d'importer re pour le regex"
    fix: str                # Le correctif appliqué
    verified: bool          # Le fix a-t-il passé sandbox ?

class ReflexionEngine:
    def reflect(self, error: ErrorReport, context: str) -> Reflexion:
        # Génère une réflexion via LLM + prompt spécifique
        pass
    
    def retrieve_relevant(self, intent: str) -> List[Reflexion]:
        # RAG sur lcca_failures avec filtre failure_type
        pass

Pattern Multi-Agent Reflexion  : le Reviewer et le Tester produisent chacun une réflexion. Si elles divergent, un consensus est requis avant stockage.
3.4 Karpathy Loop — lcca improve
Boucle d'auto-expérimentation locale  :
$ python main.py improve --target=auth.py --metric=pytest_score --iterations=20
# core/karpathy_loop.py
class KarpathyLoop:
    """
    1. Génère N variantes d'une fonction
    2. Exécute en sandbox avec métrique
    3. Conserve le meilleur
    4. Stocke dans Skill Library
    """
    def iterate(self, base_code: str, metric_fn, n: int = 10) -> str:
        candidates = []
        for i in range(n):
            variant = self.llm.mutate(base_code, temperature=0.5 + i*0.05)
            score = metric_fn(variant)
            candidates.append((score, variant))
        
        best = max(candidates, key=lambda x: x[0])
        return best[1]

3.5 Verifiable Execution — Receipts A2A
Chaque agent produit une preuve d'exécution avant de passer la main 
@dataclass
class ExecutionReceipt:
    task_id: str
    agent: str
    input_hash: str         # MD5 de la tâche reçue
    output_hash: str        # MD5 du livrable
    sandbox_result: bool
    test_passed: int
    test_failed: int
    tx_id: Optional[str]    # Lien vers TransactionManager V5
    timestamp: str
    signature: str          # HMAC de preuve (clé locale)

4. Ce qu'il faut AMÉLIORER
4.1 SandboxEngine → "Karpathy Sandbox"
Ajouter le support métrique pour le loop d'amélioration :
# Extension SandboxEngine
def run_with_metrics(self, code: str) -> Tuple[bool, dict]:
    """
    Retourne (success, {
        'duration_ms': int,
        'memory_peak_mb': int,
        'complexity_after': int,  # McCabe
        'score_evaluator': int    # CodeEvaluator
    })
    """
4.2 MemPalace → Hiérarchie V8
Nouvelles collections :
| Collection        | Layer           | Contenu                                        |
| ----------------- | --------------- | ---------------------------------------------- |
| `lcca_skills`     | L1 (compressed) | Fonctions réutilisables + embeddings signature |
| `lcca_reflexions` | L2 (scoped)     | Réflexions structurées par failure\_type       |
| `lcca_receipts`   | L3 (deep)       | Audit trail A2A (illimité)                     |

4.3 CodeEvaluator → Métrique de boucle
Le score V7 est informatif. En V8, il alimente le Karpathy Loop :
# Dans CodeEvaluator.evaluate()
return EvaluationResult(
    # ... champs existants ...
    karpathy_score=self._compute_karpathy_score(criteria)  # 0-100 pondéré
)
5. Ce qu'il faut SUPPRIMER
| Élément V7                       | Remplacement V8                  | Raison                                                              |
| -------------------------------- | -------------------------------- | ------------------------------------------------------------------- |
| `NLOrchestrator`                 | `A2ALocalBus` + Agent Conversant | L'orchestration unique est remplacée par la négociation multi-agent |
| `main_nl.py`                     | `main.py --mode=agentic`         | Unification du point d'entrée                                       |
| `generate_spec` comme tool isolé | Skill de l'Architect             | La spec devient un livrable A2A, pas un outil MCP                   |
| `auto_rollback` booléen          | `RecoveryPolicy` par agent       | Chaque agent définit sa politique (stop/retry/escalate)             |

6. Protocole de décision V8 (Cognitive vs Orchestration)
Utilisateur : "Ajoute la gestion JWT au module auth"

    │
    ▼
┌─────────────────────────────────────────┐
│  Architect (reçoit la tâche)            │
│  ─────────────────────────────────────  │
│  1. memory_search("lcca_skills", "jwt") │
│  2. Si skill existe → déléguer à Coder  │
│  3. Sinon → décomposer :               │
│     - Tâche 1 : Générer validate_token │
│     - Tâche 2 : Modifier login()       │
│  4. Émettre TaskContracts A2A          │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│  Coder (reçoit TaskContract)            │
│  ─────────────────────────────────────  │
│  1. Récupérer skill "jwt" si existant   │
│  2. generate_code + edit_batch ACID     │
│  3. Émettre receipt + livrable          │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│  Reviewer (reçoit livrable)             │
│  ─────────────────────────────────────  │
│  1. validate_spec + analyze_error       │
│  2. Si KO → reject avec reflexion       │
│  3. Si OK → forward à Tester            │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│  Tester (sandbox + receipt)             │
│  ─────────────────────────────────────  │
│  1. sandbox_run + evaluate_quality      │
│  2. Générer ExecutionReceipt            │
│  3. Si OK → memory_store(skill)         │
│  4. Si KO → reflexion_engine.reflect()  │
└─────────────────────────────────────────┘

7. Implémentation — Modules V8 à créer
core/agents/
├── __init__.py
├── agent_card.py          # Dataclass + registry
├── architect.py           # Planning + decomposition
├── coder.py               # Execution + edit_batch
├── reviewer.py            # Validation + critique
├── tester.py              # Sandbox + métriques
└── a2a_bus.py             # Bus local JSON

core/
├── skill_library.py       # Extraction + stockage skills
├── reflexion_engine.py    # Génération réflexions
├── karpathy_loop.py       # Boucle auto-expérimentation
├── receipt_store.py       # Audit A2A verifiable
└── agent_orchestrator.py  # Boot des agents + routing

memory/a2a/
├── inbox/
│   ├── architect/
│   ├── coder/
│   ├── reviewer/
│   └── tester/
└── receipts/
    └── {task_id}.json

8. Tests V8 requis
| Suite       | Fichier                    | Cas test                                    | Pattern validé       |
| ----------- | -------------------------- | ------------------------------------------- | -------------------- |
| A2A         | `test_a2a_bus.py`          | `test_task_contract_roundtrip`              | Bus local fiable     |
| A2A         | `test_a2a_bus.py`          | `test_receipt_hmac_integrity`               | Verifiable execution |
| Skills      | `test_skill_library.py`    | `test_extract_skill_from_sandbox_success`   | Voyager pattern      |
| Skills      | `test_skill_library.py`    | `test_skill_reuse_improves_prompt`          | SAGE token reduction |
| Reflexion   | `test_reflexion_engine.py` | `test_reflection_stored_on_failure`         | ExpeL pattern        |
| Reflexion   | `test_reflexion_engine.py` | `test_retrieve_relevant_reflection`         | RAG failures         |
| Karpathy    | `test_karpathy_loop.py`    | `test_loop_converges_better_score`          | Auto-improvement     |
| Multi-Agent | `test_agents_e2e.py`       | `test_architect_coder_reviewer_tester_flow` | A2A complet          |
| Sécurité    | `test_agent_security.py`   | `test_agent_cannot_edit_other_inbox`        | Isolation A2A        |

9. Règles invariantes V8 (ajouts aux 15 règles V7)
| #  | Règle                                                           | Justification                                          |
| -- | --------------------------------------------------------------- | ------------------------------------------------------ |
| 16 | **Un agent ne modifie jamais la mémoire d'un autre agent**      | Isolation A2A : seul le bus peut écrire dans une inbox |
| 17 | **Aucun skill n'est stocké sans receipt de sandbox**            | Verifiable execution : preuve avant persistance        |
| 18 | **Le Karpathy Loop s'arrête si 3 itérations sans amélioration** | Anti-gaming / reward hacking prevention                |
| 19 | **Les réflexions sont validées par consensus Reviewer+Tester**  | Multi-Agent Reflexion : évite l'entrenchment cognitif  |
| 20 | **La modification du code de LCCA lui-même est INTERDITE**      | Safety : frozen-model constraint                       |

10. Roadmap de migration V7 → V8
| Phase          | Durée      | Livrable                                   |
| -------------- | ---------- | ------------------------------------------ |
| **V8.0-alpha** | 2 semaines | A2A Bus + Agent Cards + Architect/Coder    |
| **V8.0-beta**  | 2 semaines | Reviewer/Tester + Receipts + Skill Library |
| **V8.0-rc**    | 1 semaine  | Reflexion Engine + Karpathy Loop           |
| **V8.1**       | 1 mois     | Self-Play (bug injection sandbox)          |
| **V8.2**       | 1 mois     | Curriculum Learning (tâches progressives)  |

11. Checklist validation (avant merge V8)
[ ] Les agents communiquent UNIQUEMENT via A2ALocalBus (pas d'appel direct)
[ ] SkillLibrary.store() exige un ExecutionReceipt valide (règle 17)
[ ] KarpathyLoop respecte la limite 3 itérations sans gain (règle 18)
[ ] Les réflexions sont produites par au moins 2 agents (règle 19)
[ ] Aucun agent ne peut modifier core/ (règle 20)
[ ] Les 237 tests V5 restent verts
[ ] Les tests V7 (Spec Layer) restent verts
[ ] Nouveaux tests V8 passent
<!-- AI-READY | Roadmap V8 Cognitive Fabric | 2026-04-18 -->