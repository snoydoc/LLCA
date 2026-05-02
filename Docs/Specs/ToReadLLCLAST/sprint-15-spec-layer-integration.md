# Sprint 15 — Spec Layer Integration
<!-- AI-READY | Architecture Spec Layer Integration | Version 7.1.0 | 2026-04-18 -->
<!-- Corrige et remplace addendum-21 sections 1, 3.3, 4, 6, 7, 8 -->
<!-- Prérequis : Sprint 14 terminé (SpecEntry, SpecGeneratorService, SpecValidatorService) -->

## Vue d'ensemble

Ce sprint intègre la Spec Layer dans le pipeline LCCA V7 existant :
- **Heuristique de complexité** `should_generate_spec()` — allégée (pas d'I/O dans le scoring)
- **Nouveaux outils MCP** `generate_spec` et `validate_spec`
- **Modification `LCCAV5Fusion.execute()`** — mode adaptatif
- **Collection mémoire `lcca_specs`** — intégration MemoryEngine
- **Promotion mémoire** — layer 2 → 1 → 0 (scheduler déclenché par usage_count)

---

## Périmètre Sprint 15

| Module | Fichier | Statut |
|--------|---------|--------|
| Heuristique | `core/spec_complexity.py` | 🆕 NOUVEAU |
| Intégration orchestrateur | `core/orchestrator.py` | ✏️ MODIFIÉ |
| Outils MCP | `core/mcp_server.py` | ✏️ MODIFIÉ (+2 tools) |
| Promotion mémoire | `core/spec_promoter.py` | 🆕 NOUVEAU |
| Tests heuristique | `tests/test_spec_complexity.py` | 🆕 NOUVEAU |
| Tests intégration | `tests/test_spec_orchestrator.py` | 🆕 NOUVEAU |

**Non inclus** : promotion layer_0 → identity (Sprint 16 TBD), documentation API.

---

## 1. Heuristique — `core/spec_complexity.py`

### 1.1 Corrections apportées vs spec originale

| Problème original | Correction |
|---|---|
| `should_generate_spec()` appelle `file_selector.select(intent)` → I/O lent dans heuristique | Score basé sur attributs déjà parsés dans `Intent` (pas d'I/O supplémentaire) |
| Fonction libre non injectable | Classe `SpecComplexityEstimator` avec `MemoryEngine` injecté |
| `memory_engine.has_spec_for_domain()` non définie | Méthode ajoutée à la spec de MemoryEngine : `search(collection, query, n)` suffit |

### 1.2 Algorithme corrigé

```python
# core/spec_complexity.py
# -*- coding: utf-8 -*-
"""
spec_complexity.py — LCCA V7
Sprint 15 — TASK-15-01

Heuristique adaptative : décide si une tâche nécessite une spec.
Aucun I/O disque dans le scoring — basé uniquement sur Intent déjà parsé.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.memory_engine import MemoryEngine

import config


_COMPLEX_KEYWORDS = frozenset({
    "rollback", "sandbox", "mcp", "memory-first",
    "transaction", "acid", "async", "multi-agent",
    "spec", "migration", "refactor", "architecture",
})


class SpecComplexityEstimator:
    """
    Calcule un score de complexité pour décider si une spec est nécessaire.

    Score 0-100 :
      0-40   → exécution directe pipeline V5
      41-59  → optionnel (mode interactif ou auto_spec=True)
      60-100 → generate_spec() obligatoire
    """

    def __init__(self, memory_engine: "MemoryEngine") -> None:
        self._mem = memory_engine

    def estimate(self, intent) -> tuple[bool, int]:
        """
        Retourne (need_spec: bool, score: int).
        intent : objet Intent (DSLParser output) — déjà parsé, pas d'I/O.
        """
        score = 0
        triggers = []

        # 1. Nombre de fichiers cibles (attribut Intent déjà calculé)
        n_files = len(getattr(intent, "target_files", []))
        if n_files >= 3:
            score += 30
            triggers.append("max_files_per_tx")

        # 2. Nouveau domaine (recherche mémoire — seule I/O autorisée)
        domain = _infer_domain(intent)
        existing_specs = self._mem.search(
            collection=config.SPEC_MEMORY_COLLECTION,
            query=domain,
            n=1,
        )
        if not existing_specs:
            score += 25
            triggers.append("new_domain")

        # 3. Mots-clés complexes dans le raw intent
        raw = getattr(intent, "raw", "").lower()
        if any(kw in raw for kw in _COMPLEX_KEYWORDS):
            score += 20
            triggers.append("complex_keywords")

        # 4. Historique d'échec similaire
        details = getattr(intent, "details", raw)
        past_failures = self._mem.search(
            collection="lcca_failures",
            query=details,
            n=3,
        )
        if past_failures:
            score += 15
            triggers.append("past_failure_similar")

        # 5. Longueur de la description (proxy complexité)
        if len(details) > 100:
            score += 10
            triggers.append("long_description")

        threshold = getattr(config, "SPEC_COMPLEXITY_THRESHOLD", 60)
        need_spec = score >= threshold
        return need_spec, min(100, score)


def _infer_domain(intent) -> str:
    """Infère le domaine depuis les mots-clés du raw intent."""
    raw = getattr(intent, "raw", "").lower()
    domain_map = {
        "transaction": ["transaction", "wal", "rollback", "acid"],
        "sandbox": ["sandbox", "docker", "subprocess", "exec"],
        "mcp": ["mcp", "json-rpc", "tool", "server"],
        "memory": ["memory", "chroma", "embedding", "vector"],
        "ast": ["ast", "libcst", "patcher", "parse"],
        "spec": ["spec", "specification", "addendum"],
        "orchestration": ["orchestrat", "pipeline", "execute", "workflow"],
    }
    for domain, keywords in domain_map.items():
        if any(kw in raw for kw in keywords):
            return domain
    return "global"
```

### 1.3 Règle de décision

| Score | Action |
|-------|--------|
| 0-40 | Exécution directe pipeline V5 — pas de spec |
| 41-59 | Optionnel — demander confirmation (mode interactif) ou auto si `ADAPTIVE_SPEC_ENABLED=True` |
| 60-100 | Obligatoire — `generate_spec()` avant toute modification |

---

## 2. Intégration orchestrateur — `core/orchestrator.py`

### 2.1 Modifications de `LCCAV5Fusion.execute()`

Ajout du paramètre `adaptive_spec: bool = True` et de la Phase 2 adaptative.

**Règle d'or** : la Phase 3 (pipeline V5 core) est **inchangée**. La Spec Layer est un préambule optionnel.

```python
# core/orchestrator.py — diff partiel (méthode execute)

def execute(
    self,
    command: str,
    auto_rollback: bool = True,
    adaptive_spec: bool = True,
) -> bool:

    # Phase 1 : Parsing (inchangé)
    intent = DSLParser().parse(command)

    # Phase 2 : Décision adaptative (NOUVEAU — conditionnel)
    if adaptive_spec and getattr(config, "ADAPTIVE_SPEC_ENABLED", False):
        spec_ok = self._run_spec_layer(intent)
        if not spec_ok:
            log.error("Spec Layer a bloqué l'exécution.")
            return False

    # Phase 3 : Exécution V5 standard (inchangée)
    return self._execute_core(intent, auto_rollback)


def _run_spec_layer(self, intent) -> bool:
    """
    Retourne True si le pipeline peut continuer.
    False si une spec invalide bloque l'exécution.
    """
    need_spec, complexity = self._complexity.estimate(intent)
    if not need_spec:
        return True

    # Recherche spec existante
    existing = self._mem.search(
        collection=config.SPEC_MEMORY_COLLECTION,
        query=intent.raw,
        n=3,
    )
    usable = [e for e in existing if SpecEntry.from_dict(e).is_usable()]
    if usable:
        spec = SpecEntry.from_dict(usable[0])
        spec.usage_count += 1
        self._mem.store(config.SPEC_MEMORY_COLLECTION, spec.to_dict())
        log.info("Spec réutilisée depuis mémoire : %s", spec.spec_id)
        return True

    # Génération
    domain = _infer_domain(intent)
    context = self._ctx_assembler.assemble(intent=intent.raw, wing="lcca", room="spec_generation")
    spec = self._generator.generate(intent=intent.raw, domain=domain, context=context)

    # Validation + auto-fix
    val = self._validator.validate(spec)
    if not val["valid"]:
        spec = self._generator.auto_fix(spec, val["violations"])
        val = self._validator.validate(spec)

    spec.validated = val["valid"]
    spec.validation_notes = val["validation_notes"]

    if not spec.validated:
        # Stockage en lcca_failures pour apprentissage
        self._mem.store("lcca_failures", {
            **spec.to_dict(),
            "failure_reason": val["validation_notes"],
        })
        log.error("Spec non validable après auto-fix — arrêt. Notes : %s", val["validation_notes"])
        return False

    # Spec valide → mémoire
    self._mem.store(config.SPEC_MEMORY_COLLECTION, spec.to_dict())
    log.info("Nouvelle spec générée et stockée : %s", spec.spec_id)
    return True
```

### 2.2 Nouvelles dépendances injectées dans `LCCAV5Fusion.__init__`

```python
# Ajouts dans __init__ (avec valeurs par défaut None → instanciation lazy)
self._complexity: Optional[SpecComplexityEstimator] = None
self._generator: Optional[SpecGeneratorService] = None
self._validator: Optional[SpecValidatorService] = None
```

**Règle DI** : si `adaptive_spec=True` et que `_complexity` est None, instanciation automatique dans `_run_spec_layer()` avec `LLMGenerator` existant.

---

## 3. Nouveaux outils MCP — `core/mcp_server.py`

### 3.1 Correction apportée

L'outil `generate_spec` dans la spec originale ne définissait pas le format exact du résultat MCP (champ `content`). Correction : format JSON-RPC 2.0 complet, cohérent avec les 7 tools existants.

### 3.2 Tool : `generate_spec`

```
Nom        : generate_spec
Rôle       : Générer une specification technique à partir d'un intent flou
Input      : intent (str), domain (str), context (str, optionnel)
Output     : spec_id, title, abstract, complexity_score, validated, validation_notes
Sécurité   : Pas d'accès disque direct — mémoire uniquement via MemoryEngine
Erreur     : -32002 si génération échoue, -32001 si domain interdit
```

```json
// Exemple input MCP
{
  "jsonrpc": "2.0",
  "id": 42,
  "method": "tools/call",
  "params": {
    "name": "generate_spec",
    "arguments": {
      "intent": "Ajouter un sandbox Docker avec fallback soft",
      "domain": "sandbox",
      "context": "Voir sprint 12 section SandboxEngine"
    }
  }
}

// Exemple output
{
  "jsonrpc": "2.0",
  "id": 42,
  "result": {
    "content": [{
      "type": "text",
      "text": "{\"spec_id\": \"a1b2c3d4e5f6\", \"title\": \"Spec Sandbox V7\", \"abstract\": \"...\", \"complexity_score\": 72, \"validated\": true, \"validation_notes\": \"Validation OK\"}"
    }]
  }
}
```

### 3.3 Tool : `validate_spec`

```
Nom        : validate_spec
Rôle       : Valider une spec existante (par spec_id) contre les règles V5+V7
Input      : spec_id (str), rules (list[str], optionnel — défaut : toutes)
Output     : valid (bool), score (float), violations (list), validation_notes (str)
Erreur     : -32602 si spec_id introuvable
```

```json
// Exemple input MCP
{
  "jsonrpc": "2.0",
  "id": 43,
  "method": "tools/call",
  "params": {
    "name": "validate_spec",
    "arguments": {
      "spec_id": "a1b2c3d4e5f6",
      "rules": ["rule_1_smartpatcher_str", "rule_8_sys_executable"]
    }
  }
}
```

### 3.4 Mise à jour `tools/list`

McpServer V7 passe de **7 tools à 9 tools** :

| # | Nom | Nouveau ? |
|---|-----|-----------|
| 1 | memory_search | — |
| 2 | memory_store | — |
| 3 | project_search | — |
| 4 | edit_batch | — |
| 5 | sandbox_run | — |
| 6 | evaluate_quality | — |
| 7 | analyze_error | — |
| 8 | **generate_spec** | ✅ Sprint 15 |
| 9 | **validate_spec** | ✅ Sprint 15 |

---

## 4. Promotion mémoire — `core/spec_promoter.py`

### 4.1 Corrections apportées

| Problème original | Correction |
|---|---|
| Scheduler non défini ("qui déclenche la promotion ?") | Promotion déclenchée lors de `memory_store` si `usage_count` dépasse seuil |
| Pas de rollback de promotion | `promote()` sauvegarde l'état avant promotion (champ `memory_layer` versionné) |
| Layer 0 "identity" non spécifié | Layer 0 = abstract injecté dans le `system_prompt` de `LLMGenerator` (via `config.SPEC_IDENTITY_ABSTRACTS`) |

### 4.2 Architecture

```python
# core/spec_promoter.py
# -*- coding: utf-8 -*-
"""
spec_promoter.py — LCCA V7
Sprint 15 — TASK-15-04

Gestion de la promotion mémoire des specs.
Layer 2 (scoped) → Layer 1 (compressed) → Layer 0 (identity)

Déclenchement : après chaque usage réussi dans un pipeline TX.
Rollback possible : spec conserve son ancien layer_X jusqu'à promotion validée.
"""
from __future__ import annotations

from core.spec_entry import SpecEntry
from core.cognitive_patterns import SpecFormatterPattern
import config

# Seuils de promotion
_LAYER_2_TO_1_THRESHOLD = 5   # 5 usages → compression abstract
_LAYER_1_TO_0_THRESHOLD = 10  # 10 usages → intégration identity


class SpecPromoter:
    """
    Évalue et exécute la promotion mémoire d'une SpecEntry.
    Injecté dans l'orchestrateur, appelé après chaque réutilisation TX.
    """

    def __init__(self, formatter: SpecFormatterPattern) -> None:
        self._formatter = formatter

    def maybe_promote(self, spec: SpecEntry) -> SpecEntry:
        """
        Tente de promouvoir la spec si les seuils sont atteints.
        Retourne la spec (potentiellement avec un nouveau memory_layer).
        """
        if spec.memory_layer == 2 and spec.usage_count >= _LAYER_2_TO_1_THRESHOLD:
            return self._promote_to_layer1(spec)
        if spec.memory_layer == 1 and spec.usage_count >= _LAYER_1_TO_0_THRESHOLD:
            return self._promote_to_layer0(spec)
        return spec

    def _promote_to_layer1(self, spec: SpecEntry) -> SpecEntry:
        """Layer 2 → 1 : enrichissement de l'abstract par le LLM."""
        enriched_abstract = self._formatter.run(
            prompt=f"Résume cette spec en 500 caractères max :\n{spec.body_md}",
            context="abstract_compression",
        )[:500]
        spec.abstract = enriched_abstract
        spec.memory_layer = 1
        return spec

    def _promote_to_layer0(self, spec: SpecEntry) -> SpecEntry:
        """Layer 1 → 0 : intégration dans config.SPEC_IDENTITY_ABSTRACTS."""
        identity_abstracts = getattr(config, "SPEC_IDENTITY_ABSTRACTS", [])
        if spec.abstract not in identity_abstracts:
            identity_abstracts.append(spec.abstract)
            config.SPEC_IDENTITY_ABSTRACTS = identity_abstracts
        spec.memory_layer = 0
        return spec
```

---

## 5. Tests requis

### 5.1 `tests/test_spec_complexity.py` (10 tests)

| Cas test | Couvre |
|----------|--------|
| `test_should_generate_spec_max_files` | 3 fichiers → score ≥ 60 → True |
| `test_should_not_generate_simple_rename` | Rename simple → score < 40 → False |
| `test_complex_keyword_adds_score` | "transaction" → +20 pts |
| `test_new_domain_adds_score` | Domaine absent de mémoire → +25 pts |
| `test_past_failure_adds_score` | Échec similaire → +15 pts |
| `test_score_capped_at_100` | Tous critères → score = 100 |
| `test_infer_domain_sandbox` | "docker" → "sandbox" |
| `test_infer_domain_mcp` | "json-rpc" → "mcp" |
| `test_infer_domain_fallback` | Intent inconnu → "global" |
| `test_memory_search_called_once` | Pas de double appel mémoire |

### 5.2 `tests/test_spec_orchestrator.py` (12 tests)

| Classe | Cas test | Couvre |
|--------|----------|--------|
| `TestAdaptiveSpec` | `test_simple_task_skips_spec_layer` | Score < 60 → bypass |
| `TestAdaptiveSpec` | `test_complex_task_generates_spec` | Score ≥ 60 → generate_spec appelé |
| `TestAdaptiveSpec` | `test_reuse_existing_validated_spec` | Hit mémoire → pas de génération |
| `TestAdaptiveSpec` | `test_adaptive_spec_blocks_invalid_spec` | Spec invalide après auto-fix → False |
| `TestAdaptiveSpec` | `test_invalid_spec_stored_in_lcca_failures` | Échec → lcca_failures |
| `TestAdaptiveSpec` | `test_valid_spec_stored_in_lcca_specs` | Succès → lcca_specs |
| `TestAdaptiveSpec` | `test_usage_count_incremented_on_reuse` | usage_count++ |
| `TestAdaptiveSpec` | `test_adaptive_spec_disabled_skips_layer` | `ADAPTIVE_SPEC_ENABLED=False` |
| `TestMcpSpecTools` | `test_generate_spec_tool_success` | JSON-RPC generate_spec |
| `TestMcpSpecTools` | `test_generate_spec_tool_invalid_domain` | Erreur -32602 |
| `TestMcpSpecTools` | `test_validate_spec_tool_known_id` | JSON-RPC validate_spec |
| `TestMcpSpecTools` | `test_validate_spec_tool_unknown_id` | Erreur -32602 |

### 5.3 `tests/test_spec_promoter.py` (6 tests)

| Cas test | Couvre |
|----------|--------|
| `test_no_promotion_below_threshold` | usage_count < 5 → layer inchangé |
| `test_promote_layer2_to_1_at_5_usages` | usage_count=5 → layer=1 |
| `test_promote_layer1_to_0_at_10_usages` | usage_count=10 → layer=0 |
| `test_layer0_abstract_in_config` | Promotion 0 → config.SPEC_IDENTITY_ABSTRACTS |
| `test_abstract_enriched_on_layer1_promotion` | LLM formatter appelé |
| `test_already_layer0_not_repromoted` | Idempotence |

---

## 6. Règles invariantes — Ajouts Sprint 15

| # | Règle | Justification |
|---|-------|---------------|
| 16 | `should_generate_spec()` ne fait aucun I/O disque | Performance : heuristique sur Intent déjà parsé |
| 17 | Les outils MCP `generate_spec` et `validate_spec` respectent JSON-RPC 2.0 | Cohérence protocole |
| 18 | La promotion layer_0 est idempotente | Pas de doublon dans `SPEC_IDENTITY_ABSTRACTS` |
| 19 | Un spec stockée dans `lcca_failures` ne peut pas être promu | Apprentissage par échec uniquement |

---

## 7. Nouvelle collection mémoire `lcca_specs`

### 7.1 Intégration MemoryEngine

Pas de modification de `MemoryEngine` : la collection `lcca_specs` utilise les mêmes méthodes `search()` / `store()` que les autres collections.

| Paramètre | Valeur |
|-----------|--------|
| Collection | `lcca_specs` |
| Seuil store | Toujours (validated=True ou False) |
| Seuil search | score ≥ 0.0 (pas de filtre MemoryEngine — filtrage applicatif via `is_usable()`) |
| Embedding sur | `abstract + domain + title` (concaténés) |
| Fichiers JSON | `palace/wings/lcca/rooms/specs/{spec_id}.json` — encodage `utf-8` |

### 7.2 Méthode `MemoryEngine.has_spec_for_domain()` — NON ajoutée

La spec originale appelait `memory_engine.has_spec_for_domain(domain)`. Cette méthode n'est pas ajoutée à `MemoryEngine` pour préserver l'interface existante. Le comportement équivalent est :

```python
existing = mem.search(collection="lcca_specs", query=domain, n=1)
has_spec = len(existing) > 0
```

---

## 8. Checklist validation Sprint 15

- [ ] `SpecComplexityEstimator.estimate()` : zéro I/O disque (seule mémoire autorisée)
- [ ] `LCCAV5Fusion.execute()` : Phase 3 inchangée (466 tests précédents verts)
- [ ] `_run_spec_layer()` : spec invalide → stockage `lcca_failures` → return False
- [ ] MCP `generate_spec` : format JSON-RPC 2.0 strict, cohérent avec 7 tools existants
- [ ] MCP `validate_spec` : erreur -32602 si spec_id inconnu
- [ ] `SpecPromoter.maybe_promote()` : idempotente si spec déjà layer=0
- [ ] `config.ADAPTIVE_SPEC_ENABLED = False` désactive entièrement la Spec Layer
- [ ] JSON `lcca_specs` en `utf-8` (pas de BOM)
- [ ] 466 + 23 (Sprint 14) tests précédents restent verts
- [ ] Nouveaux tests : 10 + 12 + 6 = **28 tests PASSED**

<!-- AI-READY | Sprint 15 Spec Layer Integration | Version 7.1.0 | 2026-04-18 -->
