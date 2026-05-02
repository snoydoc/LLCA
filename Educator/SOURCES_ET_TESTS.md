# LCCA Educator — Nouvelles sources & Suite de tests d'entraînement

## 1. Nouvelles sources recommandées

### Critères d'inclusion
- Licence : MIT, Apache-2.0, BSD, PSF — ou `skip_license_check: true` si NOASSERTION
- Type hints systématiques, docstrings, pathlib, pas de `shell=True`
- Stars > 1000, code Python 3.9+
- Pertinence directe pour LCCA : patterns agents, AST, LLM, CLI, async, data

---

### 1.1 — Tooling / qualité de code (manque actuel)

| owner | repo | description | skip_license |
|---|---|---|---|
| `psf` | `black` | Formateur Python — patterns AST + libcst excellents | non |
| `PyCQA` | `flake8` | Analyse statique — patterns visitors AST | non |
| `PyCQA` | `isort` | Gestion imports — patterns pathlib complets | non |
| `charliermarsh` | `ruff` | Linter Rust/Python — patterns config + CLI modernes | non |
| `pre-commit` | `pre-commit` | Orchestration hooks — patterns CLI robustes | non |

Commandes d'ajout (bat option [3]) :
```
psf/black           -- Python formatter, AST patterns
PyCQA/flake8        -- Static analysis, AST visitors
PyCQA/isort         -- Import sorting, pathlib
charliermarsh/ruff  -- Modern linter, CLI patterns
pre-commit/pre-commit -- Hook orchestration
```

---

### 1.2 — Async / concurrence (sous-représenté)

| owner | repo | description | skip_license |
|---|---|---|---|
| `python-trio` | `trio` | Async propre — excellente couverture type hints | non |
| `aio-libs` | `aiohttp` | HTTP async — patterns request/response | Apache-2.0 |
| `MagicStack` | `asyncpg` | Driver PostgreSQL async — patterns connection pool | non |

---

### 1.3 — Sérialisation / validation (utile pour les dataclasses LCCA)

| owner | repo | description | skip_license |
|---|---|---|---|
| `marshmallow-code` | `marshmallow` | Sérialisation — patterns from_dict/to_dict | non |
| `python-jsonschema` | `jsonschema` | Validation JSON — patterns guards robustes | non |
| `samuelcolvin` | `msgspec` | Sérialisation rapide — type hints stricts | non |

---

### 1.4 — LLM / agents (directement pertinent pour LCCA)

| owner | repo | description | skip_license |
|---|---|---|---|
| `microsoft` | `promptflow` | Orchestration LLM — patterns proches LCCA | non |
| `BerriAI` | `litellm` | Abstraction multi-LLM — patterns fallback/retry | non |
| `langchain-ai` | `langchain-core` | Core agents LangChain — patterns tool/memory | non |
| `stanfordnlp` | `dspy` | Framework prompts compilés — patterns pipeline | non |

Note : `langchain-core` uniquement, pas `langchain` entier (trop gros).

---

### 1.5 — CLI / configuration (patterns LCCA config + bat)

| owner | repo | description | skip_license |
|---|---|---|---|
| `Textualize` | `textual` | TUI framework — patterns composants + état | non |
| `tiangolo` | `typer` | CLI moderne basé Click — type hints stricts | non |
| `willmcgugan` | `cyclopts` | CLI léger — patterns argparse avancés | non |
| `dynaconf` | `dynaconf` | Config management — patterns environ/fichier | non |

---

### 1.6 — Tests / qualité (renforcer les patterns pytest de LCCA)

| owner | repo | description | skip_license |
|---|---|---|---|
| `pytest-dev` | `pluggy` | Système de plugins pytest — patterns hooks | non |
| `pytest-dev` | `pytest-asyncio` | Tests async — fixtures async patterns | non |
| `tox-dev` | `tox` | Orchestration tests — patterns configuration | non |
| `nedbat` | `coveragepy` | Coverage — patterns AST instrumentation | non |

---

### 1.7 — Repos avec licence non standard (nécessitent skip_license_check)

| owner | repo | description | SPDX réel | skip_license |
|---|---|---|---|---|
| `google` | `yapf` | Formateur — patterns AST | Apache-2.0 mais NOASSERTION via API | **oui** |
| `PyCQA` | `pylint` | Analyse statique complète | GPL-2.0 | **NON — GPL** |
| `python` | `mypy` | Type checker — patterns AST avancés | MIT (mais vérifier) | tester d'abord |

⚠️ Ne jamais ajouter `skip_license_check` sur un repo GPL — le bypass est réservé aux licences permissives mal détectées par l'API GitHub.

---

## 2. Suite de tests d'entraînement

### Objectif
Vérifier que le LLM (`qwen2.5-coder:3b`) a correctement absorbé les patterns
ingérés depuis la whitelist. Trois niveaux : **basique**, **intermédiaire**, **avancé**.

---

### 2.1 — Tests basiques (patterns omniprésents dans la whitelist)

#### T-B1 : Type hints + docstring
```
Prompt :
  Écris une fonction Python `parse_url(raw: str) -> dict` qui extrait
  scheme, host, port et path depuis une URL. Type hints obligatoires,
  docstring en français, pas de print().

Attendu :
  - Signature avec type hints complets
  - Docstring triple-guillemets
  - Utilisation de urllib.parse ou parsing manuel propre
  - Pas de shell=True, pas de print()
  - Moins de 30 lignes
```

#### T-B2 : Pathlib
```
Prompt :
  Écris une fonction `list_python_files(root: Path) -> list[Path]`
  qui liste récursivement tous les .py d'un dossier.
  Utilise pathlib uniquement, pas os.path.

Attendu :
  - from pathlib import Path en import
  - root.rglob("*.py") ou équivalent
  - Retour list[Path] typé
  - Zéro usage de os.path.*
```

#### T-B3 : Dataclass sérialisable
```
Prompt :
  Crée une dataclass Python `CodeSnippet` avec les champs :
  source (str), score (int, défaut 0), tags (list[str], défaut []).
  Ajoute to_dict() et from_dict().

Attendu :
  - @dataclass avec field(default_factory=list) pour tags
  - to_dict() retourne dict
  - from_dict() est classmethod
  - Pas de __init__ manuel
```

---

### 2.2 — Tests intermédiaires (patterns agents + async)

#### T-I1 : Context manager
```
Prompt :
  Écris une classe `TimedBlock` utilisable comme context manager
  qui mesure la durée d'un bloc et log le résultat.
  Utilise logging, pas print().

Attendu :
  - __enter__ / __exit__ corrects
  - log = logging.getLogger(...)
  - log.info("msg %s", var) — PAS log.info(f"msg {var}")
  - time.monotonic() pour la mesure
```

#### T-I2 : Threading lock
```
Prompt :
  Écris une classe `SafeCounter` thread-safe avec méthodes
  increment(), decrement() et value(). Le lock doit être
  un attribut d'instance.

Attendu :
  - self._lock = threading.Lock() dans __init__ (pas de classe)
  - with self._lock: dans chaque méthode
  - Pas de variable de classe partagée
```

#### T-I3 : Retry avec backoff
```
Prompt :
  Écris un décorateur `retry(max_attempts: int, backoff: float)`
  qui relance une fonction en cas d'exception avec backoff
  exponentiel. Type hints obligatoires.

Attendu :
  - Signature propre avec functools.wraps
  - time.sleep(backoff ** attempt)
  - Lève la dernière exception si épuisé
  - Log des tentatives via logging
```

---

### 2.3 — Tests avancés (patterns spécifiques LCCA)

#### T-A1 : Pattern AST visitor
```
Prompt :
  Écris une fonction `count_functions(source: str) -> int` qui
  compte le nombre de fonctions définies dans un fichier Python
  en utilisant ast.walk().

Attendu :
  - ast.parse(source)
  - ast.walk(tree) avec isinstance check
  - Gestion SyntaxError propre
  - Pas de regex
```

#### T-A2 : Pipeline avec résultat typé
```
Prompt :
  Écris un pipeline `run_pipeline(steps: list[Callable]) -> PipelineResult`
  où PipelineResult est une dataclass avec success (bool), output (str),
  errors (list[str]). Chaque step reçoit le résultat précédent.
  Stoppe au premier échec.

Attendu :
  - Dataclass PipelineResult avec field(default_factory=list)
  - Boucle propre avec try/except par step
  - Retour anticipé sur échec
  - Type hints sur tout
```

#### T-A3 : JSON-RPC minimaliste (pattern MCP)
```
Prompt :
  Écris une fonction `handle_jsonrpc(raw: str) -> str | None`
  qui parse un message JSON-RPC 2.0 et retourne la réponse
  sérialisée. Les notifications (sans id) retournent None.
  Gère les erreurs parse avec code -32700.

Attendu :
  - Vérification champs jsonrpc, method, id
  - Notifications : id absent → return None (jamais de réponse)
  - Erreur parse → {"jsonrpc":"2.0","error":{"code":-32700,...},"id":null}
  - json.dumps/loads uniquement
```

#### T-A4 : Test du pattern generate_text (pattern LCCA spécifique)
```
Prompt :
  Écris une fonction `generate_text(system: str, user: str) -> str`
  qui appelle une API LLM locale (endpoint http://localhost:11434/api/generate)
  via urllib.request uniquement. Timeout infini. Retourne le texte généré.

Attendu :
  - urllib.request.Request + urlopen(timeout=None)
  - json.dumps pour le body, json.loads pour la réponse
  - PAS de import requests
  - Gestion du streaming ligne par ligne si nécessaire
```

---

### 2.4 — Tests de régression (anti-patterns connus)

Ces prompts vérifient que le modèle N'apprend PAS les mauvais patterns.

#### T-R1 : Anti-pattern f-string dans log
```
Prompt :
  Écris une fonction qui log un message avec une variable.

Signal d'échec :
  log.info(f"traitement de {item}")   ← MAUVAIS

Signal de succès :
  log.info("traitement de %s", item)  ← CORRECT
```

#### T-R2 : Anti-pattern "python" hardcodé
```
Prompt :
  Écris un script qui lance un sous-processus Python.

Signal d'échec :
  subprocess.run(["python", ...])      ← MAUVAIS

Signal de succès :
  subprocess.run([sys.executable, ...]) ← CORRECT
```

#### T-R3 : Anti-pattern lock de classe
```
Prompt :
  Écris une classe thread-safe avec un compteur partagé.

Signal d'échec :
  class Foo:
      _lock = threading.Lock()         ← MAUVAIS (partagé entre instances)

Signal de succès :
  def __init__(self):
      self._lock = threading.Lock()    ← CORRECT
```

---

### 2.5 — Protocole d'évaluation

Pour chaque test, évaluer sur 4 critères (score 0-3 chacun, max 12) :

| Critère | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| **Correction** | Erreur syntaxe/logique | Fonctionne partiellement | Fonctionne | Fonctionne + cas limites |
| **Style LCCA** | Aucun pattern respecté | 1-2 patterns | 3-4 patterns | Tous les patterns |
| **Type hints** | Absents | Partiels | Complets | Complets + génériques |
| **Régression** | Anti-pattern présent | — | — | Aucun anti-pattern |

**Seuil de validation** : score moyen ≥ 9/12 sur l'ensemble T-B + T-I.
**Seuil avancé** : score moyen ≥ 8/12 sur T-A.

---

### 2.6 — Script de test rapide (à lancer après ingestion)

Sauvegarder dans `Educator/test_training.py` et lancer avec le venv :

```python
# test_training.py -- smoke test post-ingestion
# Lance 3 prompts basiques et vérifie les patterns LCCA

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

PROMPTS = [
    {
        "id": "T-B1",
        "prompt": "Écris une fonction parse_url(raw: str) -> dict avec type hints et docstring.",
        "must_contain": ["->", '"""', "def parse_url"],
        "must_not_contain": ["print(", "shell=True"],
    },
    {
        "id": "T-B2",
        "prompt": "Écris list_python_files(root: Path) -> list[Path] avec pathlib uniquement.",
        "must_contain": ["pathlib", "Path", "->"],
        "must_not_contain": ["os.path"],
    },
    {
        "id": "T-I2",
        "prompt": "Écris SafeCounter thread-safe, lock en attribut d'instance.",
        "must_contain": ["self._lock = threading.Lock()", "with self._lock"],
        "must_not_contain": ["_lock = threading.Lock()"],  # lock de classe
    },
]

def run_tests():
    try:
        import config
        from core.llm_generator import generate_text
    except ImportError as e:
        print(f"[ERREUR] Import : {e}")
        sys.exit(1)

    results = []
    for t in PROMPTS:
        print(f"\n{'='*50}")
        print(f"  {t['id']} : {t['prompt'][:60]}...")
        try:
            response = generate_text(
                system="Tu es un expert Python. Réponds uniquement avec du code.",
                user=t["prompt"],
            )
            ok_pos = all(kw in response for kw in t["must_contain"])
            ok_neg = all(kw not in response for kw in t["must_not_contain"])
            status = "PASS" if (ok_pos and ok_neg) else "FAIL"
            results.append((t["id"], status))
            print(f"  Résultat : {status}")
            if not ok_pos:
                missing = [k for k in t["must_contain"] if k not in response]
                print(f"  Manquant : {missing}")
            if not ok_neg:
                found = [k for k in t["must_not_contain"] if k in response]
                print(f"  Anti-pattern détecté : {found}")
        except Exception as e:
            results.append((t["id"], "ERROR"))
            print(f"  ERREUR : {e}")

    print(f"\n{'='*50}")
    passed = sum(1 for _, s in results if s == "PASS")
    print(f"  RÉSULTATS : {passed}/{len(results)} PASS")
    for tid, status in results:
        mark = "✓" if status == "PASS" else "✗"
        print(f"    {mark} {tid} : {status}")
    print(f"{'='*50}\n")
    return 0 if passed == len(results) else 1

if __name__ == "__main__":
    sys.exit(run_tests())
```

Lancement :
```bat
D:\LLMCodeAgent\venv\Scripts\python.exe D:\LLMCodeAgent\Educator\test_training.py
```
