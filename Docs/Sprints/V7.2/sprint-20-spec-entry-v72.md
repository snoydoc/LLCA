# Sprint 20 — Migration SpecEntry vers spec V7.2
<!-- AI-READY | Migration Spec Layer | Version 7.2.0 | 2026-04-18 -->

## Contexte

L'analyse comparative entre la spec V7.2 (`LLCA_V7_2.md`) et l'implémentation actuelle
(Sprints 14-19) révèle des **écarts majeurs dans `SpecEntry`** : 6 champs manquants,
une signature `make_spec_id()` différente, et une logique `is_usable()` incomplète.

Ce sprint migre `spec_entry.py` pour être conforme à la spec V7.2 tout en conservant
la rétrocompatibilité avec les 517 tests existants.

---

## Périmètre Sprint 20

| Module | Fichier | Type |
|--------|---------|------|
| Modèle de données | `core/spec_entry.py` | 🔄 MIGRATION |
| Tests spec entry | `tests/test_spec_layer.py` | 🔄 MISE À JOUR |
| Tests promoter | `tests/test_spec_promoter.py` | 🔄 MISE À JOUR |
| Tests orchestrateur spec | `tests/test_spec_orchestrator.py` | 🔄 MISE À JOUR |
| Config | `config.py` | 🔄 MISE À JOUR |

**Non inclus** : migration `spec_validator.py`, `spec_generator.py`, `cognitive_patterns.py` → Sprint 21.

---

## 1. Analyse des écarts `spec_entry.py`

### 1.1 Champs manquants (à ajouter)

| Champ | Type | Défaut | Description |
|-------|------|--------|-------------|
| `domain` | `str` | `"global"` | Parmi `VALID_DOMAINS` — domaine architectural |
| `version` | `str` | `"7.2.0"` | Version de la spec (ex: "7.2.0") |
| `complexity_score` | `int` | `0` | Score 0-100 (remplace `complexity` 1-10) |
| `generated_by` | `str` | `"manual"` | Parmi `VALID_GENERATED_BY` |
| `validated` | `bool` | `False` | True si spec a passé la validation (Règle 11) |
| `validation_notes` | `str` | `""` | Notes de validation formatées |
| `superseded_by` | `Optional[str]` | `None` | spec_id de la version suivante (Règle 13) |
| `deprecated` | `bool` | `False` | True si spec dépréciée |

### 1.2 Constantes à ajouter

```python
VALID_DOMAINS = frozenset({
    "transaction", "ast", "mcp", "sandbox",
    "memory", "spec", "orchestration", "global"
})

VALID_GENERATED_BY = frozenset({
    "deep_reasoning", "spec_formatter", "hybrid", "manual"
})
```

### 1.3 Changements `make_spec_id()`

**Spec V7.2** : `make_spec_id(body_md: str) -> str` — MD5 du corps complet.
**Actuel** : `make_spec_id(title, abstract)` — MD5 de title::abstract.

**Décision** : ajouter `SpecEntry.make_spec_id(body_md)` comme **classmethod** (spec V7.2),
conserver la fonction module-level `make_spec_id(title, abstract)` pour rétrocompat tests.

### 1.4 Changement `is_usable()`

**Spec V7.2** :
```python
def is_usable(self) -> bool:
    return self.validated and not self.deprecated and self.superseded_by is None
```

**Actuel** : `return self.score >= min_score and bool(self.body_md.strip())`

**Décision** : la logique V7.2 est plus correcte (Règle 11 — une spec non `validated`
ne doit jamais être réutilisée dans un pipeline TX). Migrer vers la logique V7.2,
mais garder `min_score` comme garde secondaire :

```python
def is_usable(self, min_score: float = 0.8) -> bool:
    return (
        self.validated
        and not self.deprecated
        and self.superseded_by is None
        and self.score >= min_score
    )
```

---

## 2. Implémentation cible `spec_entry.py`

```python
# -*- coding: utf-8-sig -*-
"""spec_entry.py — LCCA V7.2
Sprint 14 — Dataclass autonome initial.
Sprint 19 — memory_layer ajouté.
Sprint 20 — Migration V7.2 : domain, version, complexity_score, generated_by,
            validated, validation_notes, superseded_by, deprecated.
            make_spec_id() disponible comme classmethod (spec V7.2)
            ET comme fonction module-level pour rétrocompat.
            is_usable() migré vers logique V7.2 (validated + not deprecated + not superseded).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ── Constantes de domaine (spec V7.2) ────────────────────────────────────────

VALID_DOMAINS = frozenset({
    "transaction", "ast", "mcp", "sandbox",
    "memory", "spec", "orchestration", "global"
})

VALID_GENERATED_BY = frozenset({
    "deep_reasoning", "spec_formatter", "hybrid", "manual"
})


# ── Fonction module-level (rétrocompatibilité Sprints 14-19) ─────────────────

def make_spec_id(title: str, abstract: str) -> str:
    """Rétrocompat : MD5 de title::abstract (12 chars)."""
    raw = f"{title.strip()}::{abstract.strip()}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class SpecEntry:
    """
    Entrée de specification technique dans la collection lcca_specs.

    Champs identité :
        spec_id          : MD5 12 chars — SpecEntry.make_spec_id(body_md) V7.2
        domain           : Domaine architectural (VALID_DOMAINS)
        version          : Version de la spec (ex: "7.2.0")
        complexity_score : Score 0-100 (heuristique sections + règles)

    Champs contenu :
        title, body_md, abstract

    Champs provenance :
        generated_by     : VALID_GENERATED_BY
        validated        : True si spec a passé validation — Règle 11
        validation_notes : Texte formaté des violations

    Champs lifecycle :
        superseded_by    : spec_id successeur — Règle 13
        deprecated       : True si retirée
        usage_count      : Réutilisations TX

    Champs mémoire :
        memory_layer     : 2=scoped, 1=compressed, 0=identity (Sprint 19)

    Champs legacy (Sprints 14-19, conservés pour rétrocompat) :
        complexity, tags, created_at, promoted, score
    """
    # Champs requis V7.2
    spec_id:          str
    title:            str
    abstract:         str
    body_md:          str
    domain:           str        = "global"
    version:          str        = "7.2.0"
    complexity_score: int        = 0
    generated_by:     str        = "manual"
    validated:        bool       = False
    validation_notes: str        = ""
    superseded_by:    Optional[str] = None
    deprecated:       bool       = False

    # Champs partagés V7.2 + legacy
    usage_count:      int        = 0
    memory_layer:     int        = 2

    # Champs legacy (conservés — utilisés par tests existants)
    complexity:       int        = 1
    tags:             list[str]  = field(default_factory=list)
    created_at:       str        = field(default_factory=lambda: datetime.utcnow().isoformat())
    promoted:         bool       = False
    score:            float      = 0.0

    # ── API V7.2 ──────────────────────────────────────────────────────────────

    @classmethod
    def make_spec_id(cls, body_md: str) -> str:
        """V7.2 : MD5 du corps complet (12 chars)."""
        return hashlib.md5(body_md.encode("utf-8")).hexdigest()[:12]

    def is_usable(self, min_score: float = 0.8) -> bool:
        """
        True si la spec peut être utilisée dans un pipeline TX.
        Règle 11 : spec non validée → jamais réutilisée.
        Règle 13 : spec supersedée → jamais réutilisée.
        """
        return (
            self.validated
            and not self.deprecated
            and self.superseded_by is None
            and self.score >= min_score
        )

    # ── Sérialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            # V7.2
            "spec_id":          self.spec_id,
            "domain":           self.domain,
            "version":          self.version,
            "complexity_score": self.complexity_score,
            "title":            self.title,
            "body_md":          self.body_md,
            "abstract":         self.abstract,
            "generated_by":     self.generated_by,
            "validated":        self.validated,
            "validation_notes": self.validation_notes,
            "superseded_by":    self.superseded_by,
            "deprecated":       self.deprecated,
            "usage_count":      self.usage_count,
            "memory_layer":     self.memory_layer,
            # Legacy
            "complexity":       self.complexity,
            "tags":             self.tags,
            "created_at":       self.created_at,
            "promoted":         self.promoted,
            "score":            self.score,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpecEntry":
        return cls(
            spec_id          = data["spec_id"],
            title            = data["title"],
            abstract         = data["abstract"],
            body_md          = data["body_md"],
            domain           = data.get("domain", "global"),
            version          = data.get("version", "7.2.0"),
            complexity_score = int(data.get("complexity_score", 0)),
            generated_by     = data.get("generated_by", "manual"),
            validated        = bool(data.get("validated", False)),
            validation_notes = data.get("validation_notes", ""),
            superseded_by    = data.get("superseded_by"),
            deprecated       = bool(data.get("deprecated", False)),
            usage_count      = int(data.get("usage_count", 0)),
            memory_layer     = int(data.get("memory_layer", 2)),
            # Legacy
            complexity       = data.get("complexity", 1),
            tags             = data.get("tags", []),
            created_at       = data.get("created_at", datetime.utcnow().isoformat()),
            promoted         = bool(data.get("promoted", False)),
            score            = float(data.get("score", 0.0)),
        )

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.spec_id}.json"
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path: Path) -> "SpecEntry":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)
```

---

## 3. Impact sur les tests existants

### 3.1 `test_spec_layer.py` — Modifications requises

**`TestSpecEntry.test_is_usable`** : le test actuel vérifie `score >= 0.8` uniquement.
Après migration, `is_usable()` requiert aussi `validated=True`.

```python
# Avant (Sprint 14)
assert _make_spec(score=0.9).is_usable(min_score=0.8)   # passe car score OK
assert not _make_spec(score=0.5).is_usable(min_score=0.8)

# Après (Sprint 20)
assert _make_spec(score=0.9, validated=True).is_usable()   # doit passer validated=True
assert not _make_spec(score=0.9, validated=False).is_usable()  # non validée → inutilisable
assert not _make_spec(score=0.9, validated=True, deprecated=True).is_usable()
assert not _make_spec(score=0.9, validated=True, superseded_by="aabbccddeeff").is_usable()
```

**`TestSpecEntry.test_to_dict_from_dict_roundtrip`** : les nouveaux champs doivent
apparaître dans le dict sérialisé.

**`_make_spec()` helper** : ajouter `domain="global"`, `version="7.2.0"` aux defaults.

### 3.2 `test_spec_orchestrator.py` — Modifications requises

`_mock_memory(has_specs=True)` crée des `SpecEntry` sans `validated=True` → `is_usable()` retournera False.
Corriger : `SpecEntry(..., validated=True)` dans les fixtures.

### 3.3 Nouveaux tests à ajouter

```python
class TestSpecEntryV72:

    def test_make_spec_id_classmethod_from_body(self):
        """V7.2 : spec_id = MD5(body_md)."""
        body = "## Titre\nContenu de la spec."
        id1 = SpecEntry.make_spec_id(body)
        id2 = SpecEntry.make_spec_id(body)
        assert id1 == id2
        assert len(id1) == 12
        assert all(c in "0123456789abcdef" for c in id1)

    def test_is_usable_requires_validated(self):
        spec = _make_spec(score=0.9, validated=False)
        assert not spec.is_usable()

    def test_is_usable_requires_not_deprecated(self):
        spec = _make_spec(score=0.9, validated=True, deprecated=True)
        assert not spec.is_usable()

    def test_is_usable_requires_not_superseded(self):
        spec = _make_spec(score=0.9, validated=True, superseded_by="aabbccddeeff")
        assert not spec.is_usable()

    def test_is_usable_all_conditions_met(self):
        spec = _make_spec(score=0.9, validated=True, deprecated=False, superseded_by=None)
        assert spec.is_usable()

    def test_domain_defaults_to_global(self):
        spec = _make_spec()
        assert spec.domain == "global"

    def test_to_dict_includes_v72_fields(self):
        spec = _make_spec(domain="mcp", validated=True)
        d = spec.to_dict()
        assert "domain" in d
        assert "validated" in d
        assert "superseded_by" in d
        assert "deprecated" in d
        assert "generated_by" in d

    def test_from_dict_rétrocompat_sans_champs_v72(self):
        """Un dict sans champs V7.2 doit se désérialiser sans erreur (valeurs par défaut)."""
        d = {
            "spec_id": "a" * 12,
            "title": "Test",
            "abstract": "Abstract",
            "body_md": "## Corps\n" + "x" * 60,
        }
        spec = SpecEntry.from_dict(d)
        assert spec.domain == "global"
        assert spec.validated is False
        assert spec.superseded_by is None
```

---

## 4. Mise à jour `config.py`

```python
# === Spec Layer V7.2 ===
SPEC_DEFAULT_VERSION: str = "7.2.0"
SPEC_VALIDATOR_RULES: list[str] = [
    "rule_1_smartpatcher_str",
    "rule_2_ast_read_libcst_write",
    "rule_3_max_files",
    "rule_4_snapshot_md5",
    "rule_5_wal_append_only",
    "rule_6_llm_fallback",
    "rule_7_dependency_injection",
    "rule_8_sys_executable",
    "rule_9_module_level_imports",
    "rule_10_utf8_sig",
    "rule_11_no_code_if_invalid_spec",
    "rule_12_complexity_first",
    "rule_13_spec_versioned",
    "rule_14_invalid_spec_stops",
    "rule_15_patterns_configurable",
]
```

---

## 5. Checklist validation Sprint 20

- [ ] `SpecEntry` contient les 8 nouveaux champs V7.2 avec valeurs par défaut
- [ ] `VALID_DOMAINS` et `VALID_GENERATED_BY` définis comme frozenset
- [ ] `SpecEntry.make_spec_id(body_md)` fonctionne comme classmethod V7.2
- [ ] `make_spec_id(title, abstract)` conservée comme fonction module-level (rétrocompat)
- [ ] `is_usable()` vérifie `validated and not deprecated and superseded_by is None and score >= min_score`
- [ ] `to_dict()` / `from_dict()` : roundtrip parfait sur tous les champs V7.2
- [ ] `from_dict()` : rétrocompat sans champs V7.2 (valeurs par défaut)
- [ ] `test_spec_layer.py` : `_make_spec()` mise à jour, 8 nouveaux tests `TestSpecEntryV72`
- [ ] `test_spec_orchestrator.py` : fixtures corrigées avec `validated=True`
- [ ] 517 tests précédents restent verts
- [ ] Nouveaux tests : 8+ passed

<!-- AI-READY | Sprint 20 Migration SpecEntry V7.2 | 2026-04-18 -->
