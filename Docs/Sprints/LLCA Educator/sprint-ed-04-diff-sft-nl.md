# Sprint ED-04 — EducatorAgent : Mode diff & intégration pipeline SFT
<!-- AI-READY | LCCA V9.1 | Sprint ED-04 | Priorité P2/P3 | Effort 1j -->

## Objectif

Fermer la boucle entre l'EducatorAgent et les autres composants V9 :
- **Mode `--diff`** : rapport de ce qui serait ingéré sans écrire (dry-run enrichi avec comparaison)
- **Intégration Training** : les skills `source_type="external"` sont éligibles comme pairs SFT
- **Évaluation post-ingestion** : sandbox check rapide pour vérifier l'exécutabilité des skills
- **CLI LCCA** : commande `educator` dans `nl_parser.py` / `nl_intent.py` (pas de `main.py` standalone)
- **README** du module Educator dans `Docs/`

**Prérequis** : ED-01, ED-02, ED-03 TERMINÉS.

## Contexte LCCA

- `SandboxEngine` : `core/sandbox_engine.py` — `run(code, timeout) → SandboxResult`
- `NlParser` : `core/nl_parser.py` — patterns NL d'intention, ordre critique spécifiques avant généraux
- `NlIntent` : `core/nl_intent.py` — `NlIntent` enum + routing
- `LLMGenerator.generate()` : pipeline TX — ne pas appeler depuis l'Educator (pas de TX ici)
- `config.TRAINING_OUTPUT_DIR` : `"training_data"` — dossier SFT pairs
- Contrainte : pas de `main.py` standalone dans LCCA → la commande CLI est un intent NL

## Fichiers cibles

| # | Fichier | Opération | Lignes estimées |
|---|---------|-----------|-----------------|
| 1 | `core/agents/educator_agent.py` | PATCH — mode diff + sandbox check | +80 lignes |
| 2 | `core/nl_intent.py` | PATCH — intent `EDUCATOR_RUN` + `EDUCATOR_DIFF` | +6 lignes |
| 3 | `core/nl_parser.py` | PATCH — patterns NL français/anglais pour educator | +10 lignes |
| 4 | `core/nl_orchestrator.py` | PATCH — routing educator → EducatorAgent | +15 lignes |
| 5 | `core/agents/educator_agent.py` | PATCH — export SFT pairs | +40 lignes |
| 6 | `tests/test_educator_agent.py` | PATCH — 8 nouveaux tests | +80 lignes |
| 7 | `tests/test_nl_parser.py` | PATCH — patterns educator | +8 lignes |
| 8 | `Docs/EDUCATOR_README.md` | CREATE — documentation module | ~80 lignes |

## Spécification détaillée

### 1. Mode `diff` — `run_diff` dans `EducatorAgent`

```python
def run_diff(
    self,
    repos_filter: Optional[list[str]] = None,
    progress_cb : Optional[Callable[[str], None]] = None,
) -> dict:
    """
    Mode diff : simule une curation sans écriture et compare avec l'état actuel
    de la SkillLibrary pour identifier les nouveaux skills et les obsolètes.

    Returns:
        {
            "new_skills"       : list[str],  # skill_ids à ingérer
            "stale_skills"     : list[str],  # skill_ids non utilisés (ext)
            "repos_checked"    : int,
            "files_would_fetch": int,
            "errors"           : list[str],
        }
    """
    # Lancer une curation dry_run=True et collecter les skill_ids potentiels
    result = self.run_curation(
        dry_run=True, repos_filter=repos_filter, progress_cb=progress_cb
    )

    # Comparer avec SkillLibrary existante
    new_skills = []
    if self._skill_lib:
        for entry in getattr(self, "_last_dry_skill_ids", []):
            if self._skill_lib.get(entry) is None:
                new_skills.append(entry)

    stale_skills = []
    if self._skill_lib:
        for entry in self._skill_lib.list_all():
            if entry.source_type == "external" and entry.usage_count == 0:
                stale_skills.append(entry.skill_id)

    return {
        "new_skills"       : new_skills,
        "stale_skills"     : stale_skills,
        "repos_checked"    : result.repos_processed,
        "files_would_fetch": result.files_fetched,
        "errors"           : result.errors,
    }
```

**Note d'implémentation** : pendant `_ingest` en dry_run, collecter les `skill_id`
dans `self._last_dry_skill_ids: list[str]` (attribut d'instance protégé par `self._lock`).

### 2. Évaluation post-ingestion — `_sandbox_check`

```python
def _sandbox_check(self, body: str) -> bool:
    """
    Vérifie qu'un snippet de skill est exécutable en sandbox.
    Silencieux : si la sandbox n'est pas disponible, retourne True (ne pas bloquer).

    Returns:
        True si exécutable ou sandbox indisponible, False si SyntaxError/NameError critique.
    """
    try:
        from core.sandbox_engine import SandboxEngine
        sandbox = SandboxEngine(mode="soft")
        result = sandbox.run(body, timeout=5)
        # On accepte les NameError (dépendances externes manquantes)
        # On rejette uniquement les SyntaxError
        if result.error and "SyntaxError" in result.error:
            return False
        return True
    except Exception:
        return True  # Sandbox indisponible → accepter par défaut
```

Appeler `_sandbox_check` optionnellement dans `_ingest` — contrôlé par config :
```python
EDUCATOR_SANDBOX_CHECK = False   # Opt-in — lent mais utile en production
```

```python
# Dans _ingest, avant de créer SkillEntry :
if getattr(config, "EDUCATOR_SANDBOX_CHECK", False):
    if not self._sandbox_check(body):
        log.debug("Sandbox check failed pour skill %s — ignoré", name)
        continue
```

### 3. Export SFT pairs — `export_sft_pairs`

```python
def export_sft_pairs(
    self, output_dir: Optional[str] = None, min_score: int | None = None
) -> int:
    """
    Exporte les skills externes comme paires instruction/réponse pour le fine-tuning SFT.

    Format de sortie JSONL (compatible avec le collecteur V9-04 Training) :
        {"instruction": "Écris une fonction Python ...", "response": "<code>", "source": "external"}

    Args:
        output_dir: Dossier de sortie. None → config.TRAINING_OUTPUT_DIR / "educator"
        min_score: Score minimum des skills à exporter. None → EDUCATOR_MIN_SCORE

    Returns:
        Nombre de paires exportées.
    """
    import json
    from pathlib import Path
    from utils.safe_path import safe_path

    if self._skill_lib is None:
        log.warning("export_sft_pairs: SkillLibrary non configurée — aucune paire exportée.")
        return 0

    if output_dir is None:
        base = getattr(config, "TRAINING_OUTPUT_DIR", "training_data")
        output_dir = str(Path(base) / "educator")
    if min_score is None:
        min_score = getattr(config, "EDUCATOR_MIN_SCORE", 70)

    out_path = safe_path(output_dir, create=True) / "sft_pairs.jsonl"
    count = 0

    try:
        with out_path.open("w", encoding="utf-8") as f:
            for entry in self._skill_lib.list_all():
                if entry.source_type != "external":
                    continue
                # Évaluation légère du score
                try:
                    ev = self._evaluator.evaluate(entry.body)
                    if ev.score < min_score:
                        continue
                except Exception:
                    pass

                instruction = (
                    f"Écris une fonction Python nommée `{entry.name}` "
                    f"provenant du projet `{entry.source}`, "
                    f"bien documentée, avec type hints."
                )
                pair = {
                    "instruction": instruction,
                    "response"   : entry.body,
                    "source"     : "external",
                    "skill_id"   : entry.skill_id,
                    "repo"       : entry.source,
                }
                f.write(json.dumps(pair, ensure_ascii=False) + "\n")
                count += 1
        log.info("export_sft_pairs: %d paires exportées → %s", count, out_path)
    except Exception as exc:
        log.error("export_sft_pairs: échec export: %s", exc)

    return count
```

### 4. NL Intent & Parser — intégration commande educator

#### 4.1 `core/nl_intent.py` — PATCH

```python
class NlIntent(Enum):
    # ... intents existants ...
    EDUCATOR_RUN  = "educator_run"   # Lancer une curation
    EDUCATOR_DIFF = "educator_diff"  # Mode diff (rapport sans écriture)
```

#### 4.2 `core/nl_parser.py` — PATCH

Ajouter **avant** les patterns généraux (ordre critique) :

```python
# ─── Educator (spécifique — avant les patterns généraux) ─────────────────
_EDUCATOR_RUN_RE = re.compile(
    r"(?:lance|démarre|run|start|exécute)\s+(?:l[ae]\s+)?(?:curator|educator|curation)",
    re.IGNORECASE,
)
_EDUCATOR_DIFF_RE = re.compile(
    r"(?:diff|rapport|preview|aperçu)\s+(?:educator|curator|curation)",
    re.IGNORECASE,
)
```

Dans la méthode `parse()` :
```python
# Normaliser (NFD) avant test regex
src_normalized = unicodedata.normalize("NFD", text)
if _EDUCATOR_RUN_RE.search(src_normalized):
    return NlIntent.EDUCATOR_RUN, {}
if _EDUCATOR_DIFF_RE.search(src_normalized):
    return NlIntent.EDUCATOR_DIFF, {}
```

#### 4.3 `core/nl_orchestrator.py` — PATCH

```python
case NlIntent.EDUCATOR_RUN:
    educator = context.get("educator_agent")
    if educator is None:
        return NlResponse(text="EducatorAgent non configuré (EDUCATOR_ENABLED=False).")
    result = educator.run_task(
        _make_contract(intent=NlIntent.EDUCATOR_RUN, context={"dry_run": False})
    )
    return NlResponse(text=f"Curation lancée en arrière-plan (thread: {result.payload.get('thread')}).")

case NlIntent.EDUCATOR_DIFF:
    educator = context.get("educator_agent")
    if educator is None:
        return NlResponse(text="EducatorAgent non configuré.")
    diff = educator.run_diff()
    return NlResponse(
        text=(
            f"Diff Educator : {len(diff['new_skills'])} nouveaux skills potentiels, "
            f"{len(diff['stale_skills'])} skills obsolètes, "
            f"{diff['repos_checked']} repos vérifiés."
        ),
        data=diff,
    )
```

### 5. Tests ED-04

```python
class TestSandboxCheck:
    def setup_method(self):
        self.agent = _make_agent()

    def test_valid_syntax_passes(self):
        src = "def foo(x: int) -> int:\n    return x + 1\n"
        # Sandbox peut ne pas être disponible → doit retourner True dans les deux cas
        result = self.agent._sandbox_check(src)
        assert isinstance(result, bool)

    def test_syntax_error_rejected(self):
        src = "def foo(:\n    pass\n"
        with patch("core.sandbox_engine.SandboxEngine") as MockSandbox:
            instance = MockSandbox.return_value
            instance.run.return_value = MagicMock(error="SyntaxError: invalid syntax")
            result = self.agent._sandbox_check(src)
        assert result is False


class TestExportSftPairs:
    def setup_method(self):
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        self.agent = _make_agent()

    def test_no_skill_lib_returns_zero(self):
        self.agent._skill_lib = None
        assert self.agent.export_sft_pairs(output_dir=self._tmpdir) == 0

    def test_exports_external_only(self):
        from core.skill_library import SkillEntry
        internal = MagicMock(spec=SkillEntry)
        internal.source_type = "internal"
        external = MagicMock(spec=SkillEntry)
        external.source_type = "external"
        external.name = "foo"
        external.source = "owner/repo"
        external.body = "def foo() -> None:\n    '''doc.'''\n    pass\n"
        external.skill_id = "ext_abc_foo"

        lib = MagicMock()
        lib.list_all.return_value = [internal, external]
        self.agent._skill_lib = lib

        ev_mock = MagicMock()
        ev_mock.score = 80
        self.agent._evaluator.evaluate = MagicMock(return_value=ev_mock)

        count = self.agent.export_sft_pairs(output_dir=self._tmpdir)
        assert count == 1

        import json
        from pathlib import Path
        pairs_file = Path(self._tmpdir) / "sft_pairs.jsonl"
        assert pairs_file.exists()
        pair = json.loads(pairs_file.read_text(encoding="utf-8"))
        assert pair["source"] == "external"
        assert "foo" in pair["instruction"]


class TestNlPatterns:
    def test_educator_run_fr(self):
        from core.nl_parser import NlParser
        from core.nl_intent import NlIntent
        parser = NlParser()
        intent, _ = parser.parse("lance la curation")
        assert intent == NlIntent.EDUCATOR_RUN

    def test_educator_run_en(self):
        from core.nl_parser import NlParser
        from core.nl_intent import NlIntent
        parser = NlParser()
        intent, _ = parser.parse("start educator")
        assert intent == NlIntent.EDUCATOR_RUN

    def test_educator_diff(self):
        from core.nl_parser import NlParser
        from core.nl_intent import NlIntent
        parser = NlParser()
        intent, _ = parser.parse("diff curation")
        assert intent == NlIntent.EDUCATOR_DIFF
```

### 6. `Docs/EDUCATOR_README.md` — CREATE

```markdown
# LLCA-Educator — Agent de curation externe

## Rôle

EducatorAgent est un agent satellite V9.1 qui enrichit la mémoire de LCCA
en collectant du code exemplaire depuis une whitelist de repos GitHub open-source.

## Activation

```python
# config.py
EDUCATOR_ENABLED = True
EDUCATOR_DRY_RUN = False        # Autoriser l'écriture en mémoire
EDUCATOR_GITHUB_TOKEN = "ghp_…" # Recommandé pour dépasser 60 req/h
```

## Commandes NL

| Commande | Effet |
|---|---|
| "lance la curation" | Démarre la curation en arrière-plan |
| "diff curation" | Rapport de ce qui serait ingéré (sans écriture) |

## Outil MCP

```json
{ "name": "educator_status" }
```
Retourne le statut de la dernière curation.

## Whitelist

18 repos MIT/Apache/BSD avec ≥ 1000 étoiles (configurable via `EDUCATOR_STARS_THRESHOLD`).
Liste complète dans `core/agents/educator_agent.py : _WHITELIST`.

## Politique de licences

- Licences acceptées : MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause
- Refus explicite si GPL détecté dans le fichier, même sur un repo MIT
- Cache des résultats (TTL : `EDUCATOR_CACHE_TTL_HOURS`, défaut 24h)

## Politique de rareté

Les skills externes non utilisés après `EDUCATOR_SKILL_DEPRECATION_DAYS` (défaut 30 jours)
sont marqués `deprecated` automatiquement via `deprecate_stale_skills()`.

## Export SFT

```python
agent.export_sft_pairs()
# → training_data/educator/sft_pairs.jsonl
```

## Sprints

| Sprint | Contenu |
|---|---|
| ED-01 | Fondations + corrections P0 (run_task, dédup, filtres) |
| ED-02 | Robustesse (parallèle, cache, rate limit, encodage) |
| ED-03 | Qualité (stars, commit hash, rareté, tool MCP) |
| ED-04 | Mode diff, SFT, NL intent, sandbox check |
```

## Critères d'acceptation

- [ ] `run_diff()` retourne un dict avec clés `new_skills`, `stale_skills`, `repos_checked`
- [ ] `export_sft_pairs()` : ne compte pas les skills `source_type="internal"`
- [ ] `export_sft_pairs()` produit un fichier JSONL valide (1 JSON par ligne)
- [ ] NL "lance la curation" → `NlIntent.EDUCATOR_RUN`
- [ ] NL "diff curation" → `NlIntent.EDUCATOR_DIFF`
- [ ] NL patterns educator placés **avant** les patterns généraux dans `nl_parser.py`
- [ ] `_sandbox_check("def foo(:\n    pass")` → `False` (SyntaxError détecté)
- [ ] Tous les tests V8 + ED-01 + ED-02 + ED-03 toujours verts

## Protocole d'exécution

```
ÉTAPE 0 — Lecture préalable
1. filesystem:read_text_file core/nl_intent.py
2. filesystem:read_text_file core/nl_parser.py (head=80) — voir ordre des patterns
3. filesystem:read_text_file core/nl_orchestrator.py — voir dispatch existant
4. filesystem:read_text_file core/agents/educator_agent.py — version ED-03

ÉTAPE 1 — Patches
5. filesystem:edit_file core/nl_intent.py — +EDUCATOR_RUN, EDUCATOR_DIFF
6. filesystem:edit_file core/nl_parser.py — +patterns educator AVANT généraux
7. filesystem:edit_file core/nl_orchestrator.py — +2 cases
8. filesystem:edit_file core/agents/educator_agent.py — +run_diff +_sandbox_check +export_sft_pairs
9. filesystem:write_file Docs/EDUCATOR_README.md

ÉTAPE 2 — Tests
10. filesystem:read_text_file tests/test_educator_agent.py — version ED-03
11. filesystem:edit_file tests/test_educator_agent.py — +3 classes
12. filesystem:read_text_file tests/test_nl_parser.py — patterns existants
13. filesystem:edit_file tests/test_nl_parser.py — +3 tests educator

ÉTAPE 3 — Validation
14. bash: python -m pytest tests/test_educator_agent.py -v
15. bash: python -m pytest tests/test_nl_parser.py -v
16. bash: python -m pytest tests/ -x -q
```

## Dépendances

Aucune nouvelle dépendance pip — tout est stdlib ou modules LCCA existants.

## Mise à jour skills requise (fin de sprint)

- **001** :
  - Pattern "NlIntent.EDUCATOR_RUN / EDUCATOR_DIFF — ordre avant généraux dans nl_parser"
  - Pattern "EducatorAgent.export_sft_pairs() — JSONL Training output dir / educator/"
  - Pattern "EducatorAgent.run_diff() — dry_run enrichi + comparaison SkillLibrary"
- **002** : RAS
- **003** :
  - `Docs/EDUCATOR_README.md` ajouté
  - `core/nl_intent.py` : +EDUCATOR_RUN, +EDUCATOR_DIFF
- **004** : sprint ED-04 marqué TERMINÉ. Sprints ED-01→ED-04 = module Educator V9.1 complet.
