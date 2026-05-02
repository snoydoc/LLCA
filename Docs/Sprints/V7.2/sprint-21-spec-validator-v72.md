# Sprint 21 — Migration spec_validator.py et cognitive_patterns.py vers spec V7.2
<!-- AI-READY | Sprint 21 Migration spec_validator + cognitive_patterns + spec_generator | 2026-04-20 TERMINÉ -->

## ✅ Statut : TERMINÉ (2026-04-20)

**Note** : À l'ouverture de ce sprint, l'analyse a révélé que le code était
déjà intégralement migré V7.2 par les sessions REFACTO-01 et Sprint 20 :
- `spec_validator.py` + `spec_validator_rules.py` : RULE_REGISTRY V7.2 (15 règles), `validate()` → dict, `_format_notes()`, `validator_pattern=` compat.
- `cognitive_patterns.py` : prompts longs V7.2, `SpecDirectPattern` SPEC-01/02.
- `spec_generator.py` : `generate(domain=)`, `_compute_complexity()`, `spec.validated` propagé.
- `test_spec_layer.py` : `TestRuleRegistryV72` (8 tests), `TestSpecValidatorService` (8 tests), `TestSpecGeneratorService` (12 tests dont les 3 Sprint 21).
- `test_spec_orchestrator.py` : `validated=True` partout, champs V7.2 vérifiés.

Items "absents" du plan (`RULE_REGISTRY_LEGACY`, `validate_compat()`) : non requis—
aucun test ne les utilise et le code V7.2 est déjà l'interface unique.

Suite du Sprint 20 (migration `SpecEntry`). Ce sprint migre :
- `spec_validator.py` : `RuleChecker` ABC → classes concrètes sur `body_md`, `validate()` → `dict`
- `cognitive_patterns.py` : prompts enrichis conformes à la spec V7.2
- `spec_generator.py` : signature `generate(intent, domain, context)`, `_compute_complexity()`

**Prérequis** : Sprint 20 terminé (SpecEntry V7.2 en place).

---

## Périmètre Sprint 21

| Module | Fichier | Type |
|--------|---------|------|
| Validation | `core/spec_validator.py` | 🔄 MIGRATION COMPLÈTE |
| Patterns cognitifs | `core/cognitive_patterns.py` | 🔄 MIGRATION PROMPTS |
| Génération | `core/spec_generator.py` | 🔄 MIGRATION SIGNATURE |
| Tests validator | `tests/test_spec_layer.py` | 🔄 MISE À JOUR MAJEURE |
| Tests orchestrateur | `tests/test_spec_orchestrator.py` | 🔄 MISE À JOUR |

---

## 1. Migration `spec_validator.py`

### 1.1 Écarts critiques

| Actuel (Sprints 14-19) | Spec V7.2 | Impact |
|---|---|---|
| `RuleChecker` = `@dataclass` avec lambda | `RuleChecker` = ABC avec classes concrètes | Interface différente |
| `analyze(spec: SpecEntry) -> list[str]` | `analyze(body_md: str) -> list[dict]` | Les règles analysent le **texte** de la spec, pas ses champs |
| Règles R01-R15 : vérifications de champs (titre vide, abstract vide...) | Règles rule_1 à rule_15 : vérifications architecturales sur le corps Markdown | Contenu entièrement différent |
| `validate()` retourne `ValidationResult` dataclass | `validate()` retourne `dict` | Type de retour différent |
| Pas de `_format_notes()` | `_format_notes(violations)` helper | Helper manquant |
| Pas de filtrage des règles | `rules: Optional[list[str]]` dans `__init__` | Filtrage absent |

### 1.2 Stratégie de migration

**Problème** : les 517 tests passent avec l'interface actuelle. La migration casse l'interface.

**Solution** : double interface pendant la transition (Sprint 21), suppression legacy Sprint 22.

```python
class SpecValidatorService:
    def __init__(
        self,
        llm_pattern=None,
        rules: Optional[list[str]] = None,
        # Rétrocompat Sprint 14-19
        validator_pattern=None,
    ) -> None:
        self._llm = llm_pattern or validator_pattern
        self._rules = rules or list(RULE_REGISTRY.keys())

    def validate(self, spec: "SpecEntry") -> dict:
        """
        Retourne dict (spec V7.2) avec clés :
        - valid: bool
        - score: float
        - violations: list[dict]  ← dicts avec rule, severity, location, fix_suggestion
        - validation_notes: str
        """
        ...

    def validate_compat(self, spec: "SpecEntry") -> "ValidationResult":
        """
        Wrapper rétrocompat pour les tests Sprint 14-19 qui attendent ValidationResult.
        Sera supprimé Sprint 22.
        """
        result = self.validate(spec)
        return ValidationResult(
            violations=[v.get("location", str(v)) for v in result["violations"]],
            blocking=sum(1 for v in result["violations"] if v.get("severity") == "blocking"),
            score=result["score"],
            valid=result["valid"],
            llm_feedback="",
        )
```

**Pour les tests existants** : patcher `SpecValidatorService.validate` pour retourner
un objet compatible (duck-typing). Alternative : mettre à jour les tests pour le dict.

### 1.3 RULE_REGISTRY V7.2 complet

Les 15 règles de la spec V7.2 analysent `body_md` (le texte de la spec) :

```
rule_1_smartpatcher_str         — apply_patch + write_text directs → blocking
rule_2_ast_read_libcst_write    — ast.parse pour modification → warning
rule_3_max_files                — >3 fichiers/TX mentionnés → blocking
rule_4_snapshot_md5             — FileSnapshot sans content_hash → warning
rule_5_wal_append_only          — modification du WAL → blocking
rule_6_llm_fallback             — FallbackGenerator + raise → warning
rule_7_dependency_injection     — instanciation dans méthodes → warning
rule_8_sys_executable           — subprocess + "python" hardcodé → blocking
rule_9_module_level_imports     — import dans corps de fonction → warning
rule_10_utf8_sig                — JSON avec utf-8-sig → warning
rule_11_no_code_if_invalid_spec — bypass spec invalide → blocking
rule_12_complexity_first        — generate_spec sans should_generate_spec → warning
rule_13_spec_versioned          — SpecEntry sans superseded_by → warning
rule_14_invalid_spec_stops      — continuation malgré spec invalide → blocking
rule_15_patterns_configurable   — (sémantique — retourne toujours [])
```

### 1.4 Problème de coexistence RULE_REGISTRY

**Actuel** : `RULE_REGISTRY = {"R01": RuleChecker(...), ..., "R15": ...}` clés courtes.
**V7.2** : `RULE_REGISTRY = {"rule_1_smartpatcher_str": Rule1SmartPatcherStr(), ...}` clés longues.

Garder les deux registres pendant la transition :

```python
RULE_REGISTRY: dict[str, RuleChecker] = { ... }       # V7.2 — règles sur body_md
RULE_REGISTRY_LEGACY: dict[str, ...] = { ... }         # Legacy R01-R15 — règles sur champs
```

---

## 2. Migration `cognitive_patterns.py`

### 2.1 Écarts

| Actuel | Spec V7.2 | Impact |
|---|---|---|
| `self._generator` | `self._gen` | Mineur — renommage interne |
| Prompts simplifié en 1-2 phrases | Prompts longs avec instructions détaillées | Qualité de génération |
| Pas de `COGNITIVE_PROMPTS` configurable | Prompts depuis `config.COGNITIVE_PROMPTS` | Configurabilité |

### 2.2 Nouveaux prompts V7.2

```python
# À la place des prompts inline actuels, utiliser les constants de la spec :

_DEEP_REASONING_SYSTEM = """\
Tu es un architecte logiciel senior. Avant d'écrire du code ou du Markdown :
1. Identifie les 3 options possibles
2. Pour chaque option, liste risques et bénéfices
3. Choisis la meilleure option et justifie
4. Définis les interfaces et contrats avant l'implémentation

Ne génère pas de code. Génère une analyse structurée en sections JSON ou bullet points.
"""

_SPEC_FORMATTER_SYSTEM = """\
Tu es un technical writer expert. Transforme l'analyse architecturale fournie
en document Markdown strict selon ce format :
- Header AI-READY avec version et date
- Tableaux pour les dataclasses et API
- Code blocks Python avec type hints
- Règles invariantes numérotées
- Checklist de validation finale

Règles absolues :
- Jamais de markdown à l'intérieur des tableaux
- Toujours utiliser le français technique
- Référencer explicitement les addendum précédents
"""

_SPEC_VALIDATOR_SYSTEM = """\
Tu es un reviewer technique obsessionnel. Ton rôle : trouver les contradictions.
Vérifie strictement :
- Les dataclasses ont-elles des champs cohérents avec l'usage décrit ?
- Les règles invariantes V5/V7 sont-elles violées ?
- Les chemins de rollback sont-ils cohérents ?
- Y a-t-il des références circulaires ou des dépendances manquantes ?

Réponds UNIQUEMENT en JSON strict :
{"violations": [{"rule": "...", "severity": "blocking|warning", "location": "...", "fix_suggestion": "..."}]}
Si aucune violation : {"violations": []}
"""
```

### 2.3 Impact sur les tests

Les tests `TestCognitivePatterns` vérifient que `generate_text()` est appelé mais
ne testent pas le contenu des prompts → pas de régression sur les tests existants.

Seul risque : si un test compare `_SYSTEM` exactement → aucun test ne le fait.

---

## 3. Migration `spec_generator.py`

### 3.1 Écarts

| Actuel | Spec V7.2 | Impact |
|---|---|---|
| `generate(prompt, context)` | `generate(intent, domain, context)` | `domain` manquant |
| `auto_fix(spec, max_iter)` | `auto_fix(spec, violations, max_iterations)` | Signature différente |
| `_extract_complexity()` — regex sur texte | `_compute_complexity()` — sections*5 + règles*3 | Algorithme différent |
| Retourne `SpecEntry` non validée avec `score` | Retourne `SpecEntry` non validée, `validated=False` | `validated` non géré |

### 3.2 Changements ciblés

**`generate()`** — ajouter `domain` et renseigner `SpecEntry.domain` + `SpecEntry.generated_by` :
```python
def generate(self, prompt: str, context: str = "", domain: str = "global") -> "SpecEntry":
    ...
    spec = SpecEntry(
        spec_id=spec_id, title=title, abstract=abstract, body_md=body_md,
        domain=domain,
        generated_by="hybrid",
        complexity=complexity,
        complexity_score=_compute_complexity(body_md),
    )
    result = self._validator.validate(spec)
    spec.score = result["score"] if isinstance(result, dict) else result.score
    spec.validated = result["valid"] if isinstance(result, dict) else result.valid
    spec.validation_notes = result.get("validation_notes", "") if isinstance(result, dict) else ""
    return spec
```

**`_compute_complexity()`** — algorithme V7.2 :
```python
def _compute_complexity(body_md: str) -> int:
    sections = len([l for l in body_md.splitlines() if l.startswith("## ")])
    rules = len([l for l in body_md.splitlines() if l.strip().startswith("| ")])
    return min(100, sections * 5 + rules * 3)
```

**`auto_fix()`** — conserver la signature actuelle (court-circuit Sprint 18 = bonne pratique),
ajouter extraction des violations en `list[dict]` :
```python
def auto_fix(self, spec: "SpecEntry", max_iter: int | None = None) -> "SpecEntry":
    # Conserver court-circuit Sprint 18 (delta < 0.05)
    # Adapter la récupération de violations selon le type de retour validate()
    ...
```

---

## 4. Nouveaux tests Sprint 21

### 4.1 `TestRuleRegistryV72` — règles sur body_md

```python
class TestRuleRegistryV72:

    def test_registry_has_15_v72_rules(self):
        assert len(RULE_REGISTRY) == 15

    def test_rule1_detects_direct_write_after_patch(self):
        body = "Appeler apply_patch()\n puis write_text() directement"
        violations = RULE_REGISTRY["rule_1_smartpatcher_str"].analyze(body)
        assert any(v["severity"] == "blocking" for v in violations)

    def test_rule3_detects_4_files_per_tx(self):
        body = "Modifier 4 fichiers par transaction"
        violations = RULE_REGISTRY["rule_3_max_files"].analyze(body)
        assert violations

    def test_rule8_detects_hardcoded_python(self):
        body = "subprocess.run(['python', 'script.py'])"
        violations = RULE_REGISTRY["rule_8_sys_executable"].analyze(body)
        assert any(v["severity"] == "blocking" for v in violations)

    def test_rule10_warns_json_utf8_sig(self):
        body = "Écrire les JSON en utf-8-sig"
        violations = RULE_REGISTRY["rule_10_utf8_sig"].analyze(body)
        assert violations

    def test_clean_body_has_no_violations(self):
        body = "## Spec propre\n\nAucune violation attendue ici.\n\n## Critères\n- OK"
        for rule in RULE_REGISTRY.values():
            assert rule.analyze(body) == [], f"Faux positif règle {rule.rule_id}"

class TestSpecValidatorServiceV72:

    def test_validate_returns_dict(self):
        spec = _make_spec(validated=False)
        result = SpecValidatorService().validate(spec)
        assert isinstance(result, dict)
        assert "valid" in result
        assert "score" in result
        assert "violations" in result

    def test_validate_sets_validated_on_spec(self):
        """validate() doit mettre à jour spec.validated."""
        spec = _make_spec()
        svc = SpecValidatorService()
        result = svc.validate(spec)
        assert spec.validated == result["valid"]
```

### 4.2 Mise à jour `TestSpecGeneratorService`

```python
def test_generate_sets_domain(self):
    spec = self._make_svc().generate("Créer module X", domain="mcp")
    assert spec.domain == "mcp"

def test_generate_sets_validated(self):
    spec = self._make_svc().generate("Créer module X")
    # validated doit être True ou False selon le résultat du validator
    assert isinstance(spec.validated, bool)

def test_generate_sets_generated_by(self):
    spec = self._make_svc().generate("Créer module X")
    assert spec.generated_by == "hybrid"
```

---

## 5. Ordre d'exécution des modifications

1. `core/spec_validator.py` — RULE_REGISTRY V7.2 + `validate()` retourne dict + `validate_compat()`
2. `core/cognitive_patterns.py` — nouveaux prompts (pas de changement d'interface)
3. `core/spec_generator.py` — `generate(domain=)` + `_compute_complexity()` + propagation `validated`
4. `tests/test_spec_layer.py` — `TestRuleRegistryV72` + `TestSpecValidatorServiceV72` + update existants
5. `tests/test_spec_orchestrator.py` — mise à jour fixtures `validated=True`

---

## 6. Checklist validation Sprint 21

- [ ] `RULE_REGISTRY` V7.2 : 15 règles sur `body_md` avec `analyze() -> list[dict]`
- [ ] `RULE_REGISTRY_LEGACY` conservé pour rétrocompat (R01-R15)
- [ ] `validate()` retourne `dict` avec clés `valid, score, violations, validation_notes`
- [ ] `validate_compat()` wrapper rétrocompat → `ValidationResult`
- [ ] `SpecValidatorService.__init__` accepte `validator_pattern=` (compat Sprint 14)
- [ ] `_format_notes(violations)` helper implémenté
- [ ] Prompts V7.2 dans `cognitive_patterns.py` (system prompts longs)
- [ ] `generate(domain=)` dans `spec_generator.py`
- [ ] `_compute_complexity()` V7.2 (sections*5 + règles*3, max 100)
- [ ] `spec.validated` renseigné par `generate()`
- [ ] 5 nouveaux tests `TestRuleRegistryV72` passent
- [ ] 3 nouveaux tests `TestSpecValidatorServiceV72` passent
- [ ] 3 nouveaux tests `TestSpecGeneratorService` passent
- [ ] 517 tests existants restent verts

<!-- AI-READY | Sprint 21 Migration spec_validator + cognitive_patterns + spec_generator | 2026-04-18 -->
