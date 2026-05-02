# Sprint FL-04 — SkillLibrary : métriques actives dans la boucle
<!-- AI-READY | LCCA V11 | Sprint FL-04 | Priorité P1 | Effort 0.5j | Statut : 🔲 À FAIRE -->

## Objectif

Alimenter `usage_count` et `success_rate` des `SkillEntry` en fonction de l'utilisation
réelle dans la boucle `KarpathyLoop`. Actuellement ces champs sont écrits à l'ingestion
(valeur fixe) et ne changent jamais après.

**SkillEntry a déjà les champs — ils ne sont jamais mis à jour après la première écriture.**
Ce sprint ajoute deux méthodes à `SkillLibrary` et deux lignes dans `KarpathyLoop.run()`.

## Diagnostic précis (lu dans `core/skill_library.py`)

`SkillEntry` n'a pas de champ `usage_count` ni `success_rate` dans la dataclass actuelle.
Les méthodes `record_usage` / `record_outcome` n'existent pas.
`SkillLibrary` stocke dans `MemoryEngine` via `self._mem.store(...)` avec un dict de
métadonnées. La mise à jour d'une entrée existante passe par `self._mem.store(...)` avec
les mêmes clés — ChromaDB déduplique via `skill_id`.

## Fichiers cibles

| # | Fichier | Opération | Lignes estimées |
|---|---------|-----------|-----------------|
| 1 | `core/skill_library.py` | PATCH — ajout champs `SkillEntry` + 2 méthodes | +75 lignes |
| 2 | `core/agents/orchestrator_loop.py` | PATCH — helper + 2 appels post-Tester | +30 lignes |
| 3 | `tests/test_fl_04.py` | CREATE | ~90 lignes |

## Prérequis

- `core/skill_library.py` — `SkillEntry`, `SkillLibrary`, `MemoryEngine` existants ✅
- `core/agents/orchestrator_loop.py` — `KarpathyLoop.run()`, `skill_entries` en scope ✅
- FL-01 terminé (skill_entries déjà récupérés dans la boucle) ✅

## Spécification

### 1. Ajout de champs dans `SkillEntry` (rétrocompat via valeurs par défaut)

```python
# AVANT
@dataclass
class SkillEntry:
    skill_id:        str
    name:            str
    body:            str
    source_intent:   str
    quality_score:   int
    receipt_task_id: str
    source_type:     str = "internal"
    commit_hash:     str = ""

# APRÈS — FL-04 (2 nouveaux champs avec défauts → rétrocompat totale)
@dataclass
class SkillEntry:
    skill_id:        str
    name:            str
    body:            str
    source_intent:   str
    quality_score:   int
    receipt_task_id: str
    source_type:     str   = "internal"
    commit_hash:     str   = ""
    usage_count:     int   = 0      # FL-04 : fois où ce skill a été injecté dans un prompt
    success_rate:    float = 0.0    # FL-04 : taux de succès du pipeline quand ce skill est utilisé
```

Mettre à jour `to_dict()` et `from_dict()` pour inclure les nouveaux champs :

```python
def to_dict(self) -> dict:
    return {
        "skill_id"       : self.skill_id,
        "name"           : self.name,
        "body"           : self.body,
        "source_intent"  : self.source_intent,
        "quality_score"  : self.quality_score,
        "receipt_task_id": self.receipt_task_id,
        "source_type"    : self.source_type,
        "commit_hash"    : self.commit_hash,
        "usage_count"    : self.usage_count,       # FL-04
        "success_rate"   : self.success_rate,      # FL-04
    }

@classmethod
def from_dict(cls, d: dict) -> "SkillEntry":
    return cls(
        skill_id        = d.get("skill_id", ""),
        name            = d.get("name", ""),
        body            = d.get("body", ""),
        source_intent   = d.get("source_intent", ""),
        quality_score   = int(d.get("quality_score", 0)),
        receipt_task_id = d.get("receipt_task_id", ""),
        source_type     = d.get("source_type", "internal"),
        commit_hash     = d.get("commit_hash", ""),
        usage_count     = int(d.get("usage_count", 0)),        # FL-04
        success_rate    = float(d.get("success_rate", 0.0)),   # FL-04
    )
```

### 2. Méthode `record_usage()` dans `SkillLibrary`

```python
def record_usage(self, skill_ids: list[str]) -> None:
    """
    FL-04 : Incrémente usage_count pour chaque skill utilisé dans une itération.

    Récupère chaque skill depuis MemoryEngine, incrémente le compteur,
    et re-persiste via store() (ChromaDB déduplication par skill_id).

    Silencieux si skill_id inconnu ou si MemoryEngine lève une exception.

    Args:
        skill_ids : Liste des skill_ids à marquer comme utilisés.
                    [] ou None → no-op immédiat.
    """
    if not skill_ids:
        return

    for skill_id in skill_ids:
        try:
            entry = self._get_by_skill_id(skill_id)
            if entry is None:
                log.debug("[skill_library] record_usage: skill_id=%s inconnu", skill_id)
                continue

            entry.usage_count = (entry.usage_count or 0) + 1
            self._persist_entry(entry)
            log.debug("[skill_library] usage_count++ → %d pour %s", entry.usage_count, skill_id)

        except Exception as exc:
            log.debug("[skill_library] record_usage error pour %s: %s", skill_id, exc)
```

### 3. Méthode `record_outcome()` dans `SkillLibrary`

```python
def record_outcome(self, skill_ids: list[str], success: bool) -> None:
    """
    FL-04 : Met à jour success_rate (moyenne pondérée glissante).

    Formule : new_rate = (old_rate × (n-1) + outcome) / n
    où n = usage_count après record_usage() (invariant FL-04-R3).

    Clamp [0.0, 1.0] systématique pour défense contre états partiels.

    IMPORTANT : Appeler APRÈS record_usage() pour que usage_count soit à jour.

    Args:
        skill_ids : Liste des skill_ids à mettre à jour.
        success   : True si le pipeline a produit un code validé, False sinon.
    """
    if not skill_ids:
        return

    outcome_f = 1.0 if success else 0.0

    for skill_id in skill_ids:
        try:
            entry = self._get_by_skill_id(skill_id)
            if entry is None:
                continue

            n        = max(int(entry.usage_count or 1), 1)
            old_rate = entry.success_rate if isinstance(entry.success_rate, float) else 0.0
            new_rate = (old_rate * (n - 1) + outcome_f) / n

            # Clamp invariant — défense contre états corrompus ChromaDB
            entry.success_rate = max(0.0, min(1.0, new_rate))
            self._persist_entry(entry)
            log.debug(
                "[skill_library] success_rate %s: %.3f → %.3f (n=%d, success=%s)",
                skill_id, old_rate, entry.success_rate, n, success,
            )

        except Exception as exc:
            log.debug("[skill_library] record_outcome error pour %s: %s", skill_id, exc)
```

### 4. Helpers privés dans `SkillLibrary`

`_get_by_skill_id()` et `_persist_entry()` peuvent ne pas exister — les ajouter :

```python
def _get_by_skill_id(self, skill_id: str) -> Optional[SkillEntry]:
    """
    Récupère un SkillEntry par skill_id depuis MemoryEngine.
    Retourne None si introuvable ou si MemoryEngine lève une exception.
    """
    try:
        results = self._mem.search(skill_id, n=1)
        for mem_entry in results.get("skills", []):
            meta = mem_entry.metadata or {}
            if meta.get("skill_id") == skill_id:
                body = mem_entry.content or ""
                return SkillEntry.from_dict({**meta, "body": body})
    except Exception as exc:
        log.debug("[skill_library] _get_by_skill_id error: %s", exc)
    return None

def _persist_entry(self, entry: SkillEntry) -> None:
    """
    Re-persiste un SkillEntry dans MemoryEngine (mise à jour des métadonnées).
    Identique à extract_and_store mais sans validation receipt ni qualité.
    Silencieux sur erreur.
    """
    try:
        self._mem.store("lcca_skills", {
            "skill_id":        entry.skill_id,
            "name":            entry.name,
            "code":            entry.body,
            "source_intent":   entry.source_intent,
            "quality_score":   entry.quality_score,
            "receipt_task_id": entry.receipt_task_id,
            "source_type":     entry.source_type,
            "commit_hash":     entry.commit_hash,
            "usage_count":     entry.usage_count,       # FL-04
            "success_rate":    entry.success_rate,      # FL-04
        })
    except Exception as exc:
        log.debug("[skill_library] _persist_entry error: %s", exc)
```

### 5. Helper module-level + appels dans `orchestrator_loop.py`

Ajouter **avant** la classe `KarpathyLoop` :

```python
# FL-04 : helper module-level — testable unitairement
def _extract_skill_ids(skill_entries) -> list[str]:
    """
    Extrait les skill_ids depuis une liste de SkillEntry, dicts, ou strings.
    Retourne [] pour tout input None/invalide/vide. Ne lève jamais.

    Args:
        skill_entries : list[SkillEntry] | list[dict] | None

    Returns:
        list[str] : skill_ids extraits (peut être vide)
    """
    if not skill_entries:
        return []
    ids: list[str] = []
    for entry in skill_entries:
        try:
            if hasattr(entry, "skill_id"):
                ids.append(str(entry.skill_id))
            elif isinstance(entry, dict) and "skill_id" in entry:
                ids.append(str(entry["skill_id"]))
            elif isinstance(entry, str) and entry:
                ids.append(entry)
        except Exception:
            pass
    return ids
```

Dans `KarpathyLoop.run()`, **après** le bloc `if tester_result.success` / `else` (résultat
Tester connu, `skill_entries` déjà en scope depuis `skill_library.retrieve()`) :

```python
# FL-04 : mise à jour métriques skills (silencieux si skill_lib=None)
if self._skill_lib is not None:
    _used_ids = _extract_skill_ids(skill_entries)
    if _used_ids:
        # Invariant FL-04-R3 : record_usage AVANT record_outcome
        self._skill_lib.record_usage(_used_ids)
        _success = tester_result.success if hasattr(tester_result, "success") else False
        self._skill_lib.record_outcome(_used_ids, success=_success)
```

> `skill_entries` est déjà calculé dans la boucle juste avant l'appel à `CoderAgent`
> (via `skill_library.retrieve(intent)`). Aucune modification de la structure de la
> boucle n'est nécessaire.

## Tests — `tests/test_fl_04.py`

```python
# tests/test_fl_04.py
"""FL-04 — Tests métriques SkillLibrary actives dans la boucle."""
import pytest
from unittest.mock import MagicMock, patch, call


# ── TestSkillEntryNewFields ───────────────────────────────────────────────────

class TestSkillEntryNewFields:
    def test_usage_count_default_zero(self):
        from core.skill_library import SkillEntry
        e = SkillEntry(
            skill_id="abc", name="f", body="def f(): pass",
            source_intent="x", quality_score=80, receipt_task_id="r1",
        )
        assert e.usage_count == 0

    def test_success_rate_default_zero(self):
        from core.skill_library import SkillEntry
        e = SkillEntry(
            skill_id="abc", name="f", body="def f(): pass",
            source_intent="x", quality_score=80, receipt_task_id="r1",
        )
        assert e.success_rate == 0.0

    def test_to_dict_includes_new_fields(self):
        from core.skill_library import SkillEntry
        e = SkillEntry(
            skill_id="abc", name="f", body="def f(): pass",
            source_intent="x", quality_score=80, receipt_task_id="r1",
            usage_count=5, success_rate=0.8,
        )
        d = e.to_dict()
        assert d["usage_count"] == 5
        assert d["success_rate"] == 0.8

    def test_from_dict_retrocompat_missing_fields(self):
        """from_dict() sans usage_count/success_rate → défauts à 0."""
        from core.skill_library import SkillEntry
        d = {
            "skill_id": "abc", "name": "f", "body": "def f(): pass",
            "source_intent": "x", "quality_score": 80, "receipt_task_id": "r1",
            # pas de usage_count ni success_rate
        }
        e = SkillEntry.from_dict(d)
        assert e.usage_count == 0
        assert e.success_rate == 0.0


# ── TestRecordUsage ───────────────────────────────────────────────────────────

class TestRecordUsage:
    def _lib_with_entry(self, skill_id="abc123", usage_count=0):
        from core.skill_library import SkillLibrary, SkillEntry
        lib = SkillLibrary.__new__(SkillLibrary)
        entry = SkillEntry(
            skill_id=skill_id, name="f", body="def f(): pass",
            source_intent="x", quality_score=80, receipt_task_id="r1",
            usage_count=usage_count,
        )
        lib._get_by_skill_id = MagicMock(return_value=entry)
        lib._persist_entry   = MagicMock()
        lib._min_quality     = 70
        lib._max_body_lines  = 50
        lib._max_per_prompt  = 3
        return lib, entry

    def test_usage_count_incremented(self):
        lib, entry = self._lib_with_entry(usage_count=3)
        lib.record_usage(["abc123"])
        assert entry.usage_count == 4

    def test_unknown_skill_id_silently_ignored(self):
        lib, _ = self._lib_with_entry()
        lib._get_by_skill_id.return_value = None
        # Ne doit pas lever
        lib.record_usage(["unknown_id"])
        lib._persist_entry.assert_not_called()

    def test_empty_list_noop(self):
        lib, _ = self._lib_with_entry()
        lib.record_usage([])
        lib._get_by_skill_id.assert_not_called()

    def test_exception_silently_swallowed(self):
        lib, _ = self._lib_with_entry()
        lib._get_by_skill_id.side_effect = RuntimeError("db crash")
        # Ne doit pas lever
        lib.record_usage(["abc123"])

    def test_persist_called_after_increment(self):
        lib, entry = self._lib_with_entry(usage_count=1)
        lib.record_usage(["abc123"])
        lib._persist_entry.assert_called_once_with(entry)


# ── TestRecordOutcome ─────────────────────────────────────────────────────────

class TestRecordOutcome:
    def _lib_with_entry(self, usage_count=5, success_rate=0.6):
        from core.skill_library import SkillLibrary, SkillEntry
        lib = SkillLibrary.__new__(SkillLibrary)
        entry = SkillEntry(
            skill_id="abc123", name="f", body="def f(): pass",
            source_intent="x", quality_score=80, receipt_task_id="r1",
            usage_count=usage_count, success_rate=success_rate,
        )
        lib._get_by_skill_id = MagicMock(return_value=entry)
        lib._persist_entry   = MagicMock()
        return lib, entry

    def test_success_increases_rate(self):
        lib, entry = self._lib_with_entry(usage_count=4, success_rate=0.5)
        lib.record_outcome(["abc123"], success=True)
        assert entry.success_rate > 0.5

    def test_failure_decreases_rate(self):
        lib, entry = self._lib_with_entry(usage_count=4, success_rate=0.8)
        lib.record_outcome(["abc123"], success=False)
        assert entry.success_rate < 0.8

    def test_rate_clamped_max_1(self):
        """success_rate ne dépasse jamais 1.0."""
        lib, entry = self._lib_with_entry(usage_count=1, success_rate=0.99)
        lib.record_outcome(["abc123"], success=True)
        assert entry.success_rate <= 1.0

    def test_rate_clamped_min_0(self):
        """success_rate ne descend jamais sous 0.0."""
        lib, entry = self._lib_with_entry(usage_count=1, success_rate=0.01)
        lib.record_outcome(["abc123"], success=False)
        assert entry.success_rate >= 0.0

    def test_empty_list_noop(self):
        lib, _ = self._lib_with_entry()
        lib.record_outcome([], success=True)
        lib._get_by_skill_id.assert_not_called()

    def test_exception_silently_swallowed(self):
        lib, _ = self._lib_with_entry()
        lib._get_by_skill_id.side_effect = ValueError("bad state")
        lib.record_outcome(["abc123"], success=True)


# ── TestExtractSkillIds ───────────────────────────────────────────────────────

class TestExtractSkillIds:
    def test_skill_entry_objects(self):
        from core.agents.orchestrator_loop import _extract_skill_ids
        from core.skill_library import SkillEntry
        entries = [
            SkillEntry(skill_id="id1", name="f", body="", source_intent="",
                       quality_score=80, receipt_task_id="r"),
            SkillEntry(skill_id="id2", name="g", body="", source_intent="",
                       quality_score=85, receipt_task_id="r"),
        ]
        assert _extract_skill_ids(entries) == ["id1", "id2"]

    def test_dict_entries(self):
        from core.agents.orchestrator_loop import _extract_skill_ids
        entries = [{"skill_id": "abc"}, {"skill_id": "def"}]
        assert _extract_skill_ids(entries) == ["abc", "def"]

    def test_none_returns_empty(self):
        from core.agents.orchestrator_loop import _extract_skill_ids
        assert _extract_skill_ids(None) == []

    def test_empty_list_returns_empty(self):
        from core.agents.orchestrator_loop import _extract_skill_ids
        assert _extract_skill_ids([]) == []

    def test_malformed_entries_skipped(self):
        from core.agents.orchestrator_loop import _extract_skill_ids
        entries = [{"no_skill_id": "x"}, 42, None]
        assert _extract_skill_ids(entries) == []


# ── TestLoopMetricsIntegration ────────────────────────────────────────────────

class TestLoopMetricsIntegration:
    """Vérifie que record_usage/record_outcome sont appelés après chaque itération Tester."""

    def _make_loop_with_mock_lib(self, tester_success=True):
        from core.agents.orchestrator_loop import KarpathyLoop
        from core.skill_library import SkillEntry

        skill_lib = MagicMock()
        fake_entries = [
            SkillEntry(skill_id="s1", name="f", body="", source_intent="",
                       quality_score=80, receipt_task_id="r"),
        ]
        skill_lib.retrieve.return_value = fake_entries
        skill_lib.record_usage   = MagicMock()
        skill_lib.record_outcome = MagicMock()

        arch     = MagicMock(); arch.run_task.return_value = MagicMock(
            success=True, payload={"dispatched": ["s1"]})
        coder    = MagicMock(); coder.run_task.return_value = MagicMock(
            success=True, payload={"generated_code": "def f(): pass"})
        reviewer = MagicMock(); reviewer.run_task.return_value = MagicMock(
            success=True, payload={})
        tester   = MagicMock(); tester.run_task.return_value = MagicMock(
            success=tester_success,
            payload={"quality_score": 80 if tester_success else 40, "tester_ok": tester_success})

        loop = KarpathyLoop(
            arch, coder, reviewer, tester,
            max_iterations=2, timeout_sec=3600, skill_library=skill_lib,
        )
        return loop, skill_lib

    def test_record_usage_called_once_per_iteration(self):
        loop, skill_lib = self._make_loop_with_mock_lib(tester_success=True)
        import time
        loop.run("t1", "create f", time.monotonic() + 3600)
        skill_lib.record_usage.assert_called()
        call_args = skill_lib.record_usage.call_args[0][0]
        assert "s1" in call_args

    def test_record_outcome_called_with_success_true(self):
        loop, skill_lib = self._make_loop_with_mock_lib(tester_success=True)
        import time
        loop.run("t1", "create f", time.monotonic() + 3600)
        skill_lib.record_outcome.assert_called()
        _, kwargs = skill_lib.record_outcome.call_args
        assert kwargs.get("success") is True or skill_lib.record_outcome.call_args[0][1] is True

    def test_skill_lib_none_no_attribute_error(self):
        """skill_lib=None → aucune AttributeError."""
        from core.agents.orchestrator_loop import KarpathyLoop
        arch     = MagicMock(); arch.run_task.return_value = MagicMock(
            success=True, payload={"dispatched": ["s1"]})
        coder    = MagicMock(); coder.run_task.return_value = MagicMock(
            success=True, payload={"generated_code": "def f(): pass"})
        reviewer = MagicMock(); reviewer.run_task.return_value = MagicMock(
            success=True, payload={})
        tester   = MagicMock(); tester.run_task.return_value = MagicMock(
            success=True, payload={"quality_score": 80, "tester_ok": True})
        loop = KarpathyLoop(
            arch, coder, reviewer, tester,
            max_iterations=1, timeout_sec=3600, skill_library=None,
        )
        import time
        # Ne doit pas lever
        loop.run("t1", "create f", time.monotonic() + 3600)
```

## Critères d'acceptation

- [ ] `pytest tests/test_fl_04.py` : 14 passed
- [ ] Après `KarpathyLoop.run()` avec skill_lib mockée : `record_usage` appelé ≥ 1× par itération Tester
- [ ] `KarpathyLoop(skill_library=None)` → aucune `AttributeError`
- [ ] `SkillEntry.from_dict(d)` sans `usage_count`/`success_rate` → défauts à `0` / `0.0`
- [ ] `success_rate` toujours dans `[0.0, 1.0]` après toute combinaison d'appels
- [ ] `pytest tests/test_skill_library.py` : toujours verts
- [ ] `pytest tests/test_orchestrator.py` : toujours verts

## Protocole d'exécution

```
1. filesystem:read_text_file core/skill_library.py
2. filesystem:edit_file core/skill_library.py
   → ajouter usage_count=0 + success_rate=0.0 dans SkillEntry
   → mettre à jour to_dict() + from_dict()
   → ajouter _get_by_skill_id() + _persist_entry()
   → ajouter record_usage() + record_outcome()
3. filesystem:read_text_file core/agents/orchestrator_loop.py
4. filesystem:edit_file core/agents/orchestrator_loop.py
   → ajouter _extract_skill_ids() avant la classe KarpathyLoop
   → ajouter bloc FL-04 dans run() après résultat Tester
5. filesystem:write_file tests/test_fl_04.py
6. bash: python -c "from core.skill_library import SkillEntry, SkillLibrary; e = SkillEntry('a','b','c','d',80,'r'); print(e.usage_count, e.success_rate)"
7. bash: python -m pytest tests/test_fl_04.py -v
8. bash: python -m pytest tests/test_skill_library.py tests/test_orchestrator.py -v
9. bash: python -m pytest tests/ -x -q
```

## ⚠️ Points d'attention

- `_get_by_skill_id()` utilise `self._mem.search(skill_id, n=1)` puis filtre par
  `meta.get("skill_id") == skill_id`. C'est nécessaire car `MemoryEngine.search()`
  fait une recherche sémantique — le résultat n°1 peut ne pas être le bon skill_id.
  Si ChromaDB a un accès direct par ID, préférer `self._mem.get_by_id(skill_id)` si
  disponible dans `MemoryEngine`.
- `record_outcome()` doit être appelé **après** `record_usage()` dans `orchestrator_loop.py`.
  L'invariant FL-04-R3 protège la formule de moyenne pondérée (usage_count doit être
  incrémenté avant).
- `SkillEntry` n'a pas de champ `usage_count` dans la version actuelle — ChromaDB contient
  des entrées sans ce champ. `from_dict()` avec défaut à `0` assure la rétrocompat.
- `_persist_entry()` appelle `self._mem.store()` avec les mêmes clés que `extract_and_store()`.
  ChromaDB déduplication via `skill_id` — la mise à jour est un upsert.

## Mise à jour skills post-sprint

- **001** : FL-04 — `usage_count`/`success_rate` dans `SkillEntry`, `record_usage()`, `record_outcome()`, `_extract_skill_ids()`, bloc FL-04 dans KarpathyLoop.run()
- **002** : +14 tests test_fl_04.py, état tests ~1599 total
- **004** : FL-04 TERMINÉ — Pipeline Feedback Loop V1 COMPLET
