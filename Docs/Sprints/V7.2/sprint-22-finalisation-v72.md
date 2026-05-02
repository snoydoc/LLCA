# Sprint 22 — Finalisation V7.2 : nettoyage legacy + intégration orchestrateur ✅ TERMINÉ (2026-04-21)
<!-- AI-READY | Migration Spec Layer | Version 7.2.0 | 2026-04-18 -->

## Contexte

Sprint final de migration V7.2. Après Sprint 20 (SpecEntry) et Sprint 21 (Validator +
Generator), ce sprint :
1. Supprime le code legacy introduit pour la transition (Sprints 14-19)
2. Met à jour l'Orchestrateur pour propager `domain` dans la Spec Layer
3. Met à jour le MCP Server pour les nouveaux champs SpecEntry
4. Réécrit `test_spec_layer.py` complet en conformité V7.2
5. Valide la conformité totale avec la checklist de la spec

**Prérequis** : Sprints 20 et 21 terminés et verts.

---

## Périmètre Sprint 22

| Module | Fichier | Type |
|--------|---------|------|
| Legacy cleanup | `core/spec_validator.py` | 🗑️ SUPPRESSION `validate_compat()` + `RULE_REGISTRY_LEGACY` |
| Orchestrateur | `core/orchestrator.py` | 🔄 PROPAGATION domain |
| MCP Server | `core/mcp_server.py` | 🔄 MISE À JOUR generate_spec tool |
| Tests complets | `tests/test_spec_layer.py` | 🔄 RÉÉCRITURE V7.2 |
| Skills | `.claude-skills/` | 📝 MISE À JOUR |

---

## 1. Suppression du code legacy de transition

### 1.1 `spec_validator.py` — supprimer

```python
# À SUPPRIMER Sprint 22 :
def validate_compat(self, spec) -> ValidationResult: ...   # wrapper transition
RULE_REGISTRY_LEGACY: dict = { ... }                       # R01-R15 sur champs SpecEntry
@dataclass class ValidationResult: ...                     # remplacé par dict
```

**Attention** : vérifier que `_run_spec_layer()` dans `orchestrator.py` n'utilise plus
`ValidationResult` directement avant suppression. Chercher tous les `result.valid`,
`result.score`, `result.violations` dans le code et les migrer vers `result["valid"]` etc.

**Fichiers à vérifier** :
```
grep -r "ValidationResult" core/ tests/
grep -r "result\.valid\b" core/
grep -r "result\.score\b" core/
grep -r "\.violations\b" core/
```

### 1.2 `spec_entry.py` — décider du sort des champs legacy

Champs legacy conservés Sprint 20 (`complexity`, `tags`, `created_at`, `promoted`, `score`) :
- `score` → gardé (utilisé dans `is_usable()`)
- `complexity` → à supprimer Sprint 22 (remplacé par `complexity_score`)
- `tags` → à garder (utile en production)
- `created_at` → à garder (traçabilité)
- `promoted` → à évaluer (doublon partiel avec `memory_layer`)

**Décision** :
- Supprimer `complexity` (migrer vers `complexity_score` partout)
- Conserver `tags`, `created_at`
- Conserver `promoted` (sémantique différente de `memory_layer`)

---

## 2. Mise à jour `orchestrator.py` — propagation `domain`

### 2.1 Modification `_run_spec_layer()`

```python
def _run_spec_layer(self, intent) -> bool:
    ...
    domain = _infer_domain(intent)

    # Génération avec domain (Sprint 22)
    spec = self._spec_generator.generate(
        prompt=intent.raw,
        context=f"domain:{domain}",
        domain=domain,                    # ← propagé au générateur
    )

    # Validation : validate() retourne maintenant dict (Sprint 21)
    val = self._spec_validator.validate(spec)
    if not val["valid"]:                  # ← dict access, plus val.valid
        spec = self._spec_generator.auto_fix(spec)
        val = self._spec_validator.validate(spec)

    if not val["valid"]:
        try:
            self._memory.store(
                collection="lcca_failures",
                payload={
                    **spec.to_dict(),
                    "failure_reason": str(val["violations"]),
                },
            )
        except Exception:
            pass
        log.error("Spec non validable — violations: %s", val["violations"])
        return False

    try:
        self._memory.store(collection=collection, payload=spec.to_dict())
    except Exception:
        pass
    log.info("Spec stockée : %s (domain=%s, validated=%s)", spec.spec_id, spec.domain, spec.validated)
    return True
```

---

## 3. Mise à jour `mcp_server.py` — outil `generate_spec`

### 3.1 Outil `generate_spec` actuel vs V7.2

**Actuel** : retourne `spec_id, title, abstract, score, valid`.
**V7.2** : doit retourner aussi `domain, version, validated, complexity_score`.

```python
def _handle_generate_spec(self, args: dict) -> dict:
    intent = args.get("intent")
    domain = args.get("domain", "global")   # ← nouveau paramètre

    if not intent:
        raise ValueError("'intent' est requis")
    if domain not in VALID_DOMAINS:
        domain = "global"

    spec = self._spec_generator.generate(prompt=intent, domain=domain)

    return {
        "spec_id":          spec.spec_id,
        "domain":           spec.domain,
        "version":          spec.version,
        "title":            spec.title,
        "abstract":         spec.abstract,
        "complexity_score": spec.complexity_score,
        "validated":        spec.validated,
        "score":            spec.score,
    }
```

**Test MCP à mettre à jour** :
```python
def test_generate_spec_tool_success(self):
    ...
    assert "domain" in content
    assert "validated" in content
    assert "complexity_score" in content
```

---

## 4. Réécriture `test_spec_layer.py` V7.2 complète

### 4.1 Structure cible (hérite et étend les 23 tests Sprint 14)

```
TestSpecEntry (hérités + mis à jour)
  + test_make_spec_id_classmethod_from_body        [V7.2]
  + test_is_usable_requires_validated              [V7.2]
  + test_is_usable_requires_not_deprecated         [V7.2]
  + test_is_usable_requires_not_superseded         [V7.2]
  + test_domain_defaults_to_global                 [V7.2]
  + test_to_dict_includes_v72_fields               [V7.2]
  + test_from_dict_rétrocompat_sans_champs_v72     [V7.2]

TestRuleRegistryV72 (remplace TestRuleRegistry Sprint 14)
  test_registry_has_15_v72_rules
  test_rule1_detects_direct_write_after_patch
  test_rule3_detects_4_files_per_tx
  test_rule8_detects_hardcoded_python
  test_rule10_warns_json_utf8_sig
  test_clean_body_has_no_violations

TestSpecValidatorServiceV72 (remplace TestSpecValidatorService Sprint 14)
  test_validate_returns_dict
  test_validate_valid_spec
  test_validate_blocking_violation
  test_validate_sets_validated_on_spec
  test_llm_failure_is_silent
  test_format_notes_with_violations

TestCognitivePatterns (hérités — pas de régression)
  test_deep_reasoning_calls_generator
  test_spec_formatter_calls_generator
  test_spec_validator_pattern_calls_generator
  test_run_with_empty_context

TestSpecGeneratorServiceV72 (remplace TestSpecGeneratorService Sprint 14)
  test_generate_returns_spec_entry
  test_generate_sets_domain
  test_generate_sets_validated
  test_generate_sets_generated_by
  test_generate_spec_id_from_body_md              [V7.2 — MD5(body_md)]
  test_auto_fix_returns_spec_entry
  test_auto_fix_max_iter_respected
  test_compute_complexity_algorithm               [V7.2 — sections*5+règles*3]
```

**Total cible** : ~30 tests (vs 23 Sprint 14).

---

## 5. Conformité finale — Checklist spec V7.2 complète

### Section 8 de la spec originale (transposée)

- [ ] `SpecEntry.is_usable()` retourne False si non validée, dépréciée, ou superseded
- [ ] `SpecEntry.to_dict()` / `from_dict()` : roundtrip parfait (tous champs V7.2 + legacy utiles)
- [ ] `RULE_REGISTRY` V7.2 contient exactement 15 règles (10 V5 + 5 V7) sur `body_md`
- [ ] Chaque `RuleChecker.analyze()` retourne `[]` sur un `body_md` propre (zéro faux positif)
- [ ] `SpecValidatorService.validate()` : LLM failure → validation continue (pas de crash)
- [ ] `SpecValidatorService.validate()` retourne `dict` avec `valid, score, violations, validation_notes`
- [ ] `validate()` met à jour `spec.validated` et `spec.validation_notes`
- [ ] `SpecGeneratorService.generate()` prend `domain` en paramètre
- [ ] `SpecGeneratorService.generate()` renseigne `generated_by="hybrid"`
- [ ] `SpecGeneratorService.auto_fix()` boucle ≤ `SPEC_AUTO_FIX_MAX_ITERATIONS`
- [ ] `_compute_complexity()` : sections*5 + règles*3, plafonné à 100
- [ ] JSON stocké en `utf-8` (pas `utf-8-sig`) — vérifier `SpecEntry.save()`
- [ ] Fichiers `.py` en `utf-8-sig` (BOM Windows)
- [ ] `orchestrator._run_spec_layer()` : accès dict `val["valid"]` (plus `val.valid`)
- [ ] `mcp_server.generate_spec` retourne `domain, version, validated, complexity_score`
- [ ] `code legacy supprimé` : `validate_compat()`, `RULE_REGISTRY_LEGACY`, `ValidationResult`
- [ ] 517 tests V5/V7 précédents restent verts
- [ ] `test_spec_layer.py` V7.2 : ~30 tests PASSED

---

## 6. Plan de rollout sur 3 sessions

### Session Sprint 20
1. Lire skill 001 + 004
2. Écrire `core/spec_entry.py` V7.2
3. Mettre à jour `tests/test_spec_layer.py` (helper `_make_spec` + `TestSpecEntryV72`)
4. Mettre à jour `tests/test_spec_orchestrator.py` (fixtures `validated=True`)
5. `pytest tests/ -q` → cible 517 + 8 nouveaux = 525 passed

### Session Sprint 21
1. Lire skill 001 + 004
2. Écrire `core/spec_validator.py` V7.2 (RULE_REGISTRY + validate() dict + validate_compat())
3. Mettre à jour `core/cognitive_patterns.py` (nouveaux prompts)
4. Mettre à jour `core/spec_generator.py` (domain, _compute_complexity, validated)
5. Mettre à jour tests
6. `pytest tests/ -q` → cible 525 + 11 nouveaux = 536 passed

### Session Sprint 22
1. Lire skill 001 + 004
2. Supprimer code legacy (`validate_compat`, `RULE_REGISTRY_LEGACY`, `ValidationResult`)
3. Mettre à jour `core/orchestrator.py` (dict access)
4. Mettre à jour `core/mcp_server.py` (generate_spec domain)
5. Réécrire `test_spec_layer.py` V7.2 complet
6. `pytest tests/ -q` → cible 536+ passed, 0 failed
7. Mettre à jour skills (004 Sprint 22 terminé, 001 patterns, 003 arbo)

<!-- AI-READY | Sprint 22 Finalisation V7.2 | 2026-04-18 -->
