# SPEC EvalLoop — EVAL-05 : BenchGenerator + Benchmarks Initiaux
**Version** : 1.0
**Date** : 2026-04-23
**Statut** : DRAFT
**Dépendances** : EVAL-01 (dataclasses + config)

---

## 1. Objectif du sprint

Deux livrables distincts :

1. **`bench_generator.py`** — Génère de nouvelles questions via LLM (Ollama local)
2. **Benchmarks initiaux** — 6 domaines × 3 paliers × 5 questions = 90 questions minimum

Les benchmarks sont écrits **à la main** pour les paliers 0 et 1 (contrôle qualité humain).
Le générateur est utilisé pour les paliers 2+ et pour l'enrichissement continu.

---

## 2. Fichiers créés

| Fichier | Rôle |
|---|---|
| `EvalLoop/engines/bench_generator.py` | Génération questions via LLM |
| `EvalLoop/benchmarks/python_core/palier_0.json` | 5 questions palier 0 |
| `EvalLoop/benchmarks/python_core/palier_1.json` | 5 questions palier 1 |
| `EvalLoop/benchmarks/python_core/palier_2.json` | 5 questions palier 2 |
| `EvalLoop/benchmarks/architecture/palier_0.json` | 5 questions palier 0 |
| `EvalLoop/benchmarks/architecture/palier_1.json` | 5 questions palier 1 |
| `EvalLoop/benchmarks/debugging/palier_0.json` | 5 questions palier 0 |
| `EvalLoop/benchmarks/debugging/palier_1.json` | 5 questions palier 1 |
| `EvalLoop/benchmarks/algorithms/palier_0.json` | 5 questions palier 0 |
| `EvalLoop/benchmarks/refactoring/palier_0.json` | 5 questions palier 0 |
| `EvalLoop/benchmarks/llca_meta/palier_0.json` | 3 questions palier 0 |

---

## 3. `bench_generator.py`

### Responsabilités
- Générer N nouvelles questions pour un domaine + palier via Ollama
- Valider le format JSON retourné par le LLM
- Écrire / enrichir le fichier `benchmarks/{domain}/palier_{N}.json`
- Éviter les doublons (déduplication par question.lower().strip())

### Interface publique

```python
class BenchGenerator:
    def __init__(self, config: dict, benchmarks_dir: Path):
        ...

    def generate(
        self,
        domain: str,
        palier: int,
        count: int = 5,
    ) -> list[BenchQuestion]:
        """Génère count questions pour le domaine+palier via LLM.
        Déduplication contre les questions existantes du même fichier.
        Retourne les nouvelles questions générées (sans les doublons)."""

    def save(self, questions: list[BenchQuestion], domain: str, palier: int) -> Path:
        """Append les questions dans benchmarks/{domain}/palier_{N}.json.
        Crée le fichier si absent. Retourne le chemin du fichier."""

    def _build_gen_prompt(self, domain: str, palier: int, count: int) -> str:
        """Construit le prompt de génération."""

    def _parse_llm_response(self, raw: str) -> list[dict]:
        """Parse la réponse JSON du LLM. Tolère les erreurs partielles."""

    def _validate_question(self, q: dict) -> bool:
        """Vérifie que la question a tous les champs requis."""

    def _load_existing(self, domain: str, palier: int) -> list[BenchQuestion]:
        """Charge les questions existantes pour déduplication."""
```

### Prompt de génération

```
SYSTEM:
Tu es un expert en évaluation de LLMs spécialisés en développement Python.
Tu génères des questions de benchmark pour évaluer le niveau d'un assistant IA.
Réponds UNIQUEMENT en JSON valide, sans balises Markdown.

USER:
Génère {count} questions de benchmark pour le domaine "{domain_description}" au palier {palier}.

Palier {palier} signifie : {palier_description}

Pour chaque question, retourne ce format JSON exact :
[
  {
    "id": "{prefix}-p{palier}-{seq:03d}",
    "domain": "{domain}",
    "palier": {palier},
    "difficulty": "easy|medium|hard|expert",
    "question": "La question complète en français",
    "expected_concepts": ["concept1", "concept2"],
    "rubric": "Critères d'évaluation : la réponse doit mentionner...",
    "tags": ["tag1", "tag2"]
  }
]

Questions à éviter (déjà présentes) :
{existing_questions_list}
```

Descriptions de paliers :
```python
PALIER_DESCRIPTIONS = {
    0: "Fondations — définitions, vocabulaire, concepts isolés. Exemples : 'Qu'est-ce que X ?', 'Quel est le rôle de Y ?'",
    1: "Compréhension — 'pourquoi', comparaisons simples. Exemples : 'Quelle est la différence entre A et B ?', 'Pourquoi utiliser X plutôt que Y ?'",
    2: "Application — cas d'usage concrets, implémentations simples. Exemples : 'Implémente X', 'Comment utiliser Y pour faire Z ?'",
    3: "Analyse — détecter des problèmes, expliquer des comportements. Exemples : 'Quel problème pose ce code ?', 'Pourquoi ce bug se produit-il ?'",
    4: "Synthèse — concevoir une solution à un problème ouvert. Exemples : 'Conçois une architecture pour...', 'Comment refactoriser ce système ?'",
    5: "Expert — edge cases, performance, compromis architecturaux. Exemples : 'Quel est l'impact sur le GC de...', 'Quels sont les trade-offs de...'",
}
```

### Règles BenchGenerator
- `urllib.request` pour Ollama (même pattern que ProbeEngine)
- `timeout=None` pour Ollama
- Si le LLM retourne un JSON partiellement invalide → parser les questions valides, log warning pour les invalides
- Séquence d'ID : `_next_seq()` = max(ID existants) + 1 pour ce domaine/palier
- `save()` : lecture du fichier existant → merge → écriture (jamais tronquer)
- Fichier JSON indenté (indent=2, ensure_ascii=False) pour lisibilité humaine

---

## 4. Benchmarks initiaux — Palier 0 (fondations)

### Philosophie palier 0

Les questions palier 0 doivent être **sans ambiguïté**, avec **une seule bonne réponse**,
testant la compréhension de base. LLCA doit les réussir à ≥ 80% si son SkillLibrary
est correctement alimenté. Si LLCA échoue au palier 0, c'est un signal clair de lacune.

### `python_core/palier_0.json` — 5 questions

```json
[
  {
    "id": "py-p0-001",
    "domain": "python_core",
    "palier": 0,
    "difficulty": "easy",
    "question": "Qu'est-ce que le GIL en Python ? Quel est son impact sur le multithreading ?",
    "expected_concepts": ["Global Interpreter Lock", "thread", "bytecode", "I/O bound", "CPU bound"],
    "rubric": "La réponse doit définir le GIL, expliquer qu'il limite l'exécution bytecode Python à un seul thread à la fois, et distinguer I/O-bound (threads utiles) vs CPU-bound (threads bloqués par GIL).",
    "tags": ["GIL", "concurrency", "threading"]
  },
  {
    "id": "py-p0-002",
    "domain": "python_core",
    "palier": 0,
    "difficulty": "easy",
    "question": "Quelle est la différence entre une liste et un tuple en Python ?",
    "expected_concepts": ["mutable", "immutable", "hashable", "performance", "use case"],
    "rubric": "La réponse doit distinguer mutabilité (liste modifiable, tuple non), hashabilité (tuple hashable donc utilisable comme clé dict), et mentionner au moins un cas d'usage concret pour chaque.",
    "tags": ["collections", "immutable", "basics"]
  },
  {
    "id": "py-p0-003",
    "domain": "python_core",
    "palier": 0,
    "difficulty": "easy",
    "question": "Qu'est-ce qu'un décorateur Python ? Donne un exemple simple.",
    "expected_concepts": ["wrapper", "closure", "functools.wraps", "higher-order function"],
    "rubric": "La réponse doit expliquer qu'un décorateur est une fonction prenant une fonction en argument et retournant une fonction modifiée, avec un exemple de code fonctionnel.",
    "tags": ["decorators", "closures", "OOP"]
  },
  {
    "id": "py-p0-004",
    "domain": "python_core",
    "palier": 0,
    "difficulty": "easy",
    "question": "Qu'est-ce que le duck typing en Python ?",
    "expected_concepts": ["duck typing", "interface", "isinstance", "Protocol", "comportement"],
    "rubric": "La réponse doit expliquer le principe ('si ça marche comme un canard...'), le lier à la philosophie Python (EAFP vs LBYL), et mentionner l'alternative typing.Protocol.",
    "tags": ["typing", "duck-typing", "protocols"]
  },
  {
    "id": "py-p0-005",
    "domain": "python_core",
    "palier": 0,
    "difficulty": "easy",
    "question": "Qu'est-ce qu'un générateur Python et pourquoi l'utiliser ?",
    "expected_concepts": ["yield", "lazy evaluation", "mémoire", "iterable", "generator expression"],
    "rubric": "La réponse doit distinguer générateur vs liste (lazy vs eager), expliquer yield, et mentionner l'avantage mémoire pour les grandes séquences.",
    "tags": ["generators", "memory", "iterables"]
  }
]
```

### `architecture/palier_0.json` — 5 questions

```json
[
  {
    "id": "arch-p0-001",
    "domain": "architecture",
    "palier": 0,
    "difficulty": "easy",
    "question": "Qu'est-ce que le principe SOLID ? Liste les 5 principes.",
    "expected_concepts": ["Single Responsibility", "Open/Closed", "Liskov", "Interface Segregation", "Dependency Inversion"],
    "rubric": "La réponse doit nommer les 5 principes SOLID avec leur description courte. Au moins 3 doivent être expliqués avec un exemple ou une conséquence pratique.",
    "tags": ["SOLID", "OOP", "design-principles"]
  },
  {
    "id": "arch-p0-002",
    "domain": "architecture",
    "palier": 0,
    "difficulty": "easy",
    "question": "Qu'est-ce que le pattern Singleton ? Quand l'utiliser ?",
    "expected_concepts": ["instance unique", "état global", "thread safety", "anti-pattern", "module Python"],
    "rubric": "La réponse doit décrire le pattern (une seule instance), mentionner les risques (état global, tests difficiles), et expliquer qu'en Python un module est déjà un singleton.",
    "tags": ["patterns", "singleton", "creational"]
  },
  {
    "id": "arch-p0-003",
    "domain": "architecture",
    "palier": 0,
    "difficulty": "easy",
    "question": "Qu'est-ce que la séparation des responsabilités (SRP) ? Donne un exemple de violation.",
    "expected_concepts": ["Single Responsibility", "cohésion", "couplage", "raison de changer"],
    "rubric": "La réponse doit définir SRP (une classe = une raison de changer), donner un exemple concret de violation (ex: classe qui lit les données ET les affiche ET les sauvegarde).",
    "tags": ["SOLID", "SRP", "cohesion"]
  },
  {
    "id": "arch-p0-004",
    "domain": "architecture",
    "palier": 0,
    "difficulty": "easy",
    "question": "Quelle est la différence entre composition et héritage en POO ?",
    "expected_concepts": ["composition", "héritage", "couplage", "flexibilité", "has-a vs is-a"],
    "rubric": "La réponse doit distinguer 'est-un' (héritage) vs 'a-un' (composition), expliquer pourquoi 'favor composition over inheritance', et donner un exemple concret.",
    "tags": ["OOP", "composition", "inheritance"]
  },
  {
    "id": "arch-p0-005",
    "domain": "architecture",
    "palier": 0,
    "difficulty": "easy",
    "question": "Qu'est-ce qu'une API REST ? Quels sont ses principes fondamentaux ?",
    "expected_concepts": ["stateless", "ressources", "HTTP verbes", "JSON", "idempotent"],
    "rubric": "La réponse doit mentionner : stateless, ressources identifiées par URL, utilisation des verbes HTTP (GET/POST/PUT/DELETE), format échange (JSON), et idempotence.",
    "tags": ["REST", "API", "HTTP"]
  }
]
```

### `debugging/palier_0.json` — 5 questions

```json
[
  {
    "id": "debug-p0-001",
    "domain": "debugging",
    "palier": 0,
    "difficulty": "easy",
    "question": "Comment lire un traceback Python ? Explique les éléments clés.",
    "expected_concepts": ["call stack", "ligne d'erreur", "exception type", "message", "most recent call last"],
    "rubric": "La réponse doit expliquer la structure d'un traceback : lecture de bas en haut, type d'exception, message, fichier + numéro de ligne, et la pile d'appels.",
    "tags": ["debugging", "traceback", "exceptions"]
  },
  {
    "id": "debug-p0-002",
    "domain": "debugging",
    "palier": 0,
    "difficulty": "easy",
    "question": "Quelle est la différence entre une exception et une erreur en Python ?",
    "expected_concepts": ["BaseException", "Exception", "Error", "SyntaxError", "RuntimeError", "hiérarchie"],
    "rubric": "La réponse doit expliquer la hiérarchie (BaseException → Exception), distinguer erreurs (SyntaxError, IndentationError) des exceptions runtime, et mentionner qu'on attrape généralement Exception.",
    "tags": ["exceptions", "error-handling", "basics"]
  },
  {
    "id": "debug-p0-003",
    "domain": "debugging",
    "palier": 0,
    "difficulty": "easy",
    "question": "Qu'est-ce que pdb et comment l'utiliser pour déboguer du code Python ?",
    "expected_concepts": ["breakpoint()", "pdb.set_trace()", "n/s/c/q", "post-mortem", "inspection variables"],
    "rubric": "La réponse doit mentionner breakpoint() (Python 3.7+) ou pdb.set_trace(), les commandes de base (n=next, s=step, c=continue, q=quit), et comment inspecter les variables locales.",
    "tags": ["pdb", "debugging", "tools"]
  },
  {
    "id": "debug-p0-004",
    "domain": "debugging",
    "palier": 0,
    "difficulty": "easy",
    "question": "Qu'est-ce qu'une NameError en Python ? Quelles en sont les causes courantes ?",
    "expected_concepts": ["variable non définie", "scope", "typo", "import manquant", "closure"],
    "rubric": "La réponse doit expliquer qu'une NameError indique un nom non défini dans le scope courant, lister les causes (typo, variable avant assignation, import oublié, scope incorrect).",
    "tags": ["exceptions", "NameError", "scope"]
  },
  {
    "id": "debug-p0-005",
    "domain": "debugging",
    "palier": 0,
    "difficulty": "easy",
    "question": "Comment utiliser le module logging en Python ? Quels sont les niveaux de log ?",
    "expected_concepts": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "basicConfig", "getLogger"],
    "rubric": "La réponse doit lister les 5 niveaux (DEBUG/INFO/WARNING/ERROR/CRITICAL), expliquer basicConfig pour la configuration de base, et montrer un exemple d'usage logging.getLogger(__name__).",
    "tags": ["logging", "debugging", "best-practices"]
  }
]
```

---

## 5. Tests attendus — `test_eval_05_benchgen.py` (~15 tests)

- `_validate_question` : champs requis présents → True
- `_validate_question` : champ manquant → False
- `_parse_llm_response` : JSON valide → liste dicts
- `_parse_llm_response` : JSON avec balises ```json → parse correct
- `_parse_llm_response` : JSON invalide → [] + log warning
- `_parse_llm_response` : liste partielle (1 valide / 1 invalide) → retourne juste le valide
- `_load_existing` : fichier absent → []
- `_load_existing` : fichier valide → liste BenchQuestion
- `generate()` LLM mocké → liste BenchQuestion (sans doublons avec existants)
- `generate()` déduplication : question identique dans existants → skippée
- `save()` fichier absent → créé avec les questions
- `save()` fichier existant → questions appendées (pas tronquées)
- `save()` JSON indenté + ensure_ascii=False
- `generate()` LLM retourne JSON vide → retourne []
- `_next_seq()` : max existant 3 → next = 4
