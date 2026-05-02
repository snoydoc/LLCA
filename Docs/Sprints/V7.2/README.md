# LCCA V7.2 — Plan de migration Spec Layer
<!-- AI-READY | Index Migration V7.2 | 2026-04-18 -->

## Contexte

La spec `LLCA_V7_2.md` définit une architecture **Spec Layer** plus rigoureuse que ce qui
a été implémenté dans les Sprints 14-19. Ce dossier contient les sprints de migration.

---

## Analyse des écarts (résumé)

### `spec_entry.py` — 8 champs manquants

| Champ V7.2 | Statut |
|---|---|
| `domain: str` (VALID_DOMAINS) | ❌ Absent |
| `version: str` | ❌ Absent |
| `complexity_score: int` (0-100) | ❌ `complexity: int` (1-10) — échelle différente |
| `generated_by: str` | ❌ Absent |
| `validated: bool` | ❌ Absent — **CRITIQUE** (Règle 11) |
| `validation_notes: str` | ❌ Absent |
| `superseded_by: Optional[str]` | ❌ Absent — **CRITIQUE** (Règle 13) |
| `deprecated: bool` | ❌ Absent |
| `make_spec_id(body_md)` | ⚠️ Signature différente (`title, abstract` au lieu de `body_md`) |
| `is_usable()` logique complète | ⚠️ Incomplète (manque validated/deprecated/superseded) |

### `spec_validator.py` — Interface entièrement différente

| Aspect | V7.2 | Actuel |
|---|---|---|
| `RuleChecker` | ABC + classes concrètes | `@dataclass` + lambdas |
| `analyze(body_md)` | Analyse le **texte** de la spec | Analyse les **champs** de SpecEntry |
| Contenu des règles | 10 règles architecturales V5 + 5 règles V7 | 15 règles structurelles (titre, abstract...) |
| `validate()` retour | `dict` | `ValidationResult` dataclass |

### `spec_generator.py` — Écarts de signature

| Aspect | V7.2 | Actuel |
|---|---|---|
| `generate(intent, domain, context)` | `domain` manquant | Manque domaine |
| `_compute_complexity()` | sections*5 + règles*3 | Regex sur texte |
| Propagation `validated` | Oui | Non |

### `cognitive_patterns.py` — Prompts appauvris

| Aspect | V7.2 | Actuel |
|---|---|---|
| Prompts système | Longs, détaillés, rôles précis | Simplifiés 1-2 phrases |
| Configurabilité | `config.COGNITIVE_PROMPTS` | Prompts hardcodés |

---

## Sprints planifiés

| Sprint | Fichier | Statut | Cible tests |
|--------|---------|--------|-------------|
| **20** | `sprint-20-spec-entry-v72.md` | 🔮 À FAIRE | 517 → 525 |
| **21** | `sprint-21-spec-validator-v72.md` | 🔮 À FAIRE | 525 → 536 |
| **22** | `sprint-22-finalisation-v72.md` | 🔮 À FAIRE | 536 → ~540 |

---

## Règles de migration

1. **Rétrocompat obligatoire** : chaque sprint maintient les tests existants verts
2. **Pas de big bang** : migration fichier par fichier, validation tests à chaque étape
3. **Double interface pendant transition** : `validate()` dict + `validate_compat()` dataclass
4. **Legacy supprimé en dernier** : uniquement Sprint 22 quand tout le code l'utilise en V7.2
5. **Lire skill 001 en premier** à chaque session — les patterns de migration s'accumulent

---

## Commande de validation entre chaque sprint

```powershell
cd D:\LLMCodeAgent
.\venv\Scripts\Activate.ps1
pytest tests/ -q --tb=short
```

<!-- AI-READY | Index Migration V7.2 | 2026-04-18 -->
