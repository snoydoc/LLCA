# Agent Reviewer Benchmark — Spec complète
# Objectif : sélectionner le meilleur modèle DeepSeek pour ReviewerAgent sur Lenovo P50
# Date de rédaction : 2026-04-22
# Auteur : LCCA session V9-08

---

## 1. CONTEXTE ET MOTIVATION

### 1.1 Situation actuelle
Le `ReviewerAgent` (V9-08) dispose d'un `llm_generator` optionnel qui appelle
`LLMGenerator.generate_text(system, user) → str` via Ollama.
Actuellement, si Ollama est disponible, il hérite du modèle global :
**`qwen2.5-coder:3b`** (configuré dans `config.OLLAMA_MODEL`).

### 1.2 Problème
Le `CoderAgent` et le `ReviewerAgent` utilisent le **même modèle**.
Cela crée un biais cognitif : le Reviewer tend à valider ce que le Coder a produit
plutôt que de le critiquer objectivement.

Architecture cible : **spécialisation par rôle**
- `CoderAgent`    → `qwen2.5-coder:3b`   (génération rapide, spécialisé code)
- `ReviewerAgent` → `deepseek-r1:1.5b`   (raisonnement, critique, détection d'issues)

### 1.3 Contraintes hardware (Lenovo P50 — invariantes)
```
CPU  : Intel Xeon E3-1505M v5 (4c/8t, 3.0 GHz)
RAM  : 16 Go DDR4
GPU  : NVIDIA Quadro M2000M — 4 Go VRAM
OS   : Windows 10 Pro
```
**Règle absolue** : le modèle Reviewer doit tenir en VRAM résiduelle après chargement
du modèle Coder. Budget VRAM Reviewer ≤ **2.0 Go** (4 Go total − 2.0 Go Coder).

---

## 2. MODÈLES CANDIDATS

Les candidats sont sélectionnés parmi les variantes DeepSeek disponibles sur Ollama.
Tous doivent être testés en mode **GPU full** (CUDA_VISIBLE_DEVICES=0).

| ID | Modèle Ollama | Taille disque | VRAM estimée | Statut candidat |
|----|---------------|---------------|--------------|-----------------|
| M1 | `deepseek-r1:1.5b` | ~1.1 Go | ~1.0 Go | ✅ Prioritaire |
| M2 | `deepseek-coder:1.3b` | ~0.8 Go | ~0.8 Go | ✅ Alternatif |
| M3 | `deepseek-r1:7b` | ~4.7 Go | ~4.4 Go | ❌ Exclure (dépasse VRAM) |
| M4 | `deepseek-coder:6.7b` | ~3.9 Go | ~3.6 Go | ❌ Exclure (dépasse budget) |
| M5 | `deepseek-r1:1.5b-qwen-distill-q4_K_M` | ~1.1 Go | ~1.0 Go | ✅ Variante quantifiée M1 |

> Note : les tailles VRAM sont des estimations. Le benchmark mesurera la valeur réelle
> via `nvidia-smi` (champ `vram_used_mb` dans `MetricsSummary`).

---

## 3. ARCHITECTURE DU BENCHMARK

### 3.1 Structure des fichiers à créer
```
D:\LLMCodeAgent\
└── ReviewerBenchmark\
    ├── setup.ps1                  → Installation venv + dépendances
    ├── run_reviewer_benchmark.ps1 → Lanceur principal (Pull + Test)
    ├── src\
    │   ├── __init__.py
    │   ├── benchmark.py           → Moteur (fork de CPUVsGPU\src\benchmark.py)
    │   ├── metrics.py             → COPIE EXACTE de CPUVsGPU\src\metrics.py
    │   ├── prompts.py             → Prompts REVIEWER spécifiques (voir §4)
    │   ├── report.py              → Rapport HTML (fork de CPUVsGPU\src\report.py)
    │   └── main.py                → Point d'entrée
    └── results\                   → JSON + HTML générés automatiquement
```

### 3.2 Héritage depuis CPUVsGPU
Les modules suivants sont **fork** (copie + adaptation minimale) :
- `metrics.py` → copie exacte (pas de modification)
- `benchmark.py` → fork : remplacer `PROMPTS` par les prompts Reviewer + adapter
  la fonction `run_inference()` au format REVIEWER (system prompt + user prompt)
- `report.py` → fork : titre + colonnes adaptés au contexte Reviewer

---

## 4. PROMPTS DE TEST

### 4.1 Spécificité des prompts Reviewer
Le ReviewerAgent reçoit du code Python et retourne un JSON :
```json
{
  "quality_score": 72,
  "issues": ["Pas de type hints", "Division par zéro possible"],
  "suggestions": ["Utiliser pathlib", "Ajouter guard clause"]
}
```
Les prompts de benchmark doivent **imiter ce flux réel** :
- System prompt = `_REVIEWER_SYSTEM` (extrait de `reviewer_agent.py`)
- User prompt = `_REVIEWER_USER_TMPL` rempli avec du code Python réaliste
- Critère de qualité = JSON parseable + champs attendus présents

### 4.2 Liste des 6 prompts (à implémenter dans `prompts.py`)

```python
REVIEWER_SYSTEM = (
    "You are a senior Python code reviewer. "
    "Analyze the code provided and return a short JSON object with keys: "
    '"quality_score" (int 0-100), "issues" (list of strings), "suggestions" (list of strings). '
    "Return ONLY valid JSON, no explanation."
)

REVIEWER_PROMPTS = [
    {
        "id": "review_simple",
        "label": "Review — Code simple",
        "description": "Code fonctionnel sans issues évidentes",
        "code": """
def add(a: int, b: int) -> int:
    \"\"\"Additionne deux entiers.\"\"\"
    return a + b
""",
        "intent": "additionner deux entiers",
        "domain": "global",
        # Résultat attendu : quality_score élevé (>70), issues=[], suggestions minimes
    },
    {
        "id": "review_no_hints",
        "label": "Review — Sans type hints",
        "description": "Code fonctionnel mais sans annotations de types",
        "code": """
def process_data(items, threshold):
    result = []
    for item in items:
        if item > threshold:
            result.append(item * 2)
    return result
""",
        "intent": "filtrer et doubler des valeurs",
        "domain": "data",
        # Résultat attendu : issues contient mention type hints
    },
    {
        "id": "review_division_zero",
        "label": "Review — Division par zéro",
        "description": "Bug latent : division sans guard clause",
        "code": """
def average(numbers: list) -> float:
    total = sum(numbers)
    return total / len(numbers)
""",
        "intent": "calculer la moyenne d'une liste",
        "domain": "global",
        # Résultat attendu : issues contient mention division par zéro / liste vide
    },
    {
        "id": "review_print_abuse",
        "label": "Review — Print en production",
        "description": "Code avec print() hors bloc main",
        "code": """
import os
from pathlib import Path

def load_config(path: str) -> dict:
    print(f"Loading config from {path}")
    if not os.path.exists(path):
        print("File not found!")
        return {}
    with open(path) as f:
        import json
        data = json.load(f)
    print(f"Loaded {len(data)} keys")
    return data
""",
        "intent": "charger un fichier de configuration JSON",
        "domain": "config",
        # Résultat attendu : issues contient mention print() / logging
    },
    {
        "id": "review_complex_class",
        "label": "Review — Classe complexe",
        "description": "Classe avec plusieurs responsabilités",
        "code": """
class DataManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.data = {}
        self.cache = {}
        self.errors = []

    def load(self):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("SELECT * FROM items").fetchall()
        for row in rows:
            self.data[row[0]] = row[1]
        conn.close()

    def process(self):
        for k, v in self.data.items():
            try:
                self.cache[k] = v.strip().lower()
            except:
                self.errors.append(k)

    def save_csv(self, path):
        with open(path, "w") as f:
            for k, v in self.cache.items():
                f.write(f"{k},{v}\\n")
""",
        "intent": "gérer des données depuis SQLite vers CSV",
        "domain": "data",
        # Résultat attendu : issues multiples (bare except, connexion non fermée via context, etc.)
    },
    {
        "id": "review_security",
        "label": "Review — Faille sécurité",
        "description": "Code avec vulnérabilité injection SQL",
        "code": """
import sqlite3

def get_user(db_path: str, username: str) -> dict:
    conn = sqlite3.connect(db_path)
    query = f"SELECT * FROM users WHERE name = '{username}'"
    row = conn.execute(query).fetchone()
    conn.close()
    if row:
        return {"id": row[0], "name": row[1], "email": row[2]}
    return {}
""",
        "intent": "récupérer un utilisateur par nom",
        "domain": "security",
        # Résultat attendu : issues contient injection SQL, quality_score bas (<40)
    },
]

def get_quick_prompts() -> list:
    """2 prompts pour test rapide : simple + critique."""
    return [REVIEWER_PROMPTS[0], REVIEWER_PROMPTS[2]]  # review_simple + division_zero
```

### 4.3 Format du prompt envoyé à Ollama
Le benchmark doit utiliser **l'endpoint `/api/chat`** (pas `/api/generate`) pour passer
le system prompt séparément :

```python
payload = {
    "model": model,
    "messages": [
        {"role": "system", "content": REVIEWER_SYSTEM},
        {"role": "user",   "content": USER_TMPL.format(
            domain=prompt_info["domain"],
            intent=prompt_info["intent"],
            code=prompt_info["code"],
        )}
    ],
    "stream": False,
    "options": {
        "num_predict": 256,   # Réponse JSON courte
        "temperature": 0.0,   # Déterminisme maximal pour reproductibilité
    }
}
```

> **Différence clé vs CPUVsGPU** : on utilise `/api/chat` (multi-turn) au lieu de
> `/api/generate` (single-turn) car le ReviewerAgent utilise `generate_text()` qui
> passe un system prompt distinct.

---

## 5. MÉTRIQUES DE MESURE

### 5.1 Métriques de performance (héritées de CPUVsGPU)
Identiques à `CPUVsGPU\src\benchmark.py` :

| Métrique | Source | Description |
|----------|--------|-------------|
| `tok_per_sec` | `eval_count / eval_duration` | Vitesse de génération (principal) |
| `ttft_s` | `load_duration / 1e9` | Time To First Token |
| `total_s` | `total_duration / 1e9` | Durée totale de la requête |
| `prompt_tok_s` | `prompt_eval_count / prompt_eval_duration` | Vitesse d'évaluation du prompt |
| `vram_used_mb` | `nvidia-smi` | VRAM consommée pendant l'inférence |
| `cpu_avg` | `psutil` | CPU% moyen pendant l'inférence |

### 5.2 Métriques de qualité (NOUVELLES — spécifiques Reviewer)
Ces métriques mesurent la **pertinence** de la réponse, pas juste la vitesse :

| Métrique | Calcul | Description |
|----------|--------|-------------|
| `json_valid` | `bool` | La réponse est un JSON parseable (sans fences) |
| `has_quality_score` | `bool` | Le JSON contient `quality_score` (int 0-100) |
| `has_issues` | `bool` | Le JSON contient `issues` (list) |
| `has_suggestions` | `bool` | Le JSON contient `suggestions` (list) |
| `quality_score_value` | `int \| -1` | Valeur du quality_score retournée |
| `issues_count` | `int` | Nombre d'issues détectées |
| `expected_issues_found` | `bool` | ≥1 issue attendue détectée (voir §4.2) |
| `schema_score` | `int 0-4` | Somme des 4 booléens ci-dessus |

### 5.3 Score composite
Pour classer les modèles, calculer un **score composite** :

```
composite_score = (tok_per_sec / 10.0) * 0.4      # vitesse (40%)
               + (schema_score / 4.0) * 0.4        # conformité JSON (40%)
               + (expected_issues_found * 1.0) * 0.2  # pertinence (20%)
```

Plage : 0.0 → 1.0. Un modèle lent mais précis peut battre un modèle rapide mais qui
retourne du texte libre au lieu de JSON.

---

## 6. IMPLÉMENTATION — `benchmark.py` (différences vs CPUVsGPU)

### 6.1 `run_inference(model, prompt_info)` — signature modifiée
```python
def run_inference(model: str, prompt_info: dict) -> dict:
    """
    Lance une inférence REVIEWER et retourne métriques perf + qualité.
    Utilise /api/chat (system + user séparés).
    """
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": REVIEWER_SYSTEM},
            {"role": "user",   "content": USER_TMPL.format(
                domain=prompt_info["domain"],
                intent=prompt_info["intent"],
                code=prompt_info["code"].strip(),
            )},
        ],
        "stream": False,
        "options": {"num_predict": 256, "temperature": 0.0},
    }).encode()

    # ... (même structure try/except que CPUVsGPU)

    # Extraction réponse chat (différente de /api/generate)
    raw_text = data.get("message", {}).get("content", "")

    # Évaluation qualité
    quality = _evaluate_quality(raw_text, prompt_info)

    return {
        # Métriques perf (identiques CPUVsGPU)
        "tok_per_sec" : round(tok_per_sec, 2),
        "ttft_s"      : round(load_duration, 3),
        "total_s"     : round(total_dur, 3),
        "tokens_out"  : eval_count,
        # Métriques qualité (nouvelles)
        "json_valid"           : quality["json_valid"],
        "schema_score"         : quality["schema_score"],
        "quality_score_value"  : quality["quality_score_value"],
        "issues_count"         : quality["issues_count"],
        "expected_issues_found": quality["expected_issues_found"],
        "raw_response"         : raw_text[:300],
        "error"                : None,
    }
```

### 6.2 `_evaluate_quality(raw_text, prompt_info)` — fonction à créer
```python
import json as _json
import re as _re

def _evaluate_quality(raw_text: str, prompt_info: dict) -> dict:
    """
    Évalue la conformité de la réponse LLM au schéma Reviewer.
    Nettoie les fences markdown avant parse.
    """
    # Nettoyage fences markdown (même logique que reviewer_agent.py)
    clean = raw_text.strip()
    if clean.startswith("```"):
        lines = clean.splitlines()
        clean = "\n".join(
            lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        )

    json_valid = False
    parsed = {}
    try:
        parsed = _json.loads(clean)
        json_valid = True
    except Exception:
        pass

    has_quality_score = isinstance(parsed.get("quality_score"), int)
    has_issues        = isinstance(parsed.get("issues"), list)
    has_suggestions   = isinstance(parsed.get("suggestions"), list)
    schema_score      = sum([json_valid, has_quality_score, has_issues, has_suggestions])

    quality_score_value = int(parsed.get("quality_score", -1)) if has_quality_score else -1
    issues_count        = len(parsed.get("issues", [])) if has_issues else 0

    # Vérification issue attendue (heuristique — mots-clés)
    expected_kw = prompt_info.get("expected_keywords", [])
    all_text = " ".join(parsed.get("issues", []) + parsed.get("suggestions", [])).lower()
    expected_issues_found = any(kw.lower() in all_text for kw in expected_kw) if expected_kw else True

    return {
        "json_valid"           : json_valid,
        "schema_score"         : schema_score,
        "quality_score_value"  : quality_score_value,
        "issues_count"         : issues_count,
        "expected_issues_found": expected_issues_found,
    }
```

> **Note** : ajouter le champ `"expected_keywords"` dans chaque prompt de `prompts.py` :
> ```python
> # Exemple pour review_division_zero :
> "expected_keywords": ["zero", "empty", "vide", "division", "len"],
> # Exemple pour review_print_abuse :
> "expected_keywords": ["print", "log", "logging"],
> # Exemple pour review_security :
> "expected_keywords": ["sql", "injection", "parameterized", "parametr"],
> ```

---

## 7. SCRIPT POWERSHELL `run_reviewer_benchmark.ps1`

```powershell
# run_reviewer_benchmark.ps1 — Benchmark DeepSeek pour ReviewerAgent
# Prerequis : Ollama deja lance en mode GPU via .\start-ollama.ps1
# Usage :
#   .\run_reviewer_benchmark.ps1           -> tous candidats, 6 prompts, 3 runs
#   .\run_reviewer_benchmark.ps1 -Quick    -> M1+M2, 2 prompts, 1 run (~5 min)
#   .\run_reviewer_benchmark.ps1 -Model M1 -> modele spécifique uniquement

param(
    [switch]$Quick,
    [string]$Model = "all"   # "all" | "M1" | "M2"
)

$python     = "$PSScriptRoot\ReviewerBenchmark\.venv\Scripts\python.exe"
$srcDir     = "$PSScriptRoot\ReviewerBenchmark"
$resultsDir = "$PSScriptRoot\ReviewerBenchmark\results"

# Modèles candidats (M3/M4 exclus — VRAM insuffisante)
$candidates = @{
    "M1" = "deepseek-r1:1.5b"
    "M2" = "deepseek-coder:1.3b"
}

# Vérification venv
if (-not (Test-Path $python)) {
    Write-Host "[ERREUR] Venv non trouve. Lance : cd ReviewerBenchmark && .\setup.ps1" -ForegroundColor Red
    exit 1
}

# Vérification Ollama
try {
    Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 5 -ErrorAction Stop | Out-Null
    Write-Host "[OK] Ollama repond." -ForegroundColor Green
} catch {
    Write-Host "[ERREUR] Ollama ne repond pas. Lance .\start-ollama.ps1" -ForegroundColor Red
    exit 1
}

# Pull automatique des modèles manquants
foreach ($key in $candidates.Keys) {
    $modelName = $candidates[$key]
    Write-Host "[PULL] Verification $modelName..." -ForegroundColor Cyan
    & ollama pull $modelName
}

# Lancement benchmarks
$results = @{}
$modelsToTest = if ($Model -eq "all") { $candidates.Keys } else { @($Model) }

foreach ($key in $modelsToTest) {
    $modelName = $candidates[$key]
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  $key : $modelName" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan

    Push-Location $srcDir
    if ($Quick) {
        $output = & $python -m src.main --model $modelName --quick 2>&1
    } else {
        $output = & $python -m src.main --model $modelName 2>&1
    }
    Pop-Location

    Write-Host ($output -join "`n") -ForegroundColor Gray

    $avgLine = $output | Select-String "Moyenne globale"
    $results[$key] = if ($avgLine) { ($avgLine.Line -replace ".*:\s*", "").Trim() } else { "N/A" }
}

# Rapport final
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  RÉSULTATS BENCHMARK REVIEWER" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
foreach ($key in $modelsToTest) {
    $modelName = $candidates[$key]
    Write-Host ("  {0} ({1,-30}) : {2}" -f $key, $modelName, $results[$key]) -ForegroundColor White
}
Write-Host ""
Write-Host "  Rappel référence (CoderAgent) :" -ForegroundColor Gray
Write-Host "    qwen2.5-coder:3b = 10.87 tok/s (full VRAM)" -ForegroundColor Gray
Write-Host ""
Write-Host "  -> Mettre a jour config.py REVIEWER_MODEL avec le gagnant !" -ForegroundColor Magenta
Write-Host "  -> Mettre a jour 002-tech-context.md avec les résultats." -ForegroundColor Magenta
```

---

## 8. SPRINT V9-09 — IMPLÉMENTATION DU MODÈLE GAGNANT

Ce sprint sera exécuté **après** le benchmark, une fois le modèle gagnant identifié.

### 8.1 Fichiers à modifier

**`config.py`** — ajouter dans la section LLM :
```python
# ReviewerAgent — modèle dédié (raisonnement/critique, distinct du Coder)
REVIEWER_MODEL: str = "deepseek-r1:1.5b"  # À ajuster selon résultat benchmark
```

**`core/agents/reviewer_agent.py`** — modifier `create()` :
```python
@classmethod
def create(cls, bus, mcp_caller=None, llm_generator=None) -> "ReviewerAgent":
    if llm_generator is None:
        try:
            import config
            from core.llm_generator import LLMGenerator
            import ollama as _ollama
            if isinstance(_ollama.model, str):
                # Modèle dédié Reviewer (différent du Coder)
                reviewer_model = getattr(config, "REVIEWER_MODEL", config.OLLAMA_MODEL)
                llm_generator = LLMGenerator(model=reviewer_model)
        except Exception:
            pass
    # ... reste inchangé
```

> **Prérequis** : vérifier que `LLMGenerator.__init__` accepte un paramètre `model`
> (surcharge du `config.OLLAMA_MODEL`). Si non, c'est un sous-sprint à ajouter.

**`tests/test_v9_09.py`** — 10 tests minimaux :
- `REVIEWER_MODEL` présent dans `config` (str non vide)
- `REVIEWER_MODEL != OLLAMA_MODEL` (modèles distincts)
- `create()` instancie un LLMGenerator avec le bon modèle
- `create()` sans Ollama → `llm_generator=None` (rétrocompat)
- `_analyze_with_llm()` appelle `generate_text` avec le bon system prompt
- Tests existants V9-08 non régressés

### 8.2 Mise à jour skills
- `003-project-context.md` : `reviewer_agent.py` → mention REVIEWER_MODEL
- `004-sprint-context.md` : V9-09 TERMINÉ
- `002-tech-context.md` : résultats benchmark + modèle retenu

---

## 9. RAPPORT HTML ATTENDU

Le rapport généré dans `results/rapport_YYYYMMDD_HHMMSS.html` doit afficher :

### Section 1 — Tableau comparatif modèles
| Modèle | tok/s moy | TTFT moy | VRAM (MB) | Schema Score | Issues détectées | Composite |
|--------|-----------|----------|-----------|--------------|------------------|-----------|
| deepseek-r1:1.5b | X.XX | X.XXX | XXX | 4/4 | X/6 | 0.XX |
| deepseek-coder:1.3b | X.XX | X.XXX | XXX | 4/4 | X/6 | 0.XX |

### Section 2 — Détail par prompt
Pour chaque prompt et chaque modèle :
- Vitesse tok/s
- JSON valide (✅/❌)
- quality_score retourné
- Issues attendues trouvées (✅/❌)
- Réponse brute tronquée (200 chars)

### Section 3 — Recommandation automatique
```
🏆 Modèle recommandé : deepseek-r1:1.5b
   Composite score   : 0.82
   Décision          : REVIEWER_MODEL = "deepseek-r1:1.5b"
```

---

## 10. CRITÈRES DE DÉCISION FINALE

### 10.1 Modèle retenu si
1. `schema_score = 4/4` sur ≥ 4/6 prompts (JSON toujours valide)
2. `tok_per_sec ≥ 5.0` (latence acceptable dans le pipeline KarpathyLoop)
3. `vram_used_mb ≤ 2000` (reste dans le budget VRAM)
4. `expected_issues_found = True` sur les prompts critiques (M-4, M-5, M-6)

### 10.2 Fallback
Si aucun modèle ne satisfait les 4 critères → conserver `llm_generator=None`
dans `ReviewerAgent` et documenter dans `005-debt-tracker.md` :
```
DETTE INFO-XXX : ReviewerAgent sans LLM dédié — qualité review purement syntaxique.
```

### 10.3 Tie-break
Si M1 et M2 sont équivalents en composite → préférer **M1 (deepseek-r1:1.5b)**
car le suffixe R1 est optimisé pour le raisonnement critique (chain-of-thought interne).

---

## 11. CHECKLIST D'EXÉCUTION (pour la prochaine session)

```
[ ] Lire les skills 001 → ClaudeDesonneSkill avant toute action
[ ] Vérifier que CPUVsGPU\.venv est fonctionnel (python --version)
[ ] Créer D:\LLMCodeAgent\ReviewerBenchmark\ (structure §3.1)
[ ] Copier metrics.py depuis CPUVsGPU\src\metrics.py (identique)
[ ] Créer prompts.py avec REVIEWER_PROMPTS (6 prompts §4.2 + expected_keywords)
[ ] Créer benchmark.py (fork CPUVsGPU + /api/chat + _evaluate_quality)
[ ] Créer report.py (fork CPUVsGPU + colonnes qualité)
[ ] Créer main.py + setup.ps1 + run_reviewer_benchmark.ps1
[ ] Lancer .\start-ollama.ps1 (mode GPU)
[ ] Lancer .\run_reviewer_benchmark.ps1 -Quick (vérification rapide ~5 min)
[ ] Lancer .\run_reviewer_benchmark.ps1 (benchmark complet ~20 min)
[ ] Lire le rapport HTML results/
[ ] Implémenter sprint V9-09 si un gagnant clair émerge
[ ] Mettre à jour 002, 003, 004 avec résultats et modèle retenu
```

---

## 12. NOTES TECHNIQUES

### 12.1 Isolation VRAM pendant le benchmark
Pour mesurer la VRAM réelle consommée par le modèle Reviewer **seul** :
- Ne pas charger `qwen2.5-coder:3b` en même temps
- Vérifier avec `nvidia-smi` avant le benchmark que VRAM disponible ≥ 3.5 Go
- La mesure `vram_used_mb` dans MetricsSummary = VRAM totale Ollama (pas seulement le modèle)

### 12.2 Reproductibilité
- `temperature: 0.0` dans tous les appels (déterminisme maximal)
- 3 runs par prompt, prendre la **médiane** (pas la moyenne) pour éviter les outliers
- Warmup obligatoire avant le premier prompt (chargement modèle en VRAM)

### 12.3 Contrainte pipeline LCCA
Dans le pipeline KarpathyLoop, le Reviewer est appelé **de façon synchrone**.
Si `generate_text()` prend > 30s → timeout KarpathyLoop possible.
**Seuil critique** : `total_s ≤ 20s` pour les prompts de taille réelle (≤ 1500 chars de code).

### 12.4 Compatibilité `LLMGenerator`
Avant le sprint V9-09, vérifier dans `core/llm_generator.py` :
```python
class LLMGenerator:
    def __init__(self, model: Optional[str] = None): ...
    # Si model=None → utilise config.OLLAMA_MODEL
    # Si model="deepseek-r1:1.5b" → override
```
Si le constructeur n'accepte pas `model` en paramètre → ajouter ce paramètre
comme **première micro-tâche** du sprint V9-09 (avant le reste).
```
