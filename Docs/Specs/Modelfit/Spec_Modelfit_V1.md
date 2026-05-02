# Modelfit -- Spec V1
# Outil open source MIT : quel modele Ollama pour votre machine ?
# Repo independant de LLAC, utile pour toute la communaute Ollama
# Date : 2026-04-26
# ASCII pur

## VISION

Le probleme : les benchmarks publics mesurent la qualite des reponses
sur des serveurs A100. Ils ne disent rien sur ce qui va tourner a 40 tok/s
sur votre laptop avec 8 GB RAM et une iGPU Intel.

La solution Modelfit : mesurer sur VOTRE machine, avec VOS contraintes
reelles, et recommander le meilleur modele pour chaque usage.

Tagline : "Stop guessing. Start measuring."

---

## DEUX MODES

### MODE NOVICE (par defaut)
Public : premier contact avec Ollama, pas de connaissances LLM

Flux :
  1. Detection automatique du materiel (GPU, VRAM, RAM, CPU, OS)
  2. Recherche des modeles recents sur ollama.com/library (API officielle)
  3. Filtrage : seuls les modeles compatibles avec le materiel sont proposes
  4. Pre-test rapide (~2 min) : 1 prompt x 1 run sur 3-5 modeles candidats
  5. Rapport : "Pour votre machine, on recommande X pour le quotidien, Y overnight"
  6. Installation automatique avec confirmation explicite (ollama pull)

Principe : le systeme decide, l utilisateur valide.

### MODE EXPERT
Public : developpeurs, chercheurs, power users

Flux :
  1. Detection materiel (meme module detect/)
  2. Catalogue complet avec filtres (taille, famille, quantization)
  3. L utilisateur selectionne ses modeles (inclure / exclure)
  4. Configuration du benchmark :
       - Nombre de runs (1 a 10)
       - Categories de prompts choisies
       - Timeout par modele
  5. Benchmark complet
  6. Rapport detaille JSON + HTML

Principe : l utilisateur pilote, Modelfit mesure.

---

## CATEGORIES DE PROMPTS (6 categories, 3 prompts chacune = 18 total)

### code
  - Ecrire une fonction Python avec docstring et exemple
  - Implementer un algorithme de tri avec tests unitaires
  - Creer une classe avec heritage et proprietes

### debug
  - Corriger un ZeroDivisionError avec gestion du cas vide
  - Analyser un stack trace Python et proposer un correctif
  - Identifier une fuite memoire dans du code asyncio

### reasoning
  - Probleme logique multi-etapes (suite de Fibonacci optimisee)
  - Comparaison de deux architectures techniques avec criteres
  - Prise de decision sous contraintes (budget, temps, complexite)

### chat
  - Expliquer un concept technique a un debutant
  - Reformuler une explication complexe en 3 points cles
  - Repondre a une question ambigue en demandant des clarifications

### summarization
  - Resume d un document technique de 500 mots en 5 phrases
  - Extraction des points d action d une longue discussion
  - Compression d un README en une description de 2 lignes

### multilingual
  - Traduction FR->EN d un texte technique avec precision vocabulaire
  - Reponse en FR et EN sur le meme sujet (comparaison coherence)
  - Correction grammaticale d un texte en anglais non-natif

---

## ARCHITECTURE

```
modelfit/
|-- cli.py                   Point d entree unique
|                            modelfit novice
|                            modelfit expert
|                            modelfit single --model qwen3:4b
|                            modelfit report --last
|                            modelfit contribute
|
|-- detect/
|   |-- __init__.py
|   |-- hardware.py          GPU (nvidia-smi + WMI + /proc), VRAM, RAM, CPU, OS
|   |-- ollama_check.py      version, variables env, CUDA actif ou non
|   |-- models_catalog.py    fetch ollama.com/library + cache local 24h
|
|-- benchmark/
|   |-- __init__.py
|   |-- runner.py            Execute prompts, mesure tok/s + TTFT + RAM + VRAM
|   |-- prompts.py           18 prompts (6 categories x 3)
|   |-- reporter.py          Rapport JSON + HTML autonome
|
|-- recommender/
|   |-- __init__.py
|   |-- profiles.py          Regles matching materiel -> modele(s) + scoring
|   |-- installer.py         ollama pull avec barre de progression
|
|-- results/
|   |-- community/           Profils contributeurs (versiones git)
|   |   |-- quadro-m2000m-24gb-win11.json    profil seed #001
|   |-- local/               Resultats locaux (gitignore)
|
|-- tests/
|   |-- test_detect.py
|   |-- test_benchmark.py
|   |-- test_recommender.py
|   |-- test_catalog.py
|
|-- run.ps1                  Lancement Windows (une commande)
|-- run.sh                   Lancement Linux/Mac
|-- requirements.txt         rich (optionnel), stdlib uniquement pour le coeur
|-- LICENSE                  MIT
|-- README.md
```

---

## TIERS MATERIELS

TIER_GPU_HIGH  : VRAM libre >= 6 GB          -> modeles 7B+ full GPU
TIER_GPU_MID   : VRAM libre 3-6 GB           -> modeles 3-4B full GPU, 7B hybride
TIER_GPU_LOW   : VRAM libre 1-3 GB           -> modeles 2-3B uniquement
TIER_CPU_HIGH  : RAM >= 32 GB, pas GPU       -> modeles 14B+ CPU
TIER_CPU_MID   : RAM 16-32 GB, pas GPU       -> modeles 7-8B CPU
TIER_CPU_LOW   : RAM < 16 GB, pas GPU        -> modeles 3-4B CPU uniquement

---

## SCORING POST-BENCHMARK

Score final = 0.6 * tok_s_norm + 0.2 * ttft_norm + 0.2 * stabilite
  tok_s_norm  = tok/s modele / meilleur tok/s session
  ttft_norm   = 1 - (TTFT modele / pire TTFT session)
  stabilite   = 1 - (ecart_type tok/s / moyenne tok/s)

Trois recommandations produites :
  FAST    : meilleur score global               -> usage quotidien, chat
  QUALITY : meilleur score parmi modeles >8 GB  -> taches complexes overnight
  CODING  : meilleur score sur prompts "code"   -> developpement

---

## FORMAT PROFIL COMMUNAUTAIRE

{
  "profile_id": "quadro-m2000m-24gb-win11-001",
  "date": "2026-04-26",
  "hardware": {
    "gpu": "Nvidia Quadro M2000M",
    "vram_total_mb": 4096,
    "vram_free_mb": 782,
    "ram_total_gb": 24,
    "cpu": "Intel Xeon E3-1505M v5",
    "os": "Windows 11"
  },
  "ollama": {
    "version": "0.21.2",
    "cuda_active": true,
    "num_gpu": 99
  },
  "results": [
    {
      "model": "gemma4:e2b",
      "tok_s_avg": 38.4,
      "ttft_ms_avg": 420,
      "ram_mb_avg": 1240,
      "vram_mb_avg": 1580,
      "prompts_tested": ["code", "debug", "reasoning"],
      "verdict": "FAST"
    }
  ],
  "recommendation": {
    "fast": "gemma4:e2b",
    "quality": "qwen3:30b-a3b",
    "coding": "qwen3-coder:30b-a3b-q4_K_M"
  }
}

---

## FEUILLE DE ROUTE

### V1 -- MVP
[ ] detect/hardware.py        Windows + Linux (Mac best-effort)
[ ] detect/ollama_check.py    version, CUDA, variables env
[ ] detect/models_catalog.py  fetch ollama.com/library + cache 24h
[ ] benchmark/prompts.py      18 prompts, 6 categories
[ ] benchmark/runner.py       execute, mesure, gere crash 500 + restart
[ ] benchmark/reporter.py     JSON + HTML
[ ] recommender/profiles.py   scoring + tiers + 3 recommandations
[ ] recommender/installer.py  ollama pull + progression + confirmation
[ ] cli.py                    modes novice / expert / single / report / contribute
[ ] results/community/        profil seed #001 (resultats GPU de cette nuit)
[ ] run.ps1 + run.sh
[ ] README.md + LICENSE MIT
[ ] tests/ (couverture > 80%)

### V2 -- Communaute
[ ] modelfit contribute -> PR automatique GitHub
[ ] Matching sans benchmark si profil materiel deja connu dans community/
[ ] Site statique genere depuis community/
[ ] Badge README "Tested on Modelfit"

### V3 -- Avance
[ ] Support ROCm (AMD GPU)
[ ] Support Apple Metal (M1/M2/M3)
[ ] API HTTP locale (modelfit serve)
[ ] Integration CI/CD

---

## INVARIANTS ABSOLUS

1. Modelfit ne modifie JAMAIS les variables d environnement du systeme
2. Modelfit ne pull JAMAIS un modele sans confirmation explicite (o/N)
3. Modelfit ne fait JAMAIS de requete reseau sans le signaler a l utilisateur
4. Tout resultat est sauvegarde localement avant toute action suivante
5. Un crash d un modele pendant le benchmark n arrete pas les autres
6. Zéro ecriture hors de ~/.modelfit/ et results/local/ (sauf contribution explicite)

---

## DECISIONS TECHNIQUES

Langage    : Python 3.11+ (meme stack que LLAC)
Core       : stdlib uniquement (detect/ + recommender/)
Optionnel  : rich (UI terminal), requests (catalog fetch fallback urllib)
Tests      : pytest, conventions LLAC
Config     : ~/.modelfit/config.json
Logs       : ~/.modelfit/logs/ (rotation 7 jours)
Pas de Docker : l utilisateur a deja Ollama
