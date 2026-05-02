============================================================
Fichier : REVIEW-V9-FINAL-2026-04-20.md
============================================================

# Review Technique Final — Spécifications LCCA V9
&lt;!-- AI-READY | Review V9 Final | Version 9.0.0-review-final | 2026-04-20 --&gt;

**Document source** : Dossier V9 (README + 5 specs + review critique interne)  
**Périmètre** : V9-01 (Perf LLM) → V9-05 (Agents Créatifs)  
**Machine cible** : Lenovo P50, 16 GB RAM, CPU uniquement, Windows 11  
**Contrainte maîtresse** : Principe "CPU-first" — aucune fonctionnalité ne doit rendre le système inutilisable sur le hardware cible.

---

## 1. Synthèse exécutive

| Critère | Verdict | Commentaire |
|---------|---------|-------------|
| Cohérence V5/V7/V8 | ⚠️ **Partielle** | Quelques contradictions majeures (CPU-first vs GRPO, indexation répétée) |
| Faisabilité P50 | ⚠️ **Conditionnelle** | V9-04 (GRPO) et V9-05-F (Kokoro) hors scope hardware. Le reste est viable avec corrections. |
| Qualité des specs | ✅ **Bonne** | Dataclasses, tests, pré/postconditions présents. Manque de spécification sur l'éviction mémoire. |
| Rétrocompatibilité | ⚠️ **À renforcer** | Boucle de correction V9-02-B change silencieusement le contrat de `generate()` |
| Sécurité | ✅ **Correcte** | `safe_path`, sandbox, compilation sans exécution respectés |
| Priorisation | ✅ **Bonne** | P0/P1/P2/P3/P4 cohérent avec la valeur métier |

**Verdict global** : **VALIDABLE sous réserve de 7 corrections bloquantes et 5 améliorations P1.**  
Les specs V9-01, V9-02 (corrigée), V9-03 (corrigée), V9-05-A/B/C/D sont prêtes pour implémentation.  
V9-04-B/C et V9-05-F sont **reportées V10**. V9-05-E nécessite un changement de backend (SQLite FTS5).

---

## 2. Analyse détaillée par axe

### 2.1 V9-01 — Optimisation LLM (Performance)

| Sous-sprint | État | Analyse |
|-------------|------|---------|
| **V9-01-A Q4_K_M + keep_alive** | ✅ Accepté | `keep_alive` est une optimisation gratuite. La quantification Q4_K_M est pertinente pour P50. **Note** : il faut documenter la commande `ollama pull` exacte. |
| **V9-01-B Tri-modèle adaptatif** | 🔴 **Bloquant** | Le helper `_get_generator()` crée une **nouvelle instance** `LLMGenerator` à chaque appel. Sur P50, changer de modèle Ollama entraîne un déchargement/rechargement en RAM (5-15 s). **De plus**, maintenir 3 modèles (3b + 7b + 14b quantifiés ≈ 8,5 GB) avec ChromaDB + Electron dépasse les 16 GB. |
| **V9-01-C Streaming universel** | ✅ Accepté | Le fallback bloquant en cas d'échec stream est bien pensé. **Attention** : sur CPU, le streaming peut saturer l'UI si le callback est lent. Un buffer/throttle est recommandé. |

**Recommandation V9-01-B** : Remplacer par un `LLMGeneratorPool` avec politique d'éviction LRU (max 2 modèles chargés simultanément) et déchargement explicite.

```python
# core/llm_generator_pool.py
import threading
import time
from typing import Optional

class LLMGeneratorPool:
    """
    Pool singleton de LLMGenerator par modèle avec éviction LRU.
    Garantit que max 2 modèles sont chargés en RAM simultanément sur P50.
    """
    _instances: dict[str, "LLMGenerator"] = {}
    _last_used: dict[str, float] = {}
    _lock = threading.Lock()
    MAX_LOADED = 2

    @classmethod
    def get(cls, model: str, timeout: int = 90, max_tokens: int = 512) -&gt; "LLMGenerator":
        from core.llm_generator import LLMGenerator
        
        key = f"{model}:{timeout}:{max_tokens}"
        
        with cls._lock:
            if key not in cls._instances:
                cls._evict_if_needed()
                cls._instances[key] = LLMGenerator(
                    model=model, timeout=timeout, max_tokens=max_tokens
                )
            cls._last_used[key] = time.monotonic()
            return cls._instances[key]

    @classmethod
    def _evict_if_needed(cls):
        """Décharge le modèle le moins récemment utilisé si on atteint MAX_LOADED."""
        if len(cls._instances) &lt; cls.MAX_LOADED:
            return
        
        # LRU eviction
        oldest_key = min(cls._last_used, key=cls._last_used.get)
        del cls._instances[oldest_key]
        del cls._last_used[oldest_key]
        # Ollama déchargera le modèle automatiquement après keep_alive

    @classmethod
    def unload(cls, model: str) -&gt; None:
        """Déchargement explicite d'un modèle."""
        keys_to_remove = [k for k in cls._instances if k.startswith(f"{model}:")]
        for k in keys_to_remove:
            cls._instances.pop(k, None)
            cls._last_used.pop(k, None)

    @classmethod
    def clear(cls):
        with cls._lock:
            cls._instances.clear()
            cls._last_used.clear()

2.2 V9-02 — Qualité des réponses LLM
| Sous-sprint                                      | État            | Analyse                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| ------------------------------------------------ | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **V9-02-A Few-shot SkillLibrary**                | ✅ Accepté       | Connexion logique entre V8 (SkillLibrary) et PromptBuilder. Le paramètre `skill_context` par défaut `""` préserve la rétrocompatibilité.                                                                                                                                                                                                                                                                                                         |
| **V9-02-B Boucle de correction post-génération** | 🔴 **Bloquant** | Changement de comportement silencieux de `LLMGenerator.generate()`. Avant : 1 appel, fallback immédiat. Après : jusqu'à 3 appels + évaluation. **Sur P50, 3 × 60 s = 180 s minimum**, sans compter le `CodeEvaluator`. Si le modèle est le 14b (180 s), on atteint **540 s (9 minutes)** avant fallback. Le paramètre `LLM_MAX_CORRECTION_RETRIES` est mentionné dans `config.py` mais la spec utilise `_MAX_RETRIES = 2` hardcodé dans le code. |
| **V9-02-C AST context**                          | ✅ Accepté       | Bonne idée. `_build_ast_context` appelle `index_repository()` qui est linéaire en nombre de fichiers. Sur 50+ fichiers, c'est acceptable. Sur 200+, il faudra un cache.                                                                                                                                                                                                                                                                          |
| **V9-02-D JSON mode Ollama**                     | ✅ Accepté       | `"format": "json"` est bien supporté par Ollama ≥ 0.1.14. Qwen2.5-coder le respecte.                                                                                                                                                                                                                                                                                                                                                             |

Recommandation V9-02-B :
# config.py
CORRECTION_LOOP_ENABLED = False        # Opt-in pour V9.0
LLM_GENERATION_MAX_TOTAL_SEC = 120     # Timeout global dur (arrêt de la boucle)
LLM_MAX_CORRECTION_RETRIES = 2         # Doit être utilisé, pas hardcodé

# core/llm_generator.py — modification de generate()
_MIN_QUALITY_SCORE = 70

def generate(self, op, intent, context: str = "", skill_context: str = "") -> GenerationResult:
    import time, config
    from core.code_evaluator import CodeEvaluator

    # V9-02-B : respect du flag global
    if not getattr(config, "CORRECTION_LOOP_ENABLED", False):
        return self._generate_single(op, intent, context, skill_context)
    
    max_retries = getattr(config, "LLM_MAX_CORRECTION_RETRIES", 2)
    max_total_sec = getattr(config, "LLM_GENERATION_MAX_TOTAL_SEC", 120)
    deadline = time.monotonic() + max_total_sec
    
    # ... reste de la boucle avec vérification deadline ...
    for attempt in range(max_retries + 1):
        if time.monotonic() > deadline:
            log.warning("Timeout global atteint (%ds) — fallback", max_total_sec)
            break
        # ... logique existante ...

2.3 V9-03 — Agentic RAG
| Sous-sprint                          | État                 | Analyse                                                                                                                                                                                                                                     |
| ------------------------------------ | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **V9-03-A Repository-RAG**           | 🔴 **Bloquant perf** | `_retrieve_repo_context` appelle `ASTIndexer().index_repository()` **à chaque génération**. Sur P50, indexer 52 fichiers prend ~2-3 s. Multiplié par le KarpathyLoop (max 20 itérations) = **40-60 s de pure perte**.                       |
| **V9-03-B Web search auto**          | ✅ Accepté            | Heuristique `_detect_external_libs` simple et efficace. Fallback silencieux bien pensé.                                                                                                                                                     |
| **V9-03-C HyDE**                     | ⚠️ **À corriger**    | Désactivé par défaut (`MEMORY_HYDE_ENABLED = False`). Cohérent. **Problème** : `search_hyde` crée un `LLMGenerator()` par défaut si `generator is None`, ce qui recharge un modèle. Il faut passer systématiquement le générateur existant. |
| **V9-03-D Doc retrieval erreur API** | ✅ Accepté            | Excellent pattern. L'enrichissement de réflexion avec la doc officielle est une vraie plus-value. **Amélioration P1** : chercher d'abord dans `lcca_failures` (ChromaDB) avant la recherche web.                                            |

Recommandation V9-03-A : Cache AST avec TTL 5 min + invalidation post-commit.
# core/agents/coder_agent.py
import time

class CoderAgent(BaseAgent):
    def __init__(self, ...):
        # ...
        self._ast_index_cache: Optional[dict] = None
        self._ast_index_cache_ts: float = 0
        self._INDEX_CACHE_TTL = 300  # 5 minutes
        self._last_git_head: Optional[str] = None

    def _get_ast_index(self) -> dict:
        """Retourne l'index AST, avec cache TTL et invalidation si nouveau commit."""
        import subprocess
        try:
            current_head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, cwd=config.WORKSPACE_DIR, timeout=5
            ).stdout.strip()
        except Exception:
            current_head = None
        
        now = time.monotonic()
        cache_valid = (
            self._ast_index_cache is not None
            and (now - self._ast_index_cache_ts) < self._INDEX_CACHE_TTL
            and (current_head is None or current_head == self._last_git_head)
        )
        
        if not cache_valid:
            from core.ast_indexer import ASTIndexer
            self._ast_index_cache = ASTIndexer(workspace=config.WORKSPACE_DIR).index_repository()
            self._ast_index_cache_ts = now
            self._last_git_head = current_head
        
        return self._ast_index_cache

    def _retrieve_repo_context(self, intent: str) -> str:
        index = self._get_ast_index()
        # ... reste de la logique BM25 inchangée ...

Recommandation V9-03-C : Injection du générateur existant.
# core/memory_engine.py — modification de search_hyde
def search_hyde(
    self,
    query: str,
    wing: str = "lcca",
    n: int = 5,
    generator: Optional["LLMGenerator"] = None,  # Toujours fourni par l'appelant
) -> Dict[str, List[MemoryEntry]]:
    # ...
    if generator is None:
        # V9-03-C : ne jamais créer de nouveau générateur ici
        log.debug("HyDE: aucun générateur fourni → fallback standard")
        return self.search(query, wing, n)
    # ...

2.4 V9-04 — Pipeline d'entraînement (SFT + GRPO)
| Aspect                       | État                     | Analyse                                                                                                                                                                                                |
| ---------------------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **V9-04-A Collecteur SFT**   | ✅ Accepté                | `TrainingDataCollector` est bien conçu. Déduplique, exporte ShareGPT/Alpaca. Aucune dépendance GPU.                                                                                                    |
| **V9-04-B GRPO / Unsloth**   | 🔴 **Bloquant hardware** | **Contradiction majeure avec le principe "CPU-first"**. Même en 4-bit LoRA, un fine-tuning GRPO sur CPU prend des heures par epoch. Unsloth est optimisé GPU CUDA. Sur P50 sans GPU, c'est irréaliste. |
| **V9-04-C Pipeline continu** | 🔴 **Reporté**           | Dépend de V9-04-B. Le hot-swap de modèle Ollama est faisable, mais le micro-fine-tune toutes les 50 paires sur CPU est une illusion de performance.                                                    |

Recommandation V9-04 :
V9.0 : Conserver uniquement le collecteur de données (TrainingDataCollector). C'est déjà une valeur énorme (export vers environnement GPU externe, ou accumulation pour futur fine-tuning).
V9.0 : Remplacer GRPO par un "Prompt Tuning Automatique" : ajuster dynamiquement les prompts système selon les skills les plus utilisés (in-context learning, pas de fine-tuning de poids).
V10 : GRPO avec prérequis "GPU dédié ou cloud compute".

# core/prompt_tuner.py — nouveau fichier V9 (remplacement GRPO)
class PromptTuner:
    """
    Ajuste dynamiquement le prompt système du LLM selon les skills et patterns
    les plus utilisés récemment (in-context learning, pas de fine-tuning).
    """
    def tune(self, base_system_prompt: str, recent_skills: List[Skill]) -> str:
        # Injection des top 3 skills dans le prompt système
        # Pas de modification de poids du modèle
        pass

2.5 V9-05 — Agents créatifs
| Sous-sprint                     | État                       | Analyse                                                                                                                                                                                                           |
| ------------------------------- | -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **V9-05-A QAAgent**             | ✅ Accepté                  | Excellent. Lecture seule, règles pertinentes, thread daemon. Les règles `_rule_hardcoded_python` et `_rule_direct_file_write` sont des garde-fous essentiels.                                                     |
| **V9-05-B DocAgent**            | ✅ Accepté                  | Bon concept. `DOCAGENT_AUTO_CONFIRM = False` par défaut est indispensable. Le hook git PowerShell est optionnel et bien documenté.                                                                                |
| **V9-05-C Pair Programmer**     | ✅ Accepté                  | HITL bien intégré. Le callback `hitl_callback` est injecté proprement.                                                                                                                                            |
| **V9-05-D Dashboard Analytics** | ✅ Accepté                  | Dépendances UI (recharts) acceptables. Les métriques sont bien définies.                                                                                                                                          |
| **V9-05-E Mémoire épisodique**  | 🔴 **Bloquant dépendance** | DuckDB est une dépendance compilée lourde (~50 MB wheel). Sur Windows, l'installation peut échouer si Visual C++ Redist manque. **Remplacement obligatoire par SQLite FTS5** (stdlib Python 3.11+).               |
| **V9-05-F TTS Kokoro**          | 🔴 **Bloquant hardware**   | Kokoro-FastAPI nécessite un serveur en arrière-plan + modèle ~200 MB. Avec Ollama 7b (~4-9 GB) déjà en RAM, ajouter Kokoro sur P50 (16 GB total) risque de provoquer du swap et de ralentir drastiquement Ollama. |

Recommandation V9-05-E : SQLite FTS5 avec schéma documenté.
# core/episodic_memory.py — refonte avec SQLite FTS5
import sqlite3
from pathlib import Path
from config import BASE_DIR

EPISODIC_DB = BASE_DIR / "memory" / "episodic.sqlite"

class EpisodicMemory:
    def __init__(self, db_path: Path = EPISODIC_DB):
        self.db_path = db_path
        self._init_schema()
    
    def _init_schema(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    date TEXT NOT NULL,
                    sprint_name TEXT,
                    engineer TEXT
                );
                
                CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    rationale TEXT,
                    alternatives TEXT,
                    session_id TEXT,
                    created_at TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                );
                
                CREATE VIRTUAL TABLE IF NOT EXISTS decisions_fts USING fts5(
                    title, rationale, alternatives, session_id,
                    content='decisions', content_rowid='rowid'
                );
                
                CREATE TRIGGER IF NOT EXISTS decisions_ai AFTER INSERT ON decisions BEGIN
                    INSERT INTO decisions_fts(rowid, title, rationale, alternatives, session_id)
                    VALUES (new.rowid, new.title, new.rationale, new.alternatives, new.session_id);
                END;
            """)
    
    def query(self, question: str, limit: int = 5) -> List[dict]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT d.* FROM decisions d "
                "JOIN decisions_fts fts ON d.rowid = fts.rowid "
                "WHERE decisions_fts MATCH ? ORDER BY rank LIMIT ?",
                (question, limit)
            )
            cols = [c[0] for c in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]

Recommandation V9-05-F : pyttsx3 par défaut (SAPI5 Windows, 0 MB de modèle), Kokoro en option avancée V9.2.
# core/tts_engine.py
class TTSEngine:
    def __init__(self):
        self._engine = None
        self._enabled = getattr(config, "TTS_ENABLED", False)
        self._provider = getattr(config, "TTS_ENGINE", "pyttsx3")
    
    def say(self, text: str):
        if not self._enabled:
            return
        
        if self._provider == "pyttsx3":
            self._say_pyttsx3(text)
        elif self._provider == "kokoro":
            self._say_kokoro(text)
    
    def _say_pyttsx3(self, text: str):
        try:
            import pyttsx3
            if self._engine is None:
                self._engine = pyttsx3.init()
            self._engine.say(text)
            self._engine.runAndWait()
        except Exception as exc:
            log.debug("TTS pyttsx3 error: %s", exc)
    
    def _say_kokoro(self, text: str):
        # Option avancée — V9.2
        pass


3. Problèmes transversaux critiques
3.1 🔴 Contradiction "CPU-first" vs Fine-tuning GRPO (V9-04)
Impact : Bloquant. Le fine-tuning local GRPO est irréaliste sur P50.
Correction : V9-04 se limite au collecteur SFT. GRPO reporté V10. Remplacement par PromptTuner (in-context learning).
3.2 🔴 Indexation AST répétée (V9-03-A)
Impact : Performance. Jusqu'à 60 s de perdues par KarpathyLoop sur P50.
Correction : Cache TTL 5 min + invalidation post-commit dans CoderAgent.
3.3 🔴 Boucle de correction silencieuse (V9-02-B)
Impact : Rétrocompatibilité + Timeout. generate() devient 3× plus lent sans avertissement.
Correction : CORRECTION_LOOP_ENABLED = False par défaut. Timeout global LLM_GENERATION_MAX_TOTAL_SEC = 120.
3.4 🔴 Tri-modèle sans pool ni éviction (V9-01-B)
Impact : Latence + RAM. Rechargement Ollama à chaque changement de tool. Saturation mémoire si 3 modèles chargés.
Correction : LLMGeneratorPool avec LRU (max 2 modèles) + unload() explicite.
3.5 🔴 TTS Kokoro trop lourd (V9-05-F)
Impact : RAM. Risque de swap sur P50.
Correction : pyttsx3 par défaut, Kokoro en option avancée.
3.6 🔴 Mémoire épisodique DuckDB (V9-05-E)
Impact : Dépendance compilée lourde, risque d'échec d'installation Windows.
Correction : sqlite3 + FTS5 (stdlib).
3.7 🟡 Streaming sans throttle (V9-01-C)
Impact : UI. Sur CPU, le streaming peut saturer la sortie standard.
Correction : Buffer de tokens + throttle optionnel.
4. Améliorations complémentaires recommandées (P1)
4.1 Mode "Safe Mode" (optionnel)
# config.py
LCCA_SAFE_MODE = True  # Désactive automatiquement les features lourdes/dangereuses
En Safe Mode : boucle de correction OFF, web search auto OFF, DocAgent OFF, TTS OFF.
4.2 Health check périodique d'Ollama
# core/llm_generator_pool.py
def health_check(self) -> dict:
    """Vérifie latence et disponibilité. Retourne {'healthy': bool, 'latency_ms': int}."""

4.3 Compression du contexte RAG
Estimer la taille en tokens avant injection (1 token ≈ 4 caractères). Si > 80% de la fenêtre, réduire le nombre de fichiers ou tronquer.
4.4 Reranking BM25 + embeddings (P1)
Après BM25 (10-15 docs), appliquer un re-ranking par similarité cosine via ChromaDB (déjà présent). Surcoût < 100 ms.
4.5 Feedback utilisateur explicite
Exposer un événement lcca:decision dans l'UI pour que l'utilisateur comprenne le routage modèle et puisse le surcharger.
5. Tableau de décision final par sous-sprint
| Sous-sprint | Décision               | Action requise                                        |
| ----------- | ---------------------- | ----------------------------------------------------- |
| V9-01-A     | ✅ Implémenter          | Tel quel                                              |
| V9-01-B     | ⚠️ Implémenter corrigé | `LLMGeneratorPool` avec LRU (max 2)                   |
| V9-01-C     | ⚠️ Implémenter corrigé | Ajouter buffer/throttle optionnel                     |
| V9-02-A     | ✅ Implémenter          | Tel quel                                              |
| V9-02-B     | ⚠️ Implémenter corrigé | Flag `CORRECTION_LOOP_ENABLED=False`, timeout global  |
| V9-02-C     | ✅ Implémenter          | Tel quel                                              |
| V9-02-D     | ✅ Implémenter          | Tel quel                                              |
| V9-03-A     | ⚠️ Implémenter corrigé | Cache AST 5min + invalidation git                     |
| V9-03-B     | ✅ Implémenter          | Tel quel                                              |
| V9-03-C     | ⚠️ Implémenter corrigé | Injection générateur existant obligatoire             |
| V9-03-D     | ✅ Implémenter          | Tel quel + recherche locale `lcca_failures` avant web |
| V9-04-A     | ✅ Implémenter          | Tel quel (collecteur uniquement)                      |
| V9-04-B     | ❌ Reporter V10         | GRPO nécessite GPU                                    |
| V9-04-C     | ❌ Reporter V10         | Pipeline continu nécessite V9-04-B                    |
| V9-05-A     | ✅ Implémenter          | Tel quel                                              |
| V9-05-B     | ✅ Implémenter          | Tel quel                                              |
| V9-05-C     | ✅ Implémenter          | Tel quel                                              |
| V9-05-D     | ✅ Implémenter          | Tel quel                                              |
| V9-05-E     | ⚠️ Implémenter corrigé | SQLite FTS5 au lieu de DuckDB                         |
| V9-05-F     | ⚠️ Implémenter corrigé | `pyttsx3` par défaut, Kokoro option                   |

6. Spécifications complémentaires (nouveaux fichiers / patches)
6.1 core/llm_generator_pool.py (nouveau)
Voir section 2.1.
6.2 core/prompt_tuner.py (nouveau — remplacement GRPO V9)
Voir section 2.4.
6.3 core/tts_engine.py (nouveau)
Voir section 2.5.
6.4 core/episodic_memory.py (refonte SQLite)
Voir section 2.5.
6.5 Patch config.py
# === V9 Corrections Review ===
CORRECTION_LOOP_ENABLED = False
LLM_GENERATION_MAX_TOTAL_SEC = 120
LLM_MAX_CORRECTION_RETRIES = 2

# Pool
LLM_POOL_MAX_LOADED = 2

# Safe Mode
LCCA_SAFE_MODE = True

# TTS
TTS_ENABLED = False
TTS_ENGINE = "pyttsx3"  # "pyttsx3" | "kokoro"
TTS_VOICE = "fr_f"

# Quantification configurable
OLLAMA_QUANT_LEVEL = "Q4_K_M"  # "Q4_K_M" | "Q5_K_M"

# Ollama CPU params
OLLAMA_THREADS = 4      # 0 = auto
OLLAMA_NUM_GPU = 0      # Force CPU
OLLAMA_MMAP = True      # Réduction RAM via mmap

# Streaming
STREAM_BUFFER_SIZE = 10
STREAM_THROTTLE_MS = 50

7. Tests requis complémentaires
| Suite     | Fichier                      | Cas test                                                                 | Priorité |
| --------- | ---------------------------- | ------------------------------------------------------------------------ | -------- |
| Pool      | `test_llm_generator_pool.py` | `test_pool_limits_max_2_models` — 3ème modèle évince le LRU              | CRITIQUE |
| Pool      | `test_llm_generator_pool.py` | `test_pool_unload_explicit` — unload libère la mémoire                   | HAUTE    |
| Loop      | `test_llm_generator.py`      | `test_correction_loop_disabled_by_default` — flag=False = 1 appel        | CRITIQUE |
| Loop      | `test_llm_generator.py`      | `test_timeout_global_interrupts_retries` — 120s max respecté             | CRITIQUE |
| RAG       | `test_coder_agent.py`        | `test_ast_cache_returns_same_object_within_ttl` — cache efficace         | HAUTE    |
| RAG       | `test_coder_agent.py`        | `test_ast_cache_invalidated_after_git_commit` — nouveau commit = reindex | MOYENNE  |
| HyDE      | `test_memory_engine.py`      | `test_hyde_reuses_provided_generator` — pas de nouvelle instance         | HAUTE    |
| TTS       | `test_tts_engine.py`         | `test_pyttsx3_fallback_silent` — erreur init = log debug uniquement      | MOYENNE  |
| TTS       | `test_tts_engine.py`         | `test_disabled_tts_no_network_call` — TTS\_ENABLED=False = aucun appel   | MOYENNE  |
| Episodic  | `test_episodic_memory.py`    | `test_sqlite_fts_query_returns_results` — recherche fonctionnelle        | MOYENNE  |
| Safe Mode | `test_config.py`             | `test_safe_mode_disables_heavy_features` — boucle/web/docagent off       | MOYENNE  |

8. Checklist validation (pour IA tierce)
[ ] LLMGeneratorPool possède une méthode unload() et un mécanisme LRU (max 2 modèles)
[ ] CORRECTION_LOOP_ENABLED = False et LLM_GENERATION_MAX_TOTAL_SEC sont dans config.py
[ ] generate() respecte le flag et le timeout (arrêt dur avant max_retries)
[ ] CoderAgent utilise un cache AST TTL 5min invalidé par git rev-parse HEAD
[ ] search_hyde n'instancie jamais de LLMGenerator interne (injection obligatoire)
[ ] TrainingDataCollector n'importe pas torch ni unsloth
[ ] PromptTuner (remplacement GRPO) n'utilise que du prompt engineering
[ ] EpisodicMemory utilise sqlite3 (stdlib) et non duckdb
[ ] TTSEngine utilise pyttsx3 par défaut avec fallback silencieux
[ ] LCCA_SAFE_MODE = True désactive boucle, web search, DocAgent, TTS
[ ] Les 525 tests V8 restent verts
[ ] Nouveaux tests V9 (section 7) passent

============================================================
Fichier : REVIEW-V9-HARDWARE-UPDATE-2026-04-20.md
============================================================

# Addendum Hardware — Impact RAM 24→32 Go sur les specs V9
&lt;!-- AI-READY | Mise à jour contrainte matérielle V9 | 2026-04-20 --&gt;

---

## 1. Synthèse de l'impact

**Ancienne contrainte** : 16 Go RAM (P50 strict)  
**Nouvelle contrainte** : 24 Go actuels → 32 Go prochainement

**Verdict** : La montée en RAM **invalide 3 décisions bloquantes** de la review V9 et **ouvre 2 opportunités** de qualité. Le reste des corrections reste pertinent.

---

## 2. Décisions révisées

### 2.1 V9-01-B Tri-modèle — LRU max 2 → max 3

| Avant (16 Go) | Après (24-32 Go) |
|---------------|------------------|
| `LLMGeneratorPool` avec LRU max 2 (éviction obligatoire) | LRU max 3 modèles simultanés, éviction optionnelle |
| Risque de swap si 3b+7b+14b chargés (~15,5 Go) | Enveloppe mémoire confortable (~15,5 Go + 8 Go marge système) |

**Nouvelle spécification `LLMGeneratorPool` :**

```python
# config.py
LLM_POOL_MAX_LOADED = 3  # Au lieu de 2
# core/llm_generator_pool.py
class LLMGeneratorPool:
    MAX_LOADED = getattr(config, "LLM_POOL_MAX_LOADED", 3)
    # Le reste de l'implémentation reste identique

Bénéfice : Le routage tri-modèle devient transparent. Plus de latence de rechargement entre tools. Le pool sert désormais de cache préventif, pas de garde-fou de survie.
2.2 V9-04-B GRPO — "Reporté V10" → "Micro-GRPO expérimental possible"
| Avant (16 Go)                          | Après (24-32 Go)                                   |
| -------------------------------------- | -------------------------------------------------- |
| GRPO irréaliste (OOM garanti en 4-bit) | GRPO LoRA 4-bit **théoriquement** possible sur CPU |
Cependant : La RAM résout le problème d'espace, pas le problème de temps. Un fine-tuning GRPO sur CPU reste extrêmement lent (4-8 heures par epoch selon Unsloth CPU). La recommandation reste le report à V10, mais avec une nuance :
V9.1 (pas V9.0) : Ajouter un flag GRPO_EXPERIMENTAL_ENABLED pour permettre un micro-fine-tune nocturne (lancer à 18h, récupérer le modèle le lendemain matin). Cela devient une fonctionnalité de niche, pas un pipeline continu.
# config.py
GRPO_EXPERIMENTAL_ENABLED = False  # V9.1 uniquement, nécessite 32 Go + nuit

Le collecteur SFT (V9-04-A) reste la priorité P2. L'accumulation de données ne coûte que du disque.
2.3 V9-05-F TTS — pyttsx3 par défaut → Kokoro viable
| Avant (16 Go)                        | Après (24-32 Go)                                                |
| ------------------------------------ | --------------------------------------------------------------- |
| Kokoro risquait de provoquer du swap | Kokoro (200 Mo + serveur FastAPI) tient largement dans la marge |

Nouvelle décision :
# config.py
TTS_ENGINE = "kokoro"  # Devient le défaut sur 24+ Go
TTS_ENABLED = False    # Toujours opt-in global
pyttsx3 reste le fallback si Kokoro n'est pas installé :

# core/tts_engine.py
def _init_engine(self):
    if self._provider == "kokoro":
        try:
            self._init_kokoro()
        except Exception:
            log.warning("Kokoro indisponible, fallback pyttsx3")
            self._provider = "pyttsx3"
    if self._provider == "pyttsx3":
        self._init_pyttsx3()

Bénéfice : Qualité vocale nettement supérieure (Kokoro est quasi-humain), sans compromis mémoire.
3. Opportunités ouvertes par 32 Go
3.1 Quantification Q5_K_M sur le modèle 14b
Avec 32 Go, on peut envisager une quantification supérieure pour le modèle lourd (meilleure qualité, +20-30 % de précision sur les specs) :
# config.py
OLLAMA_QUANT_LEVEL_HEAVY = "Q5_K_M"  # 14b uniquement
OLLAMA_QUANT_LEVEL_LIGHT = "Q4_K_M"  # 3b/7b — inutile de monter

| Modèle | Q4\_K\_M | Q5\_K\_M | Delta RAM          |
| ------ | -------- | -------- | ------------------ |
| 3b     | ~2,0 Go  | ~2,4 Go  | Négligeable        |
| 7b     | ~4,5 Go  | ~5,5 Go  | Acceptable         |
| 14b    | ~9,0 Go  | ~11,5 Go | **Viable à 32 Go** |

Décision : Ajouter OLLAMA_QUANT_LEVEL_HEAVY dans config.py. Laisser l'utilisateur choisir. Par défaut, rester en Q4_K_M pour la compatibilité, documenter Q5_K_M comme "recommandé si 32 Go".
3.2 Cache AST persistant en mémoire
Avec 24-32 Go, l'index AST complet (52 fichiers → ~5-10 Mo en mémoire) peut rester chargé indéfiniment sans impact :

# core/agents/coder_agent.py
# Avant (16 Go) : TTL 5 min pour libérer la RAM
# Après (24+ Go) : TTL étendu ou infini

_INDEX_CACHE_TTL = getattr(config, "AST_INDEX_CACHE_TTL", 3600)  # 1 heure au lieu de 5 min

4. Ce qui NE change PAS
| Élément                          | Pourquoi                                                                                                                                                 |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **V9-02-B Boucle de correction** | `CORRECTION_LOOP_ENABLED = False` par défaut reste valide. Ce n'est pas une question de RAM, mais de latence CPU (3× 60-180 s = timeout utilisateur).    |
| **V9-03-A Cache AST**            | Le cache reste nécessaire, même avec 32 Go. L'invalidation git reste la bonne pratique. La RAM supplémentaire permet juste une TTL plus longue.          |
| **V9-05-E SQLite FTS5**          | DuckDB devient viable en RAM, mais reste une dépendance compilée lourde sur Windows. SQLite FTS5 (stdlib) reste la meilleure option pour la portabilité. |
| **Safe Mode**                    | `LCCA_SAFE_MODE` reste pertinent. Ce n'est pas une question de ressources, mais de prévisibilité.                                                        |
| **V9-04-C Pipeline continu**     | Reporté V10. La RAM ne change pas le fait qu'un fine-tune CPU prend des heures.                                                                          |

5. Tableau de décision révisé (diff vs review précédente)
| Sous-sprint            | Décision Review 16 Go | Décision Révisée 24-32 Go               | Justification                       |
| ---------------------- | --------------------- | --------------------------------------- | ----------------------------------- |
| V9-01-B Pool LRU       | max 2                 | **max 3**                               | 15,5 Go modèles + marge confortable |
| V9-01-B Quantif lourde | Q4\_K\_M obligatoire  | **Q4\_K\_M défaut, Q5\_K\_M option**    | 32 Go permet +2,5 Go pour qualité   |
| V9-04-B GRPO           | Reporté V10           | **Reporté V10, flag expérimental V9.1** | RAM OK, temps CPU toujours bloquant |
| V9-05-F TTS            | pyttsx3 défaut        | **Kokoro défaut, pyttsx3 fallback**     | 200 Mo négligeable sur 24+ Go       |
| V9-03-A Cache TTL      | 5 min                 | **1 heure (ou infini)**                 | Index AST de 10 Mo = gratuit        |

6. Checklist validation matérielle
[ ] LLM_POOL_MAX_LOADED = 3 dans config.py
[ ] OLLAMA_QUANT_LEVEL_HEAVY = "Q4_K_M" configurable vers "Q5_K_M"
[ ] TTS_ENGINE = "kokoro" par défaut sur machines ≥ 24 Go (détection auto ou flag manuel)
[ ] AST_INDEX_CACHE_TTL configurable (défaut 3600s)
[ ] GRPO_EXPERIMENTAL_ENABLED = False (V9.1 uniquement, documenté comme "nécessite nuitée")
[ ] Détection RAM au boot : si < 16 Go, forcer LLM_POOL_MAX_LOADED = 2 et TTS_ENGINE = "pyttsx3"
7. Détection RAM automatique (recommandé)
# core/hardware_profile.py
import psutil

def detect_hardware_profile() -> dict:
    ram_gb = psutil.virtual_memory().total // (1024**3)
    
    if ram_gb >= 32:
        return {
            "pool_max_loaded": 3,
            "quant_heavy": "Q5_K_M",
            "tts_default": "kokoro",
            "ast_cache_ttl": 3600,
            "grpo_experimental": True,
        }
    elif ram_gb >= 24:
        return {
            "pool_max_loaded": 3,
            "quant_heavy": "Q4_K_M",
            "tts_default": "kokoro",
            "ast_cache_ttl": 3600,
            "grpo_experimental": False,
        }
    else:  # < 24 Go
        return {
            "pool_max_loaded": 2,
            "quant_heavy": "Q4_K_M",
            "tts_default": "pyttsx3",
            "ast_cache_ttl": 300,
            "grpo_experimental": False,
        }

Bénéfice : LCCA s'adapte automatiquement au hardware sans intervention utilisateur.
8. Décision finale
La RAM 24→32 Go transforme V9 d'un système "resserré" en un système "confortable".
3 modèles simultanés deviennent la norme (plus d'éviction LRU stricte)
Kokoro devient le TTS par défaut
Q5_K_M devient une option de qualité viable pour le 14b
GRPO reste reporté V10, mais une porte expérimentale s'ouvre en V9.1
Le cache AST peut devenir quasi-permanent
Les 5 corrections bloquantes restent valides (boucle de correction, cache AST, Safe Mode, SQLite FTS5, collecteur SFT uniquement). Seules les contraintes de RAM sont relâchées.
<!-- AI-READY | Addendum Hardware V9 | 2026-04-20 -->