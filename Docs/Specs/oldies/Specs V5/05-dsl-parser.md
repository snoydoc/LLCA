# Spec 05 — DSLParser
<!-- AI-READY | core/dsl_parser.py | Sprint 04 | Tests: intégrés dans test_orchestrator.py -->

## Rôle

Traduit une commande textuelle LCCA en objet `Intent` structuré.
Supporte deux formats : **structuré** (tirets) et **langage naturel** (fallback).

---

## Localisation

```
D:\LLMCodeAgent\core\dsl_parser.py
```

---

## Format DSL structuré

```
"Projet - Cible - Action Détails"
"Projet - Cible - Sous-cible - Action Détails"
```

**Exemples :**
```
"DashV1 - Auth - Ajoute validate_email()"
"DashV1 - RDV - Modal En Consultation - Modifie send_sms()"
"MediBot - Conversation - Corrige handle_timeout"
```

---

## Dataclass `Intent`

```python
@dataclass
class Intent:
    project: str              # "DashboardV1"
    target: str               # "Auth" | "Page RDV"
    sub_target: Optional[str] # "Modal En Consultation" (4 parties seulement)
    action: str               # "ajoute" | "modifie" | "supprime" | "cree" | ...
    details: str              # "validate_email()" | description brute
    raw: str                  # Commande originale non modifiée
    confidence: float         # Score de confiance (0.0 à 1.0)
```

### Actions reconnues (`ACTIONS`)

```python
{"ajoute", "modifie", "supprime", "cree", "crée",
 "refactor", "corrige", "renomme", "deplace"}
```

### Niveaux de confiance

| Format | Confidence | Interprétation |
|--------|-----------|----------------|
| Structuré 3 parties | `1.0` | Parsing sûr |
| Structuré 4 parties | `0.95` | Très fiable |
| NL avec action trouvée | `0.4` | Ambigu |
| NL sans action | `0.2` | Très incertain |

### `Intent.is_confident() → bool`

Retourne `True` si `confidence >= 0.5`.

### `Intent.summary() → str`

Résumé lisible pour les logs :
```
"[DashV1 > Auth] ajoute → validate_email()"
```

### `Intent.to_dsl() → str`

Convertit l'NLIntent vers le format DSL Sprint 04 (utilisé par `NLOrchestrator`).

---

## `DSLParser` — API publique

### `parse(command: str) → Intent`

Point d'entrée principal. **Toujours retourne un `Intent`** (jamais d'exception).

**Algorithme :**
1. Strip de la commande
2. Si vide → `Intent` avec `confidence=0.0`
3. Split sur `" - "` → liste de parties
4. Si ≥ 3 parties → `_parse_structured()`
5. Sinon → `_parse_natural()`

### `_parse_structured(parts, raw) → Intent`

**3 parties :** `Projet - Cible - Action Détails`
→ confidence `1.0`

**4+ parties :** `Projet - Cible - Sous-cible - Action Détails`
→ confidence `0.95`, `action_str = " - ".join(parts[3:])`

### `_split_action(text) → Tuple[str, str]`

Sépare `"Ajoute validate_email()"` en `("ajoute", "validate_email()")`.

1. Split sur le premier espace
2. Normalise le premier mot (`_normalize_action`)
3. Si dans `ACTIONS` → retourne `(action, rest)`
4. Sinon cherche l'action dans toute la chaîne via regex
5. Si introuvable → `("modifie", text)`

### `_parse_natural(command) → Intent`

Parsing best-effort d'une phrase NL.

1. Cherche une action dans la commande
2. Extrait un fichier `.py` mentionné (`target`)
3. Retourne confidence `0.4` (action trouvée) ou `0.2`

---

## Normalisation des accents

```python
_ACCENT_MAP = {
    "crée": "cree",
    "déplace": "deplace",
    "corrigé": "corrige",
}
```

---

## Intégration

`DSLParser` est utilisé dans :
- `LCCAV5Fusion.execute()` — étape 1
- `LCCAV5Fusion.dry_run()` — simulation
- `NLOrchestrator.run()` — via `NLIntent.to_dsl()`

---

## Exemple d'usage

```python
from core.dsl_parser import DSLParser

parser = DSLParser()
intent = parser.parse("MediBot - Auth - Ajoute validate_token()")

print(intent.project)     # "MediBot"
print(intent.target)      # "Auth"
print(intent.action)      # "ajoute"
print(intent.details)     # "validate_token()"
print(intent.confidence)  # 1.0
print(intent.is_confident())  # True
```
