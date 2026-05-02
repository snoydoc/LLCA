"""
prompts.py -- Prompts de test pour le benchmark
8 types de taches : 6 performance + 2 qualite (raisonnement + architecture)
"""

PROMPTS = [
    {
        "id": "code_simple",
        "label": "Code simple",
        "description": "Generation d'une fonction Python basique",
        "prompt": "Ecris une fonction Python qui calcule le nombre de jours entre deux dates. Inclus la docstring et un exemple d'utilisation."
    },
    {
        "id": "code_classe",
        "label": "Code - Classe",
        "description": "Generation d'une classe Python complete",
        "prompt": "Cree une classe Python 'GestionnaireCache' qui stocke des paires cle/valeur avec une duree de vie (TTL). Implemente les methodes set(), get(), et purge_expired(). Ajoute les type hints et la docstring."
    },
    {
        "id": "debug",
        "label": "Debogage",
        "description": "Analyse et correction d'un bug",
        "prompt": """Voici un bug Python. Explique ce qui ne va pas et corrige-le :

```python
def moyenne(nombres):
    total = 0
    for n in nombres:
        total += n
    return total / len(nombres)

resultats = []
print(moyenne(resultats))
```"""
    },
    {
        "id": "explication",
        "label": "Explication concept",
        "description": "Explication pedagogique d'un concept technique",
        "prompt": "Explique le concept de 'context manager' en Python (with statement). Pourquoi l'utiliser ? Montre un exemple concret avec la gestion de fichiers, puis comment creer le sien avec __enter__ et __exit__."
    },
    {
        "id": "refactor",
        "label": "Refactoring",
        "description": "Amelioration de code existant",
        "prompt": """Refactorise ce code pour le rendre plus lisible et maintenable :

```python
def p(d):
    r = []
    for i in d:
        if i['a'] > 18:
            if i['s'] == 'M':
                r.append({'n': i['n'], 'e': i['e'] * 1.1})
            else:
                r.append({'n': i['n'], 'e': i['e'] * 1.05})
    return r
```

Explique chaque changement."""
    },
    {
        "id": "generation_tests",
        "label": "Generation de tests",
        "description": "Ecriture de tests unitaires",
        "prompt": """Ecris des tests unitaires pytest complets pour cette fonction :

```python
def valider_email(email: str) -> bool:
    if not isinstance(email, str):
        return False
    parties = email.split('@')
    if len(parties) != 2:
        return False
    local, domaine = parties
    if not local or not domaine:
        return False
    if '.' not in domaine:
        return False
    return True
```

Couvre : cas valides, cas invalides, cas limites."""
    },
    # --- QUALITE : raisonnement logique ---
    {
        "id": "reasoning",
        "label": "Raisonnement logique",
        "description": "Capacite a raisonner etape par etape sur un probleme algorithmique",
        "prompt": """Un programme Python recoit une liste d'entiers. Il doit retourner la longueur de la plus longue sous-sequence strictement croissante (pas forcement contigue). Exemple : [10, 9, 2, 5, 3, 7, 101, 18] -> 4 (2,3,7,101). Explique d'abord l'approche optimale (complexite), puis ecris le code avec type hints et tests."""
    },
    # --- QUALITE : architecture ---
    {
        "id": "architecture",
        "label": "Architecture code",
        "description": "Capacite a concevoir une architecture propre avec separation des responsabilites",
        "prompt": """Concois une architecture Python pour un systeme de cache distribue simple avec : interface abstraite (ABC), implementation en memoire, implementation Redis optionnelle, decorateur @cached(ttl=60), gestion des erreurs et fallback silencieux si Redis absent. Fournis la structure des fichiers, les classes principales avec leurs methodes (signatures uniquement), et explique les choix de design."""
    },
]


def get_prompt_by_id(prompt_id: str) -> dict:
    """Retourne un prompt par son identifiant"""
    for p in PROMPTS:
        if p["id"] == prompt_id:
            return p
    return PROMPTS[0]


def get_quick_prompts() -> list:
    """Retourne 2 prompts courts pour un test rapide"""
    return [PROMPTS[0], PROMPTS[2]]  # code_simple + debug


def get_quality_prompts() -> list:
    """Retourne les 2 prompts qualite (reasoning + architecture)"""
    ids = {"reasoning", "architecture"}
    return [p for p in PROMPTS if p["id"] in ids]
