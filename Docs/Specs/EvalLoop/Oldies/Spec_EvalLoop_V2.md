# SPEC EvalLoop V2 — Système d'Auto-Évaluation Curriculum LCCA
**Version** : 2.0  
**Date** : 2026-04-24  
**Auteur** : Claude Desktop (révision post-addendum V1→V2)  
**Statut** : VALIDÉ — Prêt pour implémentation EVAL-01  
**Remplace** : Spec_EvalLoop_V1.md

---

## PRÉAMBULE — Ce qui change entre V1 et V2

### Réponses aux blockers de l'addendum V1→V2

**BLK-01 (JudgeLocal naïf)** — RÉSOLU.  
Le substring matching est remplacé par un matching tokenisé + score de cohérence structurelle.  
Mais surtout : **JudgeLocal ne génère pas de `improved_answer`**.  
Son rôle est de filtrer les réponses catastrophiques (score < 0.40), pas d'enseigner.  
Seul JudgeClaude produit du contenu injectable. En l'absence de Claude, on stocke la réponse brute LCCA avec un flag `improved_answer_pending = true` pour revue future.

**BLK-02 (interface MemoryEngine)** — RÉSOLU après lecture du code réel.  
Interface vérifiée :
- `store(collection: str, payload: Dict) → StoreResult` ✅
- `search(query: str, wing: str, n: int) → Dict[str, List[MemoryEntry]]` ✅
- `MemoryEntry.metadata` est un `Dict[str, Any]` ✅
- `_VALID_COLLECTIONS` ne contient **pas** `"evalloop_skills"` — il faut utiliser `"lcca_context"` (seuil score >= 0.6) ou `"lcca_skills"` (SkillLibrary only)

**Impact critique** : EvalLoop ne peut pas inventer une collection inconnue.  
→ Les skills distillés vont dans **`"lcca_context"`** avec `source="evalloop"` dans les métadonnées.  
→ Le seuil `_THRESHOLD_CONTEXT = 0.6` s'applique (`score >= 0.6` requis, sinon `stored=False`).  
→ Pas besoin d'un Adapter Pattern — l'interface est propre et documentée.

**BLK-03 (import lazy / sys.path)** — RÉSOLU.  
EvalLoop est un package Python avec `__init__.py`.  
Le `lcca_eval.py` CLI en racine fait `sys.path.insert(0, BASE_DIR)` une seule fois au démarrage.  
Les modules internes EvalLoop s'importent normalement : `from EvalLoop.engines.distill_engine import ...`

**MAJ-01 (improved_answer = plagiat)** — RÉSOLU. Voir BLK-01.

**MAJ-02 (longueur récompense verbosité)** — RÉSOLU.  
`length_score` remplacé par `structure_score` (code blocks, listes, exemples).

**MAJ-03 (3B pour gen-bench)** — RÉSOLU.  
`bench_generator.py` est **désactivé en V2**. Toutes les questions sont écrites à la main.  
Le module existe dans l'arborescence mais son CLI associé est supprimé (pas de `gen-bench`).

**MAJ-04 (pas de commande review-bench)** — RÉSOLU. Commande `review-bench` ajoutée au CLI.

**MAJ-05 (max_skill_tokens confus)** — RÉSOLU. Renommé en `max_skill_words`.

---

## 1. Contexte & Motivation (inchangé)

LCCA dispose de deux sources d'apprentissage :

| Source | Mécanisme | Type de connaissance |
|---|---|---|
| EducatorAgent | Lecture repos GitHub | Patterns syntaxiques, APIs, idiomes |
| **EvalLoop** | Questions/réponses curriculum | Raisonnement, architecture, debugging |

EvalLoop fonctionne comme un **curriculum scolaire** : LCCA répond à des questions de niveau croissant, un système de scoring analyse les réponses. Quand Claude API est disponible, les réponses améliorées sont injectées dans `lcca_context`. Sans Claude, EvalLoop sert de **smoke test** (détection de régressions) sans injection.

---

## 2. Paliers de Complexité (inchangé)

```
Palier 0 : Fondations — définitions, vocabulaire, concepts isolés
Palier 1 : Compréhension — "pourquoi", comparaisons simples
Palier 2 : Application — cas d'usage concrets, implémentations simples
Palier 3 : Analyse — détecter des problèmes, expliquer des comportements
Palier 4 : Synthèse — concevoir une solution à un problème ouvert
Palier 5 : Expert — edge cases, performance, compromis architecturaux
```

Règles curriculum identiques à V1.

---

## 3. Architecture des Composants

```
D:\LLMCodeAgent\
├── lcca_eval.py                     # CLI point d'entrée

EvalLoop/
├── __init__.py                      # Package Python propre
├── eval_config.toml                 # Configuration globale
├── eval_state.json                  # Palier courant par domaine
│
├── benchmarks/                      # Questions écrites à la main (paliers 0 et 1)
│   ├── python_core/
│   │   ├── palier_0.json            # 5 questions, status="active"
│   │   └── palier_1.json            # 5 questions, status="active"
│   ├── architecture/
│   │   ├── palier_0.json
│   │   └── palier_1.json
│   ├── debugging/palier_0.json
│   ├── algorithms/palier_0.json
│   ├── refactoring/palier_0.json
│   └── lcca_meta/palier_0.json
│
├── sessions/
│   └── YYYY-MM-DD_HH-MM/
│       ├── responses.jsonl          # Réponses brutes LCCA (append-only)
│       ├── scores.jsonl             # Scores (append-only)
│       └── session_report.md        # Rapport lisible
│
├── engines/
│   ├── curriculum_tracker.py        # Gère paliers, unlock, eval_state.json
│   ├── probe_engine.py              # Questions → LCCA via Ollama → responses.jsonl
│   ├── judge_engine.py              # Orchestre les juges → scores.jsonl
│   ├── distill_engine.py            # Injecte dans lcca_context via MemoryEngine
│   └── session_reporter.py          # Génère session_report.md
│
└── judges/
    ├── judge_base.py                # ABC commun
    ├── judge_local.py               # Gatekeeper offline (filtre, pas d'injection)
    └── judge_claude.py              # Juge LLM + improved_answer (optionnel)
```

**`bench_generator.py` SUPPRIMÉ** — questions uniquement à la main.  
**`judge_openai.py` SUPPRIMÉ** — remplacé par `judge_local.py`.

---

## 4. Flux de Données

```
PHASE 1 — PROBE
  curriculum_tracker → palier courant
  benchmarks/{domain}/palier_{N}.json → questions (status="active" uniquement)
  probe_engine → soumet à LCCA via Ollama (timeout=None)
               → responses.jsonl (append ligne par ligne)

PHASE 2 — JUDGE
  judge_engine → charge responses.jsonl
  JudgeLocal   → scoring gatekeeper (filtre score < 0.40, pas d'improved_answer)
  JudgeClaude  → score subjectif + improved_answer (si --judge claude)
               → scores.jsonl (append ligne par ligne)
  curriculum_tracker → score moyen palier → unlock si ≥ 0.70
                     → eval_state.json (atomique)

PHASE 3 — DISTILL (uniquement si improved_answer non vide)
  distill_engine → filtre scores ≥ min_inject_score (0.70)
                 → filtre inject_recommended=True
                 → filtre improved_answer non vide
                 → déduplique sha256[:16]
                 → MemoryEngine.store("lcca_context", {..., "score": score})
                   (seuil lcca_context = 0.6 → toujours OK si min_inject_score=0.70)
```

---

## 5. Interface MemoryEngine — Vérifiée

Interface lue dans `core/memory_engine.py` + `core/memory_engine_store.py` :

```python
# store() — signature réelle
def store(self, collection: str, payload: Dict[str, Any]) -> StoreResult:
    ...

# StoreResult — dataclass réelle
@dataclass
class StoreResult:
    stored:     bool
    collection: str
    entry_id:   Optional[str] = None
    reason:     Optional[str] = None

# _VALID_COLLECTIONS — frozenset réel
_VALID_COLLECTIONS = frozenset({
    "lcca_solutions", "lcca_failures", "lcca_context",
    "lcca_patches", "lcca_specs", "lcca_skills"
})

# extract_content() — priorité des clés
for key in ("code", "snippet", "error", "content", "text"):
    if key in payload: return payload[key]
```

**Collections disponibles pour EvalLoop :**  
→ `"lcca_context"` : seuil `score >= 0.6`, stocker les skills distillés  
→ `"lcca_skills"` : réservé à SkillLibrary (nécessite ExecutionReceipt)  

**Payload correct pour l'injection EvalLoop :**
```python
mem.store("lcca_context", {
    "content":     improved_answer_md,   # clé "content" reconnue par extract_content()
    "score":       score.score,          # float >= 0.6 (requis par seuil)
    "source":      "evalloop",
    "question_id": score.question_id,
    "domain":      score.domain,
    "palier":      score.palier,
    "judge":       score.judge,
    "session":     session_name,
    "dedup_hash":  sha256_content[:16],
})
```

**Déduplication via search :**
```python
# Rechercher le hash dans lcca_context avant injection
results = mem.search(f"dedup:{dedup_hash}", n=1)
context_entries = results.get("context", [])
already_exists = any(
    e.metadata.get("dedup_hash") == dedup_hash
    for e in context_entries
)
```

---

## 6. Juges — Architecture V2

### Rôles clairs et distincts

| Juge | Rôle | improved_answer | inject_recommended | Disponibilité |
|---|---|---|---|---|
| `JudgeLocal` | Gatekeeper : filtre les réponses catastrophiques | `""` toujours | `False` toujours | 100% offline |
| `JudgeClaude` | Évaluation qualitative + rédaction improved_answer | Markdown 200-600 mots | True si score ≥ 0.70 | API optionnelle |

**JudgeLocal ne produit jamais de contenu injectable.**  
Son score sert uniquement à décider si on soumet à JudgeClaude (gatekeeper).

### `judge_local.py` — Algorithme corrigé V2

```python
class JudgeLocal(JudgeBase):
    """
    Gatekeeper offline. Filtre les réponses catastrophiques.
    Ne produit jamais de improved_answer.
    N'injecte jamais dans MemoryEngine.
    
    Algorithme :
      concepts_found = tokenized matching (word boundaries, insensible casse)
      concept_score  = len(concepts_found) / len(expected_concepts)
      coherence_score = _coherence_check(response, expected_concepts)
      structure_score = _structure_check(response)
      score = concept_score * 0.6 + coherence_score * 0.2 + structure_score * 0.2
      
      inject_recommended = False TOUJOURS
      improved_answer    = "" TOUJOURS
    """
    
    @property
    def judge_id(self) -> str:
        return "local"
    
    def score(self, question: BenchQuestion, response: ProbeResponse) -> JudgeScore:
        if not question.expected_concepts:
            concept_score = 0.5  # Pas de concepts définis → score neutre
        else:
            concepts_found = self._find_concepts_tokenized(
                response.response, question.expected_concepts
            )
            concept_score = len(concepts_found) / len(question.expected_concepts)
        
        coherence = self._coherence_check(response.response, question.expected_concepts)
        structure = self._structure_check(response.response)
        total     = round(concept_score * 0.6 + coherence * 0.2 + structure * 0.2, 3)
        
        missing = [c for c in question.expected_concepts
                   if not self._concept_present(response.response, c)]
        
        return JudgeScore(
            question_id        = response.question_id,
            judge              = self.judge_id,
            score              = total,
            strengths          = [],   # JudgeLocal ne produit pas d'analyse qualitative
            weaknesses         = [f"Concept absent : {c}" for c in missing],
            improved_answer    = "",   # JAMAIS de contenu généré par JudgeLocal
            inject_recommended = False,  # JAMAIS d'injection depuis JudgeLocal
            domain             = response.domain,
            palier             = response.palier,
            sub_scores         = {
                "concept_coverage": round(concept_score, 3),
                "coherence":        round(coherence, 3),
                "structure":        round(structure, 3),
            },
        )
    
    def is_available(self) -> bool:
        return True
    
    def _find_concepts_tokenized(self, text: str, concepts: list[str]) -> list[str]:
        """
        Matching par word boundaries (\b) pour éviter les faux positifs.
        "list" ne matche pas "listing" ni "checklist".
        """
        import re
        text_lower = text.lower()
        found = []
        for concept in concepts:
            # Multi-mots : chaque mot doit être présent (pas forcément adjacent)
            words = concept.lower().split()
            if all(re.search(r'\b' + re.escape(w) + r'\b', text_lower) for w in words):
                found.append(concept)
        return found
    
    def _concept_present(self, text: str, concept: str) -> bool:
        """Variante booléenne de _find_concepts_tokenized pour un concept unique."""
        import re
        text_lower = text.lower()
        words = concept.lower().split()
        return all(re.search(r'\b' + re.escape(w) + r'\b', text_lower) for w in words)
    
    def _coherence_check(self, text: str, expected_concepts: list[str]) -> float:
        """
        Vérifie que les concepts apparaissent dans un contexte structuré.
        Score 0.0 → 1.0.
        
        Proxy simple : si >= 2 concepts apparaissent dans la même fenêtre de 100 mots,
        c'est probablement une explication structurée, pas une liste de mots-clés.
        """
        if len(expected_concepts) < 2:
            return 1.0  # Pas assez de concepts pour mesurer la cohérence
        
        words = text.lower().split()
        concepts_lower = [c.lower() for c in expected_concepts]
        window_size = 100
        max_co_occurrence = 0
        
        for i in range(len(words)):
            window = " ".join(words[i:i + window_size])
            co_occurrence = sum(1 for c in concepts_lower if c in window)
            max_co_occurrence = max(max_co_occurrence, co_occurrence)
        
        # Score normalisé (au moins 2 concepts co-présents sur N attendus)
        return min(1.0, max_co_occurrence / max(2, len(expected_concepts) * 0.5))
    
    def _structure_check(self, text: str) -> float:
        """
        Vérifie la présence de structures rédactionnelles.
        
        +0.33 si code block présent (``` ou    4 espaces d'indentation)
        +0.33 si liste présente (- ou * ou 1.)
        +0.33 si exemple explicite (ex:, exemple, >>>, par exemple)
        Maximum : 1.0
        """
        import re
        score = 0.0
        if re.search(r'```|^    \S', text, re.MULTILINE):
            score += 0.33
        if re.search(r'^[\s]*[-*]\s|^\d+\.\s', text, re.MULTILINE):
            score += 0.33
        if re.search(r'\bex\b\s*:|exemple\s*:|>>>\s|\bpar exemple\b', text, re.IGNORECASE):
            score += 0.34
        return min(1.0, score)
```

### Seuils JudgeLocal (gatekeeper)

```
score < 0.40  → réponse catastrophique : signalée dans le rapport, NON soumise à Claude
score ≥ 0.40  → réponse acceptable : soumise à Claude si --judge claude
score ≥ 0.40  → utilisée pour le calcul du score palier (curriculum tracker)
```

### `judge_claude.py` — inchangé sauf

- `improved_answer` tronqué à `max_skill_words` mots si dépassé
- `inject_recommended = True` uniquement si `score >= 0.70` ET `improved_answer` non vide

### Mode pipeline : local-first + claude-optional

```python
# judge_engine.py — logique V2
def run(self, questions_index):
    local_judge  = JudgeLocal()
    claude_judge = JudgeClaude(config) if _claude_active(config) else None
    
    for response in load_responses():
        question = questions_index.get(response.question_id)
        
        # Étape 1 : gatekeeper local
        local_score = local_judge.score(question, response)
        
        if local_score.score < 0.40:
            # Réponse catastrophique — on skipe Claude, on log
            _write_score(local_score, session_dir)
            continue
        
        # Étape 2 : si Claude disponible, enrichir
        if claude_judge and claude_judge.is_available():
            claude_score = claude_judge.score(question, response)
            _write_score(claude_score, session_dir)
        else:
            # Pas de Claude : on écrit le score local (inject=False)
            _write_score(local_score, session_dir)
```

---

## 7. DistillEngine — Interface Corrigée V2

```python
class DistillEngine:
    def __init__(self, config: dict, session_dir: Path):
        self._session_dir = session_dir
        self._config      = config
        self._mem         = None  # lazy, instancié une seule fois
    
    def _get_mem(self) -> "MemoryEngine":
        """Import propre — fonctionne si lcca_eval.py a fait sys.path.insert(0, BASE_DIR)."""
        if self._mem is None:
            from core.memory_engine import MemoryEngine
            self._mem = MemoryEngine()
        return self._mem
    
    def run(self, min_score=None, questions_index=None) -> list[DistilledSkill]:
        # Ne traite que les scores avec improved_answer non vide
        # et inject_recommended=True
        ...
    
    def _inject(self, skill_md: str, score: JudgeScore, question) -> StoreResult:
        dedup_hash = self._sha256_content(skill_md)
        mem = self._get_mem()
        return mem.store("lcca_context", {
            "content":     skill_md,         # clé "content" reconnue par extract_content()
            "score":       score.score,      # float >= 0.6 requis
            "source":      "evalloop",
            "question_id": score.question_id,
            "domain":      score.domain,
            "palier":      score.palier,
            "judge":       score.judge,
            "session":     self._session_dir.name,
            "dedup_hash":  dedup_hash,
        })
    
    def _is_duplicate(self, dedup_hash: str) -> bool:
        mem = self._get_mem()
        results = mem.search(f"dedup {dedup_hash}", n=3)
        context_entries = results.get("context", [])
        return any(
            e.metadata.get("dedup_hash") == dedup_hash
            for e in context_entries
        )
```

---

## 8. `eval_config.toml` V2

```toml
[general]
project_root   = "D:\\LLMCodeAgent"
evalloop_dir   = "D:\\LLMCodeAgent\\EvalLoop"
sessions_dir   = "D:\\LLMCodeAgent\\EvalLoop\\sessions"
benchmarks_dir = "D:\\LLMCodeAgent\\EvalLoop\\benchmarks"

[llca]
ollama_base_url = "http://localhost:11434"
model           = "qwen2.5-coder:3b"
timeout         = null         # Invariant LCCA : OLLAMA_TIMEOUT = None
max_tokens      = 1500

[judges]
default         = "local"      # JudgeLocal = gatekeeper par défaut
active          = ["local"]    # Ajouter "claude" pour enrichissement + injection
consensus_mode  = false
claude_model    = "claude-sonnet-4-6"
local_gate_threshold = 0.40    # En dessous → réponse catastrophique (skip Claude)

[scoring]
min_inject_score = 0.70        # Seuil injection lcca_context (Claude uniquement)
seuil_unlock     = 0.70        # Score moyen palier requis pour unlock palier+1
max_palier       = 5
max_skill_words  = 500         # Limite taille improved_answer (en mots, ~750 tokens FR)

[curriculum]
domains = [
    "python_core",
    "architecture",
    "refactoring",
    "debugging",
    "algorithms",
    "lcca_meta",
]

[domains.python_core]
description          = "Fondamentaux Python : OOP, GC, typing, async"
questions_per_palier = 5

[domains.architecture]
description          = "Design patterns, SOLID, découpage système"
questions_per_palier = 5

[domains.refactoring]
description          = "Identifier et corriger la dette technique"
questions_per_palier = 5

[domains.debugging]
description          = "Lire un traceback, diagnostiquer, corriger"
questions_per_palier = 5

[domains.algorithms]
description          = "Complexité, structures de données, algorithmes"
questions_per_palier = 5

[domains.lcca_meta]
description          = "Questions sur LCCA lui-même et ses propres règles"
questions_per_palier = 3
```

---

## 9. CLI `lcca_eval.py` V2

```bash
# Probe
python lcca_eval.py probe --domain python_core [--session 2026-04-24] [--questions 5]
python lcca_eval.py probe --domain all

# Judge
python lcca_eval.py judge --session latest [--judge local|claude]
# Défaut : --judge local (gatekeeper uniquement, pas d'injection)

# Distill (nécessite scores Claude)
python lcca_eval.py distill --session latest [--min-score 0.70]

# Rapport
python lcca_eval.py report --session latest

# Statut curriculum
python lcca_eval.py status

# Pipeline complet
python lcca_eval.py run --domain python_core [--judge local|claude]

# Revue manuelle des questions draft (MAJ-04)
python lcca_eval.py review-bench --domain python_core --palier 1
# Affiche chaque question draft une par une :
# [1/3] py-p1-001 : "Quelle est la différence entre..." [y=active / n=supprimer / e=éditer / s=skip]
```

**Supprimé** : `gen-bench` (BenchGenerator désactivé en V2).  
**Ajouté** : `review-bench` (passage draft → active).

---

## 10. Sprints EvalLoop V2

| Sprint | Fichiers | Contenu | Dépendances |
|---|---|---|---|
| EVAL-01 | `EvalLoop/__init__.py` + `evalloop_types.py` + configs | Dataclasses + eval_config.toml + eval_state.json | — |
| EVAL-02 | `curriculum_tracker.py` + `probe_engine.py` | Paliers + probe Ollama → responses.jsonl | EVAL-01 |
| EVAL-03 | `judge_base.py` + `judge_local.py` + `judge_claude.py` + `judge_engine.py` | Gatekeeper + Claude optionnel → scores.jsonl | EVAL-01 |
| EVAL-04 | `distill_engine.py` | Injection `lcca_context` via MemoryEngine | EVAL-01, EVAL-03 |
| EVAL-05 | Benchmarks initiaux | 9 fichiers JSON paliers 0+1 (manuels) | EVAL-01 |
| EVAL-06 | `lcca_eval.py` + `session_reporter.py` | CLI + rapport + review-bench | EVAL-02..05 |
| EVAL-07 | `tests/test_eval_*.py` | ~50 tests (réduction intentionnelle) | EVAL-01..06 |

---

## 11. Tests — Cible Réduite à ~50

La V1 prévoyait 125 tests. Réduction intentionnelle à ~50 pour un projet solo.  
Priorité : JudgeLocal (cœur de la V2), intégration, et dataclasses.

| Fichier | Tests | Priorité |
|---|---|---|
| `test_eval_01_types.py` | ~15 | Dataclasses, round-trips, status, sub_scores |
| `test_eval_02_probe.py` | ~8 | CurriculumTracker basique + ProbeEngine (Ollama mocké) |
| `test_eval_03_judge.py` | ~15 | **JudgeLocal complet** (cœur V2) + JudgeClaude mocké |
| `test_eval_04_distill.py` | ~6 | DistillEngine + MemoryEngine mocké |
| `test_eval_integration.py` | ~6 | Cycle complet local (sans Claude) + avec Claude mocké |

**Total : 50 tests** — couverture essentielle, pas exhaustive.

### Tests JudgeLocal prioritaires (~15 tests)

```python
# Matching tokenisé
def test_find_concepts_no_false_positive_list_in_listing(): ...
def test_find_concepts_no_false_positive_thread_in_threading(): ...
def test_find_concepts_case_insensitive(): ...
def test_find_concepts_multi_word_concept(): ...  # "Global Interpreter Lock"

# Cohérence
def test_coherence_keyword_stuffing_penalized(): ...  # "GIL thread bytecode I/O CPU" → faible
def test_coherence_structured_explanation_rewarded(): ...

# Structure
def test_structure_code_block_detected(): ...
def test_structure_list_detected(): ...
def test_structure_empty_response(): ...

# Invariants absolus
def test_judge_local_never_inject_recommended(): ...  # inject_recommended toujours False
def test_judge_local_never_improved_answer(): ...     # improved_answer toujours ""
def test_judge_local_always_available(): ...

# Gatekeeper
def test_gatekeeper_catastrophic_response_score_below_040(): ...
def test_gatekeeper_good_response_passes(): ...

# Sub-scores
def test_sub_scores_present_in_result(): ...  # concept_coverage, coherence, structure
```

### Tests d'intégration (~6 tests)

```python
# INT-01 : Pipeline complet LOCAL (sans Claude)
# probe → judge local → scores.jsonl → distill vide (inject=False) → rapport
def test_full_cycle_local_no_injection(tmp_path): ...

# INT-02 : Pipeline complet avec Claude mocké
# probe → judge local gate OK → judge Claude mocké → scores.jsonl → distill → lcca_context
def test_full_cycle_with_claude_mock(tmp_path): ...

# INT-03 : Réponse catastrophique gatekeeper
# probe → judge local score < 0.40 → skip Claude → 0 injection
def test_catastrophic_response_no_injection(tmp_path): ...

# INT-04 : Curriculum unlock
# 5 scores ≥ 0.70 → current_palier incrémenté dans eval_state.json
def test_curriculum_unlock(tmp_path): ...

# INT-05 : Écriture atomique eval_state.json (T-14)
def test_eval_state_atomic_no_tmp_leftover(tmp_path): ...

# INT-06 : JSONL append correct
def test_jsonl_lines_valid_ndjson(tmp_path): ...
```

---

## 12. Invariants & Règles V2

- `probe_engine` : `timeout=None` sur urlopen (invariant LCCA absolu)
- `urllib.request` stdlib uniquement — jamais `requests`
- `eval_state.json` : écriture atomique `.tmp → Path.replace()` (règle T-14)
- Sessions immuables : `responses.jsonl` et `scores.jsonl` append-only
- `auto_push = false` — EvalLoop ne fait jamais de git push
- `JudgeLocal.inject_recommended` = `False` INVARIANT — jamais injecte dans MemoryEngine
- `JudgeLocal.improved_answer` = `""` INVARIANT — jamais génère de contenu
- Injection dans `"lcca_context"` uniquement (seule collection accessible sans receipt)
- `score >= 0.60` requis par `_THRESHOLD_CONTEXT` — min_inject_score=0.70 garantit le seuil
- `EvalLoop/__init__.py` obligatoire — package Python propre, pas d'import hack

---

## 13. Réponses aux Questions Ouvertes V2

| ID | Réponse |
|----|---------|
| **Q-V2-01** | Interface MemoryEngine vérifiée (voir section 5). `store("lcca_context", {..., "content": ..., "score": ...})` → `StoreResult`. `search(query, n=3)` → `Dict[str, List[MemoryEntry]]` avec `entry.metadata` dict. |
| **Q-V2-02** | BenchGenerator désactivé en V2. Questions palier 0+1 manuelles uniquement. Paliers 2+ : écriture manuelle ou report en V3. |
| **Q-V2-03** | Injection automatique acceptable **uniquement depuis JudgeClaude**. JudgeLocal ne génère jamais de contenu injectable. Revue humaine non requise pour les scores Claude ≥ 0.70. |
| **Q-V2-04** | `eval_state.json` = artefact local. `auto_push = false`. Pas de versionnement git. |
| **Q-V2-05** | Pipeline sur demande uniquement (`lcca_eval.py run`). Pas de cron automatique (GPU/RAM non disponibles en tâche de fond sur le P50). |

---

## 14. Checklist Pré-Implémentation EVAL-01

```
[x] Interface MemoryEngine vérifiée — lcca_context, score >= 0.6, clé "content"
[x] JudgeLocal = gatekeeper uniquement (pas d'injection, pas d'improved_answer)
[x] BenchGenerator désactivé en V2 (questions manuelles uniquement)
[x] EvalLoop/__init__.py prévu (package propre, import depuis racine)
[x] Cible tests réduite à ~50 (priorisé JudgeLocal + intégration)
[x] max_skill_tokens renommé max_skill_words
[x] Commande review-bench ajoutée au CLI
[x] collection "evalloop_skills" abandonnée → "lcca_context" avec source="evalloop"

→ Prêt pour EVAL-01 : EvalLoop/__init__.py + evalloop_types.py + eval_config.toml
```

---

## 15. Compteur global LCCA post-EvalLoop V2

```
EVAL-01 types        : +15 tests
EVAL-02 probe        : +8 tests
EVAL-03 judge        : +15 tests
EVAL-04 distill      : +6 tests
EVAL-07 intégration  : +6 tests
─────────────────────────────────
EvalLoop total       : +50 tests

État avant EvalLoop  : 1483 tests (post-PROJ-04)
État après EvalLoop  : ~1533 tests (estimé)
```
