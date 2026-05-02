# Sprint ED-03 — EducatorAgent : Qualité des données & politique de rareté
<!-- AI-READY | LCCA V9.1 | Sprint ED-03 | Priorité P2 | Effort 1j -->

## Objectif

Améliorer la qualité des données ingérées et mettre en place la politique de rareté :
- Filtre de popularité (stars GitHub ≥ 1000, configurable)
- Versionning des sources (hash de commit GitHub → réingestion si commit change)
- Marquage `source_type="external"` dans `SkillEntry` (ajout du champ)
- Politique de rareté : skills `external` non utilisés après N jours → `deprecated`
- Outil MCP `educator_status` : expose le dernier `CurationResult` via le bus

**Prérequis** : ED-01 TERMINÉ, ED-02 TERMINÉ.

## Contexte LCCA

- `SkillEntry` dans `core/skill_library.py` — ajouter champs `source_type` + `commit_hash`
  → respecter la règle LCCA : "Sérialisation dataclass : ajout champ → (1) dataclass (2) to_dict() (3) from_dict() (4) tests"
- `McpServer` dans `core/mcp_server.py` — 12 tools actuels → +1 `educator_status`
  → mise à jour immédiate des tests `test_tools_list_*`
- `config.py` — constante `EDUCATOR_SKILL_DEPRECATION_DAYS` déjà définie en ED-01

## Fichiers cibles

| # | Fichier | Opération | Lignes estimées |
|---|---------|-----------|-----------------|
| 1 | `core/skill_library.py` | PATCH — +2 champs SkillEntry + serialisation | +30 lignes |
| 2 | `core/agents/educator_agent.py` | PATCH — filtre stars + commit hash + dépréciation | +60 lignes |
| 3 | `core/mcp_server.py` | PATCH — tool `educator_status` | +15 lignes |
| 4 | `core/mcp_tools_schema.py` | PATCH — schéma `educator_status` | +12 lignes |
| 5 | `core/mcp_tool_handlers.py` | PATCH — handler `educator_status` | +20 lignes |
| 6 | `tests/test_educator_agent.py` | PATCH — 6 nouveaux tests | +60 lignes |
| 7 | `tests/test_mcp_server.py` | PATCH — compter 13 tools (était 12) | +3 lignes |
| 8 | `tests/test_skill_library.py` | PATCH — champs source_type/commit_hash | +10 lignes |

## Spécification détaillée

### 1. `core/skill_library.py` — PATCH SkillEntry

Ajouter les champs après les champs existants :

```python
@dataclass
class SkillEntry:
    skill_id    : str
    name        : str
    body        : str
    source      : str
    usage_count : int = 0
    # Champs V9.1 Educator — valeurs par défaut pour rétrocompat
    source_type : str = "internal"       # "internal" | "external"
    commit_hash : str = ""               # Hash du commit GitHub source

    def to_dict(self) -> dict:
        return {
            "skill_id"   : self.skill_id,
            "name"       : self.name,
            "body"       : self.body,
            "source"     : self.source,
            "usage_count": self.usage_count,
            "source_type": self.source_type,
            "commit_hash": self.commit_hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SkillEntry":
        return cls(
            skill_id    = d["skill_id"],
            name        = d["name"],
            body        = d["body"],
            source      = d.get("source", ""),
            usage_count = d.get("usage_count", 0),
            source_type = d.get("source_type", "internal"),   # rétrocompat
            commit_hash = d.get("commit_hash", ""),
        )
```

### 2. `core/agents/educator_agent.py` — PATCH (3 ajouts)

#### 2.1 Filtre de popularité (stars)

Ajouter méthode `_check_stars(owner, repo) -> bool` :

```python
def _check_stars(self, owner: str, repo: str) -> bool:
    """Vérifie que le repo a au moins EDUCATOR_STARS_THRESHOLD étoiles."""
    threshold = self._cfg.stars_threshold
    if threshold <= 0:
        return True  # Désactivé

    cache_key = f"stars_{owner}_{repo}"
    cached = self._cache_read(cache_key)
    if cached is not None:
        return cached.get("ok", False)

    data = self._github_request(
        f"https://api.github.com/repos/{owner}/{repo}"
    )
    if data is None:
        # Pas de données → accepter par défaut (ne pas bloquer sur erreur réseau)
        return True
    stars = data.get("stargazers_count", 0)
    ok = stars >= threshold
    self._cache_write(cache_key, {"ok": ok, "stars": stars})
    log.info("Repo %s/%s : %d étoiles — %s", owner, repo, stars, "OK" if ok else "rejeté")
    return ok
```

Appeler `_check_stars` dans `_process_repo_parallel` avant `_check_license` :
```python
if not self._check_stars(owner, repo):
    log.info("Pas assez d'étoiles — repo ignoré: %s/%s", owner, repo)
    return
if not self._check_license(owner, repo):
    ...
```

#### 2.2 Commit hash pour versionning

Ajouter méthode `_get_commit_hash(owner, repo) -> str` :

```python
def _get_commit_hash(self, owner: str, repo: str) -> str:
    """Retourne le SHA du dernier commit HEAD (pour versionning des sources)."""
    data = self._github_request(
        f"https://api.github.com/repos/{owner}/{repo}/commits/HEAD"
    )
    if data and "sha" in data:
        return data["sha"][:12]
    return ""
```

Dans `_ingest`, passer `commit_hash` à `SkillEntry` :
```python
entry = SkillEntry(
    skill_id    = skill_id,
    name        = name,
    body        = body,
    source      = source_label,
    source_type = "external",
    commit_hash = self._get_commit_hash(owner, repo),  # NEW
    usage_count = 0,
)
```

#### 2.3 Politique de rareté — méthode publique `deprecate_stale_skills`

```python
def deprecate_stale_skills(self, days: int | None = None) -> int:
    """
    Marque comme deprecated les skills externes non utilisés depuis N jours.

    Args:
        days: Nombre de jours sans usage. None → EDUCATOR_SKILL_DEPRECATION_DAYS.

    Returns:
        Nombre de skills marqués deprecated.
    """
    if self._skill_lib is None:
        return 0
    if days is None:
        days = getattr(config, "EDUCATOR_SKILL_DEPRECATION_DAYS", 30)

    import time
    cutoff = time.time() - days * 86400
    count = 0
    for entry in self._skill_lib.list_all():
        if entry.source_type != "external":
            continue
        if entry.usage_count > 0:
            continue
        last_used = getattr(entry, "last_used_at", 0) or 0
        if last_used < cutoff:
            self._skill_lib.deprecate(entry.skill_id)
            count += 1
    log.info("deprecate_stale_skills: %d skills marqués deprecated", count)
    return count
```

### 3. Tool MCP `educator_status`

#### 3.1 `core/mcp_tools_schema.py` — PATCH

```python
{
    "name": "educator_status",
    "description": "Retourne le statut de la dernière curation EducatorAgent (repos traités, skills ingérés, erreurs).",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
},
```

#### 3.2 `core/mcp_tool_handlers.py` — PATCH

```python
case "educator_status":
    agent = context.get("educator_agent")
    if agent is None:
        return {"status": "not_configured", "result": None}
    result = agent.last_result()
    if result is None:
        return {"status": "idle", "result": None}
    return {
        "status"          : "ok",
        "dry_run"         : result.dry_run,
        "repos_processed" : result.repos_processed,
        "files_fetched"   : result.files_fetched,
        "files_filtered"  : result.files_filtered,
        "skills_ingested" : result.skills_ingested,
        "context_ingested": result.context_ingested,
        "errors"          : result.errors,
    }
```

#### 3.3 `core/mcp_server.py` — PATCH

Ajouter `"educator_status"` à la liste des tools reconnus (matcher du dispatch).

### 4. Tests

#### `tests/test_educator_agent.py` — 6 nouveaux tests

```python
class TestStarsFilter:
    def setup_method(self):
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        cfg = EducatorConfig(
            dry_run=True, sleep_between_repos=0, fetch_timeout=5,
            cache_dir=self._tmpdir, stars_threshold=1000,
        )
        self.agent = EducatorAgent(cfg=cfg)

    def test_repo_above_threshold_accepted(self):
        with patch.object(self.agent, "_github_request",
                          return_value={"stargazers_count": 5000}):
            assert self.agent._check_stars("owner", "repo") is True

    def test_repo_below_threshold_rejected(self):
        with patch.object(self.agent, "_github_request",
                          return_value={"stargazers_count": 500}):
            assert self.agent._check_stars("owner", "repo") is False

    def test_threshold_zero_always_pass(self):
        self.agent._cfg.stars_threshold = 0
        assert self.agent._check_stars("owner", "repo") is True

    def test_api_failure_accepted_by_default(self):
        with patch.object(self.agent, "_github_request", return_value=None):
            assert self.agent._check_stars("owner", "repo") is True


class TestCommitHash:
    def setup_method(self):
        self.agent = _make_agent()

    def test_commit_hash_extracted(self):
        sha = "abc123def456" + "0" * 28
        with patch.object(self.agent, "_github_request", return_value={"sha": sha}):
            result = self.agent._get_commit_hash("owner", "repo")
        assert result == sha[:12]

    def test_commit_hash_empty_on_failure(self):
        with patch.object(self.agent, "_github_request", return_value=None):
            result = self.agent._get_commit_hash("owner", "repo")
        assert result == ""
```

#### `tests/test_mcp_server.py` — PATCH

Mettre à jour les assertions `len(tools) == 12` en `len(tools) == 13` :

```python
# Avant (ED-01 : 12 tools)
assert len(tools) == 12
# Après (ED-03 : +educator_status = 13 tools)
assert len(tools) == 13
```

⚠️ Scanner TOUS les fichiers de test pour ce pattern (règle T-01 ClaudeDesonneSkill) :
```
grep -rn "== 12" tests/test_mcp_*.py
grep -rn "== 12" tests/test_mcp_integration*.py
```

#### `tests/test_skill_library.py` — PATCH

```python
def test_skill_entry_source_type_default():
    entry = SkillEntry(skill_id="s1", name="foo", body="def foo(): pass", source="test")
    assert entry.source_type == "internal"
    assert entry.commit_hash == ""

def test_skill_entry_roundtrip_with_new_fields():
    entry = SkillEntry(
        skill_id="s2", name="bar", body="def bar(): pass",
        source="ext/repo/bar.py", source_type="external", commit_hash="abc123"
    )
    d = entry.to_dict()
    restored = SkillEntry.from_dict(d)
    assert restored.source_type == "external"
    assert restored.commit_hash == "abc123"

def test_skill_entry_from_dict_legacy_compat():
    # Dict sans source_type (format pré-ED-03)
    d = {"skill_id": "s3", "name": "baz", "body": "def baz(): pass", "source": "old"}
    entry = SkillEntry.from_dict(d)
    assert entry.source_type == "internal"
    assert entry.commit_hash == ""
```

## Critères d'acceptation

- [ ] `SkillEntry.from_dict` sans champs `source_type`/`commit_hash` → rétrocompat OK
- [ ] `SkillEntry.to_dict()` retourne les 7 champs (incl. `source_type`, `commit_hash`)
- [ ] `_check_stars` : repo avec 500 étoiles + threshold 1000 → `False`
- [ ] `_check_stars` : threshold 0 → toujours `True`
- [ ] `educator_status` retourne `"idle"` si `last_result()` est None
- [ ] `test_mcp_server.py` : `len(tools) == 13` (était 12)
- [ ] Tous les tests V8 + ED-01 + ED-02 toujours verts

## Protocole d'exécution

```
ÉTAPE 0 — Lecture préalable (obligatoire avant toute écriture)
1. filesystem:read_text_file core/skill_library.py — lire SkillEntry complet
2. filesystem:read_text_file core/mcp_tools_schema.py — lire liste tools
3. filesystem:read_text_file core/mcp_tool_handlers.py — lire dispatcher
4. filesystem:read_text_file tests/test_mcp_server.py — trouver les assertions "== 12"
5. filesystem:search_files tests/ "== 12" — scanner tous les fichiers de test

ÉTAPE 1 — Patches
6. filesystem:edit_file core/skill_library.py — +2 champs + to_dict/from_dict
7. filesystem:edit_file core/agents/educator_agent.py — 3 patchs (stars, commit, deprecate)
8. filesystem:edit_file core/mcp_tools_schema.py — +educator_status
9. filesystem:edit_file core/mcp_tool_handlers.py — +case educator_status
10. filesystem:edit_file core/mcp_server.py — +tool au dispatcher
11. filesystem:edit_file tests/test_mcp_server.py — 12 → 13 (TOUTES les occurrences)
12. filesystem:edit_file tests/test_educator_agent.py — +2 classes tests
13. filesystem:edit_file tests/test_skill_library.py — +3 tests

ÉTAPE 2 — Validation
14. bash: python -m pytest tests/test_educator_agent.py -v
15. bash: python -m pytest tests/test_mcp_server.py tests/test_skill_library.py -v
16. bash: python -m pytest tests/ -x -q
```

## Dépendances

Aucune nouvelle dépendance pip.

## Mise à jour skills requise (fin de sprint)

- **001** : "SkillEntry V9.1 — champs source_type/commit_hash + rétrocompat from_dict" + "McpServer 13 tools : +educator_status"
- **003** : SkillEntry mis à jour dans description
- **004** : sprint ED-03 marqué TERMINÉ
- **ClaudeDesonneSkill** si nouveau pattern d'erreur découvert
