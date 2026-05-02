============================================================
Fichier : REVIEW-V9-TECHNIQUE-2026-04-20.md
============================================================

# Review Technique — Spécifications LCCA V9
&lt;!-- AI-READY | Review critique V9 | Version 9.0.0-review | 2026-04-20 --&gt;

**Auteur review** : Analyse automatique post-upload  
**Périmètre** : 5 specs (V9-01 à V9-05) + README contextuel  
**Objectif** : Validation d'architecture avant implémentation, identification des blocages et contradictions vs V5/V7/V8.

---

## 1. Synthèse exécutive

| Critère | Verdict | Commentaire |
|---------|---------|-------------|
| Cohérence V5/V7/V8 | ⚠️ **Partielle** | Quelques contradictions majeures (CPU-first vs fine-tuning, indexation à chaque appel) |
| Faisabilité P50 (16GB, CPU) | ⚠️ **Risquée** | V9-04 (GRPO) et V9-05-F (Kokoro) poussent la machine hors de ses limites |
| Qualité des specs | ✅ **Bonne** | Dataclasses, tests, pré/postconditions bien présents |
| Rétrocompatibilité | ⚠️ **À renforcer** | Boucle de correction V9-02-B change silencieusement le comportement de `generate()` |
| Sécurité | ✅ **Correcte** | `safe_path`, sandbox, compilation sans exécution respectés |
| Priorisation | ✅ **Bonne** | P0/P1/P2/P3/P4 cohérent avec la valeur métier |

**Verdict global** : **Validable sous réserve de 5 corrections bloquantes** (section 3). Les specs V9-01, V9-02, V9-03 et V9-05-A/B/C sont prêtes pour implémentation. V9-04 et V9-05-F nécessitent une refonte ou un downgrade de scope.

---

## 2. Analyse détaillée par axe

### 2.1 V9-01 — Optimisation LLM (Performance)

| Sous-sprint | État | Analyse |
|-------------|------|---------|
| **V9-01-A Q4_K_M + keep_alive** | ✅ Accepté | `keep_alive` est une optimisation gratuite. La quantification Q4_K_M est pertinente pour P50. **Attention** : il faut documenter la commande `ollama pull` exacte dans le README d'installation. |
| **V9-01-B Tri-modèle** | ⚠️ **À corriger** | Le helper `_get_generator()` crée une **nouvelle instance** `LLMGenerator` à chaque appel. Sur P50, changer de modèle Ollama entraîne un déchargement/rechargement en RAM (5-15s). **Proposition** : utiliser un pool de générateurs singletons (un par modèle) ou forcer `keep_alive` sur les 3 modèles simultanément (mais 3b+7b+14b = ~15GB RAM, trop pour 16GB). **Décision recommandée** : singleton par modèle avec gestion de mémoire (décharger le 14b quand on utilise le 3b). |
| **V9-01-C Streaming universel** | ✅ Accepté | Le fallback bloquant en cas d'échec stream est bien pensé. Vérifier que `generate_stream` retourne bien `str` et pas un générateur dans le cas d'erreur. |

**Recommandation V9-01** : Ajouter un `LLMGeneratorPool` :

```python
class LLMGeneratorPool:
    _instances: dict[str, LLMGenerator] = {}
    
    def get(self, model: str) -&gt; LLMGenerator:
        if model not in self._instances:
            self._instances[model] = LLMGenerator(model=model)
        return self._instances[model]

2.2 V9-02 — Qualité des réponses LLM
| Sous-sprint                       | État            | Analyse                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| --------------------------------- | --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **V9-02-A Few-shot SkillLibrary** | ✅ Accepté       | Connexion logique entre V8 (SkillLibrary) et PromptBuilder. Le paramètre `skill_context` par défaut `""` préserve la rétrocompatibilité.                                                                                                                                                                                                                                                                                                                                           |
| **V9-02-B Boucle de correction**  | 🔴 **Bloquant** | Changement de comportement silencieux de `LLMGenerator.generate()`. Avant : 1 appel, fallback immédiat. Après : jusqu'à 3 appels + évaluation. **Sur P50, 3×60s = 180s minimum**, sans compter le `CodeEvaluator`. Si le modèle sélectionné est le 14b (180s), on atteint **540s (9 minutes)** avant fallback. **De plus** : le paramètre `max_retries` est hardcodé à 2 dans la méthode, pas configurable par `config.py` (alors que `LLM_MAX_CORRECTION_RETRIES` est mentionné). |
| **V9-02-C AST context**           | ✅ Accepté       | Bonne idée, mais `_build_ast_context` appelle `index_repository()` qui est **linéaire en nombre de fichiers**. Sur un workspace de 50+ fichiers, c'est acceptable. Sur 200+ fichiers, il faudra un cache.                                                                                                                                                                                                                                                                          |
| **V9-02-D JSON mode**             | ✅ Accepté       | `"format": "json"` est bien supporté par Ollama ≥0.1.14. Vérifier que Qwen2.5-coder le respecte (il devrait).                                                                                                                                                                                                                                                                                                                                                                      |

Recommandation V9-02-B :
Flag de désactivation : CORRECTION_LOOP_ENABLED = False par défaut en V9.0, opt-in.
Timeout global : LLM_GENERATION_MAX_TOTAL_SEC = 120 pour couper la boucle.
Config effective : utiliser config.LLM_MAX_CORRECTION_RETRIES (actuellement la spec mentionne la constante mais le code utilise _MAX_RETRIES = 2 hardcodé).
Métrique : logger le nombre de tentatives pour ajuster le seuil.
2.3 V9-03 — Agentic RAG
| Sous-sprint                          | État                 | Analyse                                                                                                                                                                                                                                                                                                                                                                             |
| ------------------------------------ | -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **V9-03-A Repo-RAG**                 | 🔴 **Bloquant perf** | `_retrieve_repo_context` appelle `ASTIndexer().index_repository()` **à chaque génération**. Sur P50, indexer 52 fichiers prend ~2-3s. Multiplié par le nombre d'appels dans la KarpathyLoop (max 20 itérations), c'est **40-60s de pure perte**. **Solution** : injecter l'`ASTIndexer` déjà initialisé (V8 l'a déjà dans `AgentOrchestrator`) ou ajouter un cache TTL sur l'index. |
| **V9-03-B Web search auto**          | ✅ Accepté            | Heuristique `_detect_external_libs` simple et efficace. Le fallback silencieux est bien.                                                                                                                                                                                                                                                                                            |
| **V9-03-C HyDE**                     | ✅ Accepté            | Désactivé par défaut (`MEMORY_HYDE_ENABLED = False`). Cohérent avec la contrainte CPU. **Attention** : `search_hyde` crée un `LLMGenerator()` par défaut si `generator is None`, ce qui recharge un modèle. Passer toujours le générateur existant.                                                                                                                                 |
| **V9-03-D Doc retrieval erreur API** | ✅ Accepté            | Excellent pattern. L'enrichissement de réflexion avec la doc officielle est une vraie plus-value pour la boucle de correction.                                                                                                                                                                                                                                                      |

Recommandation V9-03-A :
# Dans CoderAgent.__init__ — conserver une référence
self._indexer = ASTIndexer(workspace=config.WORKSPACE_DIR)
self._index_cache: Optional[dict] = None
self._index_cache_ts: float = 0
self._INDEX_CACHE_TTL = 300  # 5 minutes

def _get_index(self):
    if self._index_cache is None or (time.time() - self._index_cache_ts) > self._INDEX_CACHE_TTL:
        self._index_cache = self._indexer.index_repository()
        self._index_cache_ts = time.time()
    return self._index_cache

2.4 V9-04 — Pipeline d'entraînement (SFT + GRPO)
| Aspect                     | État                     | Analyse                                                                                                                                                                                                                                                                                          |
| -------------------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Collecteur SFT**         | ✅ Accepté                | `TrainingDataCollector` est bien conçu, déduplique, exporte ShareGPT/Alpaca.                                                                                                                                                                                                                     |
| **Fonction de récompense** | ✅ Accepte                | `lcca_code_reward` est cohérente avec `CodeEvaluator`. La compilation sans exécution est sûre.                                                                                                                                                                                                   |
| **GRPO / Unsloth**         | 🔴 **Bloquant hardware** | **Contradiction majeure avec le principe "CPU-first"**. Même en 4-bit LoRA, un fine-tuning GRPO sur CPU prend **des heures par epoch** (Unsloth est optimisé GPU CUDA). Sur P50 sans GPU dédié, c'est irréaliste. Le README mentionne "CPU uniquement pour Ollama", puis propose du fine-tuning. |
| **Pipeline continu**       | ⚠️ **Trop tôt**          | Le hot-swap de modèle Ollama (`ollama create`) nécessite de redémarrer le serveur Ollama ou de créer un nouveau tag. C'est faisable, mais le micro-fine-tune toutes les 50 paires sur CPU est une illusion de performance.                                                                       |

Recommandation V9-04 :
Scope V9.0 : Conserver uniquement le collecteur de données (TrainingDataCollector). C'est déjà une valeur énorme (export vers un environnement GPU externe, ou accumulation pour un futur fine-tuning).
GRPO : Reporter à V10 avec pré-requis "GPU dédié ou cloud compute".
Remplacement V9 : Ajouter un "Prompt Tuning Automatique" à la place : ajuster dynamiquement les prompts système selon les skills les plus utilisés (in-context learning, pas de fine-tuning de poids).
2.5 V9-05 — Agents créatifs
| Sous-sprint                     | État                     | Analyse                                                                                                                                                                                                                                                                                                                                                     |
| ------------------------------- | ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **V9-05-A QAAgent**             | ✅ Accepté                | Excellent. Lecture seule, règles pertinentes, thread daemon. Les règles `_rule_hardcoded_python` et `_rule_direct_file_write` sont des garde-fous essentiels.                                                                                                                                                                                               |
| **V9-05-B DocAgent**            | ✅ Accepté                | Bon concept. Le flag `DOCAGENT_AUTO_CONFIRM = False` par défaut est indispensable. Le hook git PowerShell est une bonne idée mais doit être documenté comme optionnel.                                                                                                                                                                                      |
| **V9-05-C Pair Programmer**     | ✅ Accepté                | HITL bien intégré. Le callback `hitl_callback` est injecté proprement.                                                                                                                                                                                                                                                                                      |
| **V9-05-D Dashboard Analytics** | ✅ Accepté                | Dépendances UI (recharts) acceptables. Les métriques sont bien définies.                                                                                                                                                                                                                                                                                    |
| **V9-05-E Mémoire épisodique**  | ⚠️ **À corriger**        | DuckDB est une dépendance compilée lourde (~50MB wheel). Sur Windows, l'installation peut échouer si Visual C++ Redist manque. **Alternative** : SQLite avec FTS5 (déjà dans stdlib Python 3.11+). Si le besoin est purement textuel (pas de vecteurs), SQLite FTS5 suffit. Si embeddings nécessaires plus tard, migrer vers ChromaDB (déjà dans la stack). |
| **V9-05-F TTS Kokoro**          | 🔴 **Bloquant hardware** | Kokoro-FastAPI nécessite un serveur en arrière-plan + modèle ~200MB. Avec Ollama 7b (~4-9GB) déjà en RAM, ajouter Kokoro sur P50 (16GB total) risque de provoquer du swap et de ralentir drastiquement Ollama. **Alternative** : `pyttsx3` (Windows SAPI5 natif, 0MB de modèle, offline) ou `piper-tts` (beaucoup plus léger).                              |

Recommandation V9-05 :
E : Remplacer DuckDB par sqlite3 avec FTS5 pour V9.0. Migrer vers ChromaDB (déjà dépendance) si besoin d'embeddings en V10.
F : Remplacer Kokoro par pyttsx3 pour V9.0. Kokoro peut être un plugin optionnel V9.2.
3. Problèmes transversaux critiques
3.1 🔴 Contradiction "CPU-first" vs Fine-tuning GRPO (V9-04)
Impact : Bloquant. Le fine-tuning local GRPO est irréaliste sur P50.
Correction : V9-04 se limite au collecteur SFT. GRPO reporté V10.
3.2 🔴 Indexation AST répétée (V9-03-A)
Impact : Performance. Jusqu'à 60s de perdues par KarpathyLoop sur P50.
Correction : Cache TTL 5min sur l'index AST dans CoderAgent.
3.3 🔴 Boucle de correction silencieuse (V9-02-B)
Impact : Rétrocompatibilité + Timeout. generate() devient 3× plus lent sans avertissement.
Correction : CORRECTION_LOOP_ENABLED = False par défaut. Timeout global configurable.
3.4 🔴 Tri-modèle sans pool (V9-01-B)
Impact : Latence. Rechargement Ollama à chaque changement de tool.
Correction : LLMGeneratorPool singleton avec gestion mémoire.
3.5 🟡 TTS Kokoro trop lourd (V9-05-F)
Impact : RAM. Risque de swap sur P50.
Correction : pyttsx3 par défaut, Kokoro en option avancée.
4. Tableau de décision par sous-sprint
| Sous-sprint | Décision               | Action requise                                       |
| ----------- | ---------------------- | ---------------------------------------------------- |
| V9-01-A     | ✅ Implémenter          | Tel quel                                             |
| V9-01-B     | ⚠️ Implémenter corrigé | Ajouter `LLMGeneratorPool`                           |
| V9-01-C     | ✅ Implémenter          | Tel quel                                             |
| V9-02-A     | ✅ Implémenter          | Tel quel                                             |
| V9-02-B     | ⚠️ Implémenter corrigé | Flag `CORRECTION_LOOP_ENABLED=False`, timeout global |
| V9-02-C     | ✅ Implémenter          | Tel quel                                             |
| V9-02-D     | ✅ Implémenter          | Tel quel                                             |
| V9-03-A     | ⚠️ Implémenter corrigé | Cache AST 5min                                       |
| V9-03-B     | ✅ Implémenter          | Tel quel                                             |
| V9-03-C     | ✅ Implémenter          | Tel quel (désactivé par défaut)                      |
| V9-03-D     | ✅ Implémenter          | Tel quel                                             |
| V9-04-A     | ✅ Implémenter          | Tel quel (collecteur uniquement)                     |
| V9-04-B     | ❌ Reporter V10         | GRPO nécessite GPU                                   |
| V9-04-C     | ❌ Reporter V10         | Pipeline continu nécessite V9-04-B                   |
| V9-05-A     | ✅ Implémenter          | Tel quel                                             |
| V9-05-B     | ✅ Implémenter          | Tel quel                                             |
| V9-05-C     | ✅ Implémenter          | Tel quel                                             |
| V9-05-D     | ✅ Implémenter          | Tel quel                                             |
| V9-05-E     | ⚠️ Implémenter corrigé | SQLite FTS5 au lieu de DuckDB                        |
| V9-05-F     | ⚠️ Implémenter corrigé | `pyttsx3` par défaut                                 |

5. Spécifications complémentaires requises
5.1 LLMGeneratorPool (nouveau fichier)
# core/llm_generator_pool.py
class LLMGeneratorPool:
    """Pool singleton de LLMGenerator par modèle. Évite les rechargements Ollama."""
    _pool: dict[str, LLMGenerator] = {}
    _lock = threading.Lock()
    
    @classmethod
    def get(cls, model: str, timeout: int = 90, max_tokens: int = 512) -> LLMGenerator:
        key = f"{model}:{timeout}:{max_tokens}"
        with cls._lock:
            if key not in cls._pool:
                cls._pool[key] = LLMGenerator(model=model, timeout=timeout, max_tokens=max_tokens)
            return cls._pool[key]
    
    @classmethod
    def clear(cls):
        cls._pool.clear()

5.2 Timeout global de génération
# config.py
LLM_GENERATION_MAX_TOTAL_SEC = 120   # Timeout global pour generate() incluant retries
CORRECTION_LOOP_ENABLED = False      # Opt-in pour V9.0

5.3 Cache AST dans CoderAgent
# core/agents/coder_agent.py — ajout dans __init__
self._ast_index_cache: Optional[dict] = None
self._ast_index_cache_ts: float = 0

6. Checklist validation (pour IA tierce)
[ ] LLMGenerator.generate() respecte CORRECTION_LOOP_ENABLED (False par défaut)
[ ] LLMGenerator.generate() respecte LLM_GENERATION_MAX_TOTAL_SEC (arrêt dur)
[ ] _get_generator() utilise LLMGeneratorPool.get() et non LLMGenerator() direct
[ ] CoderAgent._retrieve_repo_context() utilise un cache AST TTL 5min
[ ] TrainingDataCollector ne dépend pas d'Unsloth ni de GPU
[ ] TrainingDataCollector.export() produit du JSONL valide ShareGPT
[ ] QAAgent ne modifie aucun fichier (lecture seule uniquement)
[ ] DocAgent respecte DOCAGENT_AUTO_CONFIRM = False (pas d'écriture sans confirmation)
[ ] EpisodicMemory utilise sqlite3 (stdlib) et non duckdb (externe)
[ ] TTS utilise pyttsx3 par défaut, Kokoro est optionnel
[ ] Les 237 tests V5 restent verts
[ ] Les tests V7/V8 restent verts
[ ] Nouveaux tests V9 passent (525+ attendus)
7. Décision finale
Les specs V9 sont validées pour implémentation sous réserve des 5 corrections bloquantes suivantes :
V9-04 : Scope réduit au collecteur SFT uniquement (pas de GRPO local)
V9-01-B : Ajout du LLMGeneratorPool
V9-02-B : CORRECTION_LOOP_ENABLED = False par défaut + timeout global
V9-03-A : Cache AST 5min dans CoderAgent
V9-05-E/F : SQLite FTS5 et pyttsx3 par défaut