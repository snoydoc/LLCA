# BENCHMARK EXPERIENCE LOG
# Base de connaissance pour une application de benchmark LLM universelle
# Machine : OMEN HP | GPU : Quadro M2000M (4 GB VRAM, CUDA) | RAM : ~32 GB
# Runtime : Ollama (local) | OS : Windows 11
# Dernier update : 2026-04-27
#
# FORMAT : Markdown + sections structurees
# Ce fichier est la SOURCE DE VERITE pour les decisions de configuration
# du benchmark. Toute anomalie observee doit etre consignee ici.

---

## 1. HISTORIQUE DES VERSIONS

| Version | Date       | Statut  | Note principale                                      |
|---------|------------|---------|------------------------------------------------------|
| V1      | 2026-??    | Archive | Prototype initial                                    |
| V2      | 2026-??    | Archive | Ajout GPU/CPU tiering                                |
| V3      | 2026-??    | Archive | Reprise basique                                      |
| V4      | 2026-04-27 | CRASH   | OOM crash sur gemma4:e4b (14 GB RAM Ollama)          |
| V5      | 2026-??    | Archive | Intermediaire                                        |
| V6      | 2026-04-27 | Stable  | Reprise granulaire par run. Dashboard. ErrLog JSON   |
| V7      | 2026-04-27 | ACTUEL  | Garde-fous RAM + fix tokens multipliers + timeouts   |

---

## 2. CONFIGURATION MATERIELLE

```
GPU  : NVIDIA Quadro M2000M
VRAM : 4096 MB
CUDA : oui
CPU  : Intel Core i7 (mobile, generation 6-7)
RAM  : ~32 GB
Disk : D:\ (modeles Ollama : D:\Continue\Ollama\models)
OS   : Windows 11
```

### Seuils de securite memoire (V7+)
```
RAM_FREE_MIN_MB   = 3000   # RAM systeme libre minimum avant chargement modele
OLLAMA_RAM_MAX_MB = 13000  # RAM Ollama max apres warmup (au-dela -> skip)
GPU_TEMP_WARN_C   = 85     # Alerte temperature GPU
```

### Pourquoi ces seuils ?
- gemma4:e4b a consomme 14 451 MB RAM Ollama -> crash systeme OOM en V4
- Le seuil 13 000 MB coupe avant cette valeur critique
- 3 000 MB libres minimum = marge de securite pour le systeme Windows

---

## 3. MODELES BENCHMARKES

### Tier GPU (num_gpu=-1, VRAM preferee)

| Modele                     | Famille | Params | Quant   | VRAM obs. | RAM obs.  | Statut V4 |
|----------------------------|---------|--------|---------|-----------|-----------|-----------|
| qwen2.5-coder:3b           | qwen2   | 3.1B   | Q4_K_M  | 2259 MB   | ~5200 MB  | OK        |
| gemma4:e2b                 | gemma4  | 5.1B   | Q4_K_M  | 2157 MB   | ~11600 MB | VIDES     |
| qwen3:4b                   | qwen3   | 4.0B   | Q4_K_M  | 2865 MB   | ~6150 MB  | PARTIEL   |
| phi4-mini-reasoning:latest | phi3    | 3.8B   | Q4_K_M  | 3997 MB   | ~9280 MB  | TIMEOUT   |
| gemma3:4b                  | gemma3  | 4.3B   | Q4_K_M  | 2381 MB   | ~7350 MB  | TRUNCATED |
| gemma4:e4b                 | gemma4  | 8.0B   | Q4_K_M  | 2994 MB   | ~14450 MB | CRASH OOM |

### Tier CPU (num_gpu=0, RAM uniquement)

| Modele                      | Famille      | Params | Quant   | Statut V4 |
|-----------------------------|--------------|--------|---------|-----------|
| deepseek-r1:8b              | deepseek     | 8B     | Q4_K_M  | Non teste |
| qwen3:8b                    | qwen3        | 8B     | Q4_K_M  | Non teste |
| qwen3:14b                   | qwen3        | 14B    | Q4_K_M  | Non teste |
| deepseek-r1:14b             | deepseek     | 14B    | Q4_K_M  | Non teste |
| qwen3-coder:30b-a3b-q4_K_M | qwen3-coder  | 30B    | Q4_K_M  | Non teste |
| qwen3:30b-a3b               | qwen3        | 30B    | Q4_K_M  | Non teste |

---

## 4. RESULTATS OBSERVES (V4, session 2026-04-27 00:46)

### Performances GPU confirmees

| Modele                     | tok/s moy | VRAM   | RAM Ollama | Qualite reponse      |
|----------------------------|-----------|--------|------------|----------------------|
| qwen2.5-coder:3b           | **11.1**  | 2259MB | 5220MB     | Excellente (stop)    |
| gemma4:e2b                 | 9.1       | 2157MB | 11600MB    | Mauvaise (6/9 vides) |
| qwen3:4b                   | 8.0       | 2865MB | 6150MB     | Partielle (instable) |
| phi4-mini-reasoning:latest | 5.9       | 3997MB | 9280MB     | Timeout coding_lcca  |
| gemma3:4b                  | 8.0       | 2381MB | 7350MB     | Tronquee code_simple |
| gemma4:e4b                 | CRASH     | 2994MB | 14450MB    | OOM systeme          |

### Valeurs de reference par modele (V4 raw)

```
qwen2.5-coder:3b
  code_simple : 11.03 / 11.04 / 11.04 tok/s | 25702 / 24193 / 26143 ms | 269/261/261 tok | done=stop
  debug       : 11.28 / 11.26 / 11.24 tok/s | 17541 / 16514 / 16570 ms | 184/181/181 tok | done=stop
  coding_lcca : 10.48 / 10.49 / 10.52 tok/s | 53831 / 47711 / 47574 ms | 538/492/492 tok | done=stop

gemma4:e2b
  code_simple : 9.50 / 9.53 / 9.56 tok/s | done=length | resp_len=0 (VIDE)
  debug       : 9.55 / 9.48 / 9.35 tok/s | 1/3 OK (len=454), 2/3 VIDE
  coding_lcca : 8.39 / 8.37 / 8.39 tok/s | done=stop | len=4340/4194/4194 (OK)

qwen3:4b  [reasoning=True, temp=0.6]
  code_simple : 8.07 (VIDE) / 8.06 (OK len=2729) / 8.09 (OK len=2729)
  debug       : 8.08 (VIDE) / 8.10 (OK len=906) / 8.13 (OK len=906)
  coding_lcca : 7.73 / 7.82 / 8.13 tok/s | done=length | len=494 (TRONQUE)

phi4-mini-reasoning  [reasoning=True, temp=0.6]
  code_simple : 6.20 / 6.05 / 6.08 tok/s | done=length | len=4611/4574/4574 (TRONQUE)
  debug       : 5.79 (TRONQUE) / 5.42 (OK) / 5.62 (OK)
  coding_lcca : TIMEOUT x3 (600s insuffisant)

gemma3:4b
  code_simple : 7.81 / 7.77 / 7.79 tok/s | done=length | len=1436-1440 (TRONQUE)
  debug       : 7.81 / 8.39 / 8.15 tok/s | done=stop | OK
  coding_lcca : 8.09 / 8.09 / 8.05 tok/s | done=stop | OK
```

---

## 5. ANOMALIES ET CORRECTIONS

### ANOMALIE-001 : OOM systeme (crash) sur gemma4:e4b
- **Symptome** : Crash Windows brutal en cours de coding_lcca run 1
- **Cause** : gemma4:e4b consomme 14 451 MB RAM Ollama. Windows OOM-kills.
- **Detection** : Log s'arrete brutalement sans message d'erreur
- **Correction V7** : Garde-fou OLLAMA_RAM_MAX_MB=13000 apres warmup -> skip avant inference
- **Statut** : Corrige

### ANOMALIE-002 : Reponses vides systematiques (gemma4:* )
- **Symptome** : resp_len=0, done_reason=length, eval_count=512
- **Cause** : Modeles gemma4 utilisent un "thinking block" interne qui consomme
              tout le budget de tokens avant la reponse visible. A 512 tokens,
              le thinking epuise le budget et la reponse finale est vide.
- **Preuve** : coding_lcca (2048 tokens) produit des reponses OK (4340 chars)
              code_simple (512 tokens) produit des reponses vides
- **Correction V7** : Multiplicateur tokMult=4 pour famille gemma4
              code_simple : 512 x 4 = 2048 tokens
              debug       : 512 x 4 = 2048 tokens
              coding_lcca : 2048 x 4 = 8192 tokens
- **Statut** : Corrige

### ANOMALIE-003 : Timeout systematique phi4-mini-reasoning (coding_lcca)
- **Symptome** : 3/3 timeout a exactement 600s sur coding_lcca
- **Cause** : Le modele reasoning genere un long <think> avant la reponse.
              Sur coding_lcca (prompt long + 4096 tokens predict), depasse 10 min.
- **Preuve** : code_simple et debug terminent OK (resp_len=4611/4910)
              coding_lcca timeout pile a 600s x3
- **Correction V7** : TimeoutOverrides["phi4-mini-reasoning:latest"] = 7200s
              + tokMult=3 pour famille phi3 (reasoning)
- **Statut** : Corrige

### ANOMALIE-004 : Truncation gemma3 (code_simple)
- **Symptome** : done_reason=length sur code_simple, mais resp_len=1436 (OK partiel)
- **Cause** : 512 tokens insuffisants pour reponse complete de gemma3:4b
- **Correction V7** : tokMult=2 pour famille gemma3
- **Statut** : Corrige

### ANOMALIE-005 : Instabilite qwen3 reasoning (runs vides aleatoires)
- **Symptome** : Run 1 vide, run 2-3 OK sur code_simple et debug
- **Cause** : A temperature=0.6, le premier run utilise plus de tokens reasoning
              que les suivants (pas de cache). 1024 tokens insuffisants pour run 1.
- **Correction V7** : tokMult=3 pour famille qwen3 (reasoning)
              code_simple : 512 x 3 x 2 (reasoning) = 3072 tokens
- **Statut** : Corrige

### ANOMALIE-006 : Reprise au niveau modele (V4) insuffisante
- **Symptome** : En cas de crash au run 2, tout le modele est reperdu
- **Cause** : V4 ne sauvegarde la progression qu'apres modele complet
- **Correction V6/V7** : Reprise granulaire par run individuel
              Cle : "run_MODEL__PROMPT__RUN" dans JSON progress
              Export CSV incremental apres chaque run
- **Statut** : Corrige (V6+)

---

## 6. REGLES DE CONFIGURATION (pour application universelle)

### Regles num_predict par famille

```
REGLE-TOKEN-001 : Famille gemma4
  Raison   : Thinking block natif consomme les tokens avant la reponse
  Signe    : resp_len=0, done_reason=length, eval_count=max
  Fix      : num_predict = base x 4
  Detecte  : 2026-04-27 | Confirme sur gemma4:e2b et gemma4:e4b

REGLE-TOKEN-002 : Famille phi3 (phi4-mini-reasoning)
  Raison   : Grand chain-of-thought en <think> avant reponse
  Signe    : resp_len >> normal, done_reason=length, reponse contient "<think>"
  Fix      : num_predict = base x 3 | timeout x12 sur prompts longs
  Detecte  : 2026-04-27 | Confirme sur phi4-mini-reasoning

REGLE-TOKEN-003 : Famille qwen3 (reasoning)
  Raison   : Chain of thought pre-reponse variable selon le contexte
  Signe    : Run 1 vide, runs suivants OK (budget epuise au 1er run cold)
  Fix      : num_predict = base x 3 (x2 supplementaire si isReasoning=True)
  Detecte  : 2026-04-27 | Confirme sur qwen3:4b

REGLE-TOKEN-004 : Famille gemma3
  Raison   : Reponses verboses, 512 insuffisant
  Signe    : done_reason=length mais resp_len exploitable
  Fix      : num_predict = base x 2
  Detecte  : 2026-04-27 | Confirme sur gemma3:4b

REGLE-TOKEN-005 : Families sans thinking block (qwen2, deepseek base)
  Fix      : num_predict = base x 1
```

### Detection automatique du thinking block
```
HEURISTIQUE : Si resp_len=0 AND done_reason=length AND eval_count=max_tokens
              => Le modele a un thinking block. Multiplier num_predict x4.
HEURISTIQUE : Si resp_snippet contient "<think>" ou "[THINK]"
              => Modele reasoning. Multiplier num_predict x2 minimum.
```

### Regles de timeout

```
REGLE-TIMEOUT-001 : Modeles CPU (num_gpu=0)
  Valeur   : 3600s (1 heure)
  Raison   : Gros modeles (14B-30B) peuvent prendre > 20 min sur coding_lcca

REGLE-TIMEOUT-002 : Modeles reasoning GPU sur prompts longs
  Valeur   : 7200s si famille phi3/qwen3 + prompt coding_lcca
  Raison   : phi4-mini-reasoning timeout a 600s x3 en V4

REGLE-TIMEOUT-003 : Modeles GPU standard
  Valeur   : 600s (10 min)
```

### Regles de securite memoire

```
REGLE-RAM-001 : Verification RAM systeme avant chargement
  Seuil    : RAM_FREE_MIN_MB = 3000 MB
  Action   : Skip modele si RAM libre < seuil
  Raison   : Evite OOM systeme (crash Windows brutal)

REGLE-RAM-002 : Verification RAM Ollama apres warmup
  Seuil    : OLLAMA_RAM_MAX_MB = 13000 MB
  Action   : Unload + skip si Ollama depasse le seuil
  Raison   : gemma4:e4b = 14451 MB -> crash V4
  Formule  : Get-Process ollama* | Measure PrivateMemorySize64 -Sum / 1MB

REGLE-RAM-003 : Modeles a haut risque identifies
  gemma4:e4b -> 14451 MB RAM Ollama -> INTERDIT sans RAM > 24 GB
  gemma4:e2b -> 11600 MB RAM Ollama -> Prudence sur machines < 16 GB
```

### Regles de reprise (crash recovery)

```
REGLE-RESUME-001 : Granularite de sauvegarde = niveau run individuel
  Format cle   : "run_{MODEL_SAFE}__{PROMPT}__{N}" = "ok|error"
  Format modele: "done_{MODEL}" = "ok|skip|skip_warmup|skip_oom"
  Fichier      : overnight_vX_progress.json dans results/

REGLE-RESUME-002 : Export CSV incremental apres chaque run
  Fichier      : bench_gpu_incremental.csv
  Recharge     : Import-Csv au demarrage si reprise
  Raison       : Aucune perte de donnee entre deux modeles

REGLE-RESUME-003 : Modes de skip a distinguer
  "ok"           : Modele termine avec succes
  "skip"         : Modele non disponible localement
  "skip_warmup"  : Warmup echoue 2x
  "skip_oom"     : Skip preventif RAM (nouveau V7)
  "error"        : Run individuel en erreur (sera retente au prochain lancement)
```

---

## 7. PROMPTS DE BENCHMARK

### Prompts actuels (V4-V7)

#### code_simple (tokens base : 512)
```
Write a Python function named days_between that takes two date strings
(YYYY-MM-DD) and returns the number of days between them.
Include a docstring and a usage example.
```
Teste : Generation de code simple avec docstring

#### debug (tokens base : 512)
```
Here is a buggy Python function:

def average(lst):
    return sum(lst) / len(lst)

It crashes with ZeroDivisionError when the list is empty.
Identify the bug and provide a complete fixed version.
```
Teste : Identification et correction de bug

#### coding_lcca (tokens base : 2048)
```
You are a Python code assistant. Refactor the following class.
Rules: use pathlib.Path not os.path, PascalCase for classes,
snake_case for functions, docstring on every function, handle edge cases,
return complete file without truncation.
[+ code source fileManager]
```
Teste : Refactoring complexe, instruction-following, completude

### Criteres d'evaluation qualitative
```
CRITERE-Q001 : Reponse complete (done_reason=stop)
CRITERE-Q002 : Longueur minimale acceptable : 100 chars
CRITERE-Q003 : Presence du code fonctionnel (heuristique : contient "def " ou "class ")
CRITERE-Q004 : Presence docstring (heuristique : contient '"""' ou "'''")
CRITERE-Q005 : Reponse non-vide sur les 3 runs (stabilite)
```

---

## 8. METRIQUES COLLECTEES (schema CSV)

```
model             : Nom complet Ollama (ex: qwen2.5-coder:3b)
tier              : GPU | CPU
prompt            : code_simple | debug | coding_lcca
run               : 1 | 2 | 3
tok_s             : Tokens par seconde (eval_rate ou eval_count/eval_duration*1e9)
tokens_out        : Nombre de tokens generes (eval_count)
total_ms          : Duree totale incluant reseau (Stopwatch)
load_ms           : Temps de chargement modele (load_duration / 1e6)
eval_ms           : Temps d inference pure (eval_duration / 1e6)
prompt_ms         : Temps encode prompt (prompt_eval_duration / 1e6)
ram_avg_mb        : Moyenne RAM Ollama avant/apres run (PrivateMemorySize64)
vram_before       : VRAM utilisee avant run (MB, nvidia-smi)
vram_after        : VRAM utilisee apres run (MB, nvidia-smi)
vram_delta        : vram_after - vram_before
gpu_util_pct      : % utilisation GPU (nvidia-smi)
cpu_util_pct      : % utilisation CPU (Get-Counter, -1 si GPU tier)
temp_c            : Temperature GPU en degres C
done_reason       : stop | length | (vide si erreur)
response_len      : Longueur texte reponse en chars
error             : Message d erreur si echec
num_predict_used  : Valeur num_predict effective utilisee (V7+)
tok_multiplier    : Multiplicateur applique (V7+)
response_snippet  : 500 premiers chars de la reponse
```

### Metriques derivees utiles
```
EFFICACITE_GPU   = tok_s / vram_after    (tokens/s par MB VRAM)
EFFICACITE_RAM   = tok_s / ram_avg_mb    (tokens/s par MB RAM)
TAUX_SUCCES      = runs OK / total runs  (0 a 1)
STABILITE        = ecart-type tok_s sur 3 runs
COMPLETUDE       = moyenne response_len / max response_len observee
```

---

## 9. ARCHITECTURE CIBLE (application benchmark universelle)

### Structure de fichiers
```
benchmark/
  EXPERIENCE.md            <- CE FICHIER (source de verite)
  config/
    models.json            <- Liste des modeles + metadata famille/tier
    prompts.json           <- Bibliotheque de prompts par domaine
    hardware_profiles.json <- Profils machine (seuils RAM/VRAM adaptatifs)
  results/
    sessions/              <- Une session = un lancement complet
      YYYYMMDD_HHMM/
        progress.json      <- Reprise granulaire
        incremental.csv    <- Export apres chaque run
        final.csv          <- Export fin de session
        errors.json        <- Erreurs categorisees
        responses/         <- Reponses completes par modele/prompt/run
    history.json           <- Agregation de toutes les sessions
  scripts/
    run_benchmark.ps1      <- Runner PowerShell (actuel)
    run_benchmark.py       <- Runner Python (futur)
    analyze_results.py     <- Analyse et comparaison
    detect_anomalies.py    <- Detection automatique anomalies
```

### models.json (schema cible)
```json
{
  "models": [
    {
      "name": "qwen2.5-coder:3b",
      "family": "qwen2",
      "tier": "GPU",
      "params_b": 3.1,
      "quant": "Q4_K_M",
      "is_reasoning": false,
      "tok_multiplier": 1,
      "timeout_override": null,
      "vram_observed_mb": 2259,
      "ram_observed_mb": 5220,
      "enabled": true,
      "notes": "Modele de reference GPU. Stable, rapide, reponses completes."
    },
    {
      "name": "gemma4:e4b",
      "family": "gemma4",
      "tier": "GPU",
      "params_b": 8.0,
      "quant": "Q4_K_M",
      "is_reasoning": false,
      "tok_multiplier": 4,
      "timeout_override": null,
      "vram_observed_mb": 2994,
      "ram_observed_mb": 14451,
      "enabled": false,
      "skip_reason": "OOM systeme (14 GB RAM Ollama). Necessite >= 24 GB RAM totale.",
      "notes": "DESACTIVE. Crash V4 documente. Reactiver uniquement sur machine >= 32 GB RAM."
    }
  ]
}
```

### hardware_profiles.json (schema cible)
```json
{
  "profiles": [
    {
      "name": "mobile_4gb_vram",
      "description": "GPU mobile 4 GB VRAM (Quadro M2000M, GTX 1650...)",
      "vram_total_mb": 4096,
      "ram_total_mb": 32768,
      "ram_free_min_mb": 3000,
      "ollama_ram_max_mb": 13000,
      "gpu_temp_warn_c": 85,
      "timeout_gpu_s": 600,
      "timeout_cpu_s": 3600,
      "timeout_reasoning_heavy_s": 7200
    }
  ]
}
```

---

## 10. LECONS APPRISES (retrospective)

### Ce qui fonctionne bien
1. **Reprise granulaire par run** : Indispensable. Le crash OOM en milieu de
   session aurait ete catastrophique sans ca.
2. **Export CSV incremental apres chaque run** : Aucune perte de donnee.
3. **Warmup avant inference** : Permet de detecter les modeles non chargeables
   et de mesurer le temps de chargement separement.
4. **keep_alive=0 entre modeles** : Libere la VRAM proprement.
5. **3 runs par prompt** : Permet de detecter l'instabilite (run 1 vide, runs 2-3 OK).

### Ce qui a cause des problemes
1. **Aucun garde-fou RAM** : OOM systeme = crash Windows brutal sans log.
2. **num_predict fixe par prompt** : Ne tient pas compte des thinking blocks.
3. **Timeout unique de 600s** : Insuffisant pour phi4-mini sur coding_lcca.
4. **Reprise au niveau modele** : Trop grossier, perd un modele entier sur crash.
5. **RAM Ollama non surveillee** : Ollama accumule de la RAM entre les modeles.

### Checklist pre-lancement (V7+)
```
[ ] RAM systeme libre > RAM_FREE_MIN_MB
[ ] Ollama demarre proprement (Test-NetConnection :11434)
[ ] Tous les modeles pull localement (Test-ModelExists)
[ ] nvidia-smi accessible
[ ] Dossier results/ existant et accessible en ecriture
[ ] Fichier progress.json existant ? -> mode reprise, verifier CSV incremental
```

---

## 11. TODO V8+

```
TODO-001 : Analyse qualitative automatique des reponses
           Detecter presence de code (ast.parse), docstring, completude
           Score 0-10 par reponse, pas seulement la longueur

TODO-002 : Detection automatique famille/thinking block
           Tester avec 100 tokens : si resp_len=0 -> thinking block detecte
           Ajuster tokMult automatiquement sans configuration manuelle

TODO-003 : Interface web de visualisation des resultats
           Dashboard React : comparateur modeles, graphes tok/s par prompt
           Historique inter-sessions, regression automatique

TODO-004 : Support runtime alternatifs
           llama.cpp direct, vllm, lmstudio API
           Abstraction : RuntimeAdapter avec interface commune

TODO-005 : Prompt library etendue
           Prompts multilingues (FR/EN/AR)
           Prompts par domaine : math, science, creative, roleplay
           Benchmark LCCA specifique (instruction-following score)

TODO-006 : Alertes et notifications
           Email/Telegram en fin de session
           Alerte si tok/s chute > 20% par rapport session precedente

TODO-007 : Support multi-GPU
           Detection automatique des GPU disponibles
           Assignation modele -> GPU selon VRAM disponible

TODO-008 : Gestion thermique proactive
           Pause si temp GPU > 80C pendant 5 min consecutives
           Resume automatique apres refroidissement
```
