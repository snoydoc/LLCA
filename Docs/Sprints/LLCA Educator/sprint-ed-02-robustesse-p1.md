# Sprint ED-02 — EducatorAgent : Robustesse & Performance P1
<!-- AI-READY | LCCA V9.1 | Sprint ED-02 | Priorité P1 | Effort 1j -->

## Objectif

Rendre `EducatorAgent` robuste en production :
- Fetch parallèle avec `ThreadPoolExecutor` (max_workers=5) — 18 repos × 30 fichiers ≈ 540 requêtes actuellement séquentielles
- Détection de licence améliorée (fallback fichier README si API échoue)
- Cache local des licences et métadonnées (TTL 24h) pour éviter les appels répétés
- Gestion fine du rate limit GitHub (`X-RateLimit-Remaining`)
- Encodage robuste (utf-8 → latin-1 → cp1252 en séquence)

**Prérequis** : ED-01 TERMINÉ.

## Contexte LCCA

- `EducatorAgent` créé en ED-01 — ce sprint PATCH uniquement, aucun CREATE
- `config.py` déjà patché par ED-01 — ajouter uniquement `EDUCATOR_MAX_WORKERS`
- `safe_path()` dans `utils/safe_path.py` — à utiliser pour le cache disque local
- Convention : `.py` → `utf-8-sig` | JSON cache → `utf-8` sans BOM

## Fichiers cibles

| # | Fichier | Opération | Lignes estimées |
|---|---------|-----------|-----------------|
| 1 | `core/agents/educator_agent.py` | PATCH — fetch parallèle + cache + rate limit | +90 lignes |
| 2 | `config.py` | PATCH — `EDUCATOR_MAX_WORKERS` + `EDUCATOR_CACHE_DIR` | +3 lignes |
| 3 | `tests/test_educator_agent.py` | PATCH — 8 nouveaux tests | +80 lignes |

## Spécification détaillée

### 1. `config.py` — constantes additionnelles

```python
# Dans la section V9.1 — EDUCATOR AGENT (ajoutées après ED-01)
EDUCATOR_MAX_WORKERS          = 5     # ThreadPoolExecutor workers pour fetch parallèle
EDUCATOR_CACHE_DIR            = "memory/educator_cache"  # Chemin relatif au workspace
```

### 2. `core/agents/educator_agent.py` — PATCH

#### 2.1 Import `concurrent.futures` + `json` + `pathlib`

```python
import concurrent.futures
from pathlib import Path
```

#### 2.2 Cache local des licences

Ajouter dans `EducatorConfig` :
```python
max_workers  : int  = 5
cache_dir    : str  = "memory/educator_cache"
```

Ajouter méthode `_cache_path(key: str) -> Path` :
```python
def _cache_path(self, key: str) -> Path:
    """Retourne le chemin du fichier cache pour une clé donnée."""
    from utils.safe_path import safe_path
    cache_dir = safe_path(self._cfg.cache_dir, create=True)
    safe_key = key.replace("/", "_").replace(":", "_")
    return cache_dir / f"{safe_key}.json"

def _cache_read(self, key: str) -> Optional[dict]:
    """Lit le cache si non expiré (TTL = EDUCATOR_CACHE_TTL_HOURS)."""
    p = self._cache_path(key)
    if not p.exists():
        return None
    try:
        import json, time
        data = json.loads(p.read_text(encoding="utf-8"))
        age_h = (time.time() - data.get("_cached_at", 0)) / 3600
        if age_h > getattr(config, "EDUCATOR_CACHE_TTL_HOURS", 24):
            return None
        return data
    except Exception:
        return None

def _cache_write(self, key: str, value: dict) -> None:
    """Écrit dans le cache avec timestamp."""
    import json, time
    p = self._cache_path(key)
    try:
        payload = {**value, "_cached_at": time.time()}
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        log.debug("Cache write failed %s: %s", key, exc)
```

#### 2.3 `_check_license` avec cache

```python
def _check_license(self, owner: str, repo: str) -> bool:
    """Vérifie la licence avec cache TTL 24h."""
    cache_key = f"license_{owner}_{repo}"
    cached = self._cache_read(cache_key)
    if cached is not None:
        return cached.get("ok", False)

    # Logique P0 d'ED-01 (inchangée) ...
    ok = self._check_license_uncached(owner, repo)
    self._cache_write(cache_key, {"ok": ok})
    return ok

def _check_license_uncached(self, owner: str, repo: str) -> bool:
    """Logique de vérification licence sans cache (déplacée depuis ED-01)."""
    data = self._github_request(
        f"https://api.github.com/repos/{owner}/{repo}/license"
    )
    if data and "license" in data:
        spdx = (data["license"] or {}).get("spdx_id", "")
        ok = spdx in {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause"}
        return ok

    # Fallback fichier LICENSE
    for fname in ("LICENSE", "LICENSE.txt", "COPYING"):
        raw = self._fetch_raw(owner, repo, fname)
        if raw:
            upper = raw.upper()
            if "GPL" in upper:
                return False
            if any(k in upper for k in ("MIT LICENSE", "APACHE LICENSE", "BSD")):
                return True
    return False
```

#### 2.4 Fetch parallèle — `_process_repo` refactorisé

```python
def _process_repo_parallel(
    self, owner: str, repo: str, result: CurationResult, dry_run: bool
) -> None:
    """
    Version parallèle de _process_repo.
    Fetch les fichiers avec ThreadPoolExecutor(max_workers=EDUCATOR_MAX_WORKERS).
    """
    if not self._check_license(owner, repo):
        log.info("Licence non conforme — repo ignoré: %s/%s", owner, repo)
        return

    files = self._list_py_files(owner, repo)
    files = files[: self._cfg.max_files_per_repo]

    max_w = getattr(self._cfg, "max_workers", 5)
    skills_this_repo = 0

    def _fetch_and_filter(path: str) -> Optional[tuple[str, str]]:
        """Retourne (path, src) si le fichier passe le filtre, sinon None."""
        src = self._fetch_file(owner, repo, path)
        if src is None:
            return None
        if not self._filter(src):
            return None
        return (path, src)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_w) as pool:
        futures = {pool.submit(_fetch_and_filter, p): p for p in files}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res is None:
                continue
            path, src = res
            with self._lock:
                result.files_fetched  += 1
                result.files_filtered += 1
                if skills_this_repo < self._cfg.max_skills_per_repo:
                    added = self._ingest(src, owner, repo, path, dry_run)
                    result.skills_ingested  += added["skills"]
                    result.context_ingested += added["context"]
                    skills_this_repo += added["skills"]
```

#### 2.5 `run_curation` — utiliser `_process_repo_parallel`

Dans `run_curation`, remplacer l'appel `self._process_repo(...)` par
`self._process_repo_parallel(...)`.

#### 2.6 Rate limit — amélioration `_github_request`

Dans `_github_request`, extraire et logguer `X-RateLimit-Remaining` **avant** la pause :
```python
remaining = int(resp.headers.get("X-RateLimit-Remaining", "999"))
if remaining < 10:
    reset_at  = int(resp.headers.get("X-RateLimit-Reset", 0))
    wait_secs = max(5, reset_at - int(time.time()) + 5)
    log.warning(
        "GitHub rate limit quasi atteint (%d restants) — pause %ds",
        remaining, wait_secs,
    )
    time.sleep(wait_secs)
```

### 3. `tests/test_educator_agent.py` — PATCH (8 nouveaux tests)

Ajouter les classes suivantes dans le fichier existant :

```python
class TestCacheLicense:
    def setup_method(self):
        import tempfile, pathlib
        self._tmpdir = tempfile.mkdtemp()
        cfg = EducatorConfig(
            dry_run=True, sleep_between_repos=0, fetch_timeout=5,
            cache_dir=self._tmpdir,
        )
        self.agent = EducatorAgent(cfg=cfg)

    def test_cache_miss_calls_uncached(self):
        with patch.object(self.agent, "_check_license_uncached", return_value=True) as mock:
            result = self.agent._check_license("owner", "repo")
        assert result is True
        mock.assert_called_once()

    def test_cache_hit_skips_uncached(self):
        # Pré-remplir le cache
        self.agent._cache_write("license_owner_repo", {"ok": True})
        with patch.object(self.agent, "_check_license_uncached") as mock:
            result = self.agent._check_license("owner", "repo")
        assert result is True
        mock.assert_not_called()

    def test_cache_expired_calls_uncached(self):
        # Écrire un cache avec timestamp très ancien
        import time
        old_data = {"ok": True, "_cached_at": time.time() - 999999}
        p = self.agent._cache_path("license_owner_repo")
        import json
        p.write_text(json.dumps(old_data), encoding="utf-8")
        with patch.object(self.agent, "_check_license_uncached", return_value=False) as mock:
            result = self.agent._check_license("owner", "repo")
        assert result is False
        mock.assert_called_once()


class TestParallelFetch:
    def setup_method(self):
        self.agent = _make_agent()

    def test_process_repo_parallel_no_license(self):
        result = CurationResult()
        with patch.object(self.agent, "_check_license", return_value=False):
            self.agent._process_repo_parallel("owner", "repo", result, dry_run=True)
        assert result.files_fetched == 0

    def test_process_repo_parallel_files_fetched(self):
        result = CurationResult()
        sample_src = (
            "from pathlib import Path\n"
            'def foo(x: int) -> str:\n    """doc."""\n    return str(x)\n'
        )
        with patch.object(self.agent, "_check_license", return_value=True), \
             patch.object(self.agent, "_list_py_files", return_value=["a.py", "b.py"]), \
             patch.object(self.agent, "_fetch_file", return_value=sample_src), \
             patch.object(self.agent, "_filter", return_value=True), \
             patch.object(self.agent, "_ingest", return_value={"skills": 1, "context": 1}):
            self.agent._process_repo_parallel("owner", "repo", result, dry_run=True)
        assert result.files_fetched == 2
        assert result.skills_ingested == 2


class TestEncodingFallback:
    def setup_method(self):
        self.agent = _make_agent()

    def test_latin1_fallback(self):
        latin1_bytes = "def f():\n    pass  # café\n".encode("latin-1")
        mock_resp = MagicMock()
        mock_resp.read.return_value = latin1_bytes
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = self.agent._fetch_file("owner", "repo", "f.py")
        assert result is not None
        assert "def f" in result
```

## Critères d'acceptation

- [ ] `_check_license` ne rappelle pas l'API si le cache est valide (TTL non expiré)
- [ ] `_process_repo_parallel` utilise `ThreadPoolExecutor` avec `max_workers ≥ 1`
- [ ] Un repo à licence non conforme → `files_fetched == 0`
- [ ] Fetch d'un fichier encodé latin-1 → retourne une string Python valide
- [ ] `CurationResult` thread-safe : compteurs mis à jour sous `self._lock`
- [ ] Aucun timeout levé dans les tests (mocks)
- [ ] Tous les tests ED-01 toujours verts

## Protocole d'exécution

```
1. filesystem:read_text_file core/agents/educator_agent.py — lire version ED-01
2. filesystem:edit_file config.py — ajouter EDUCATOR_MAX_WORKERS + EDUCATOR_CACHE_DIR
3. filesystem:edit_file core/agents/educator_agent.py — 4 patchs ciblés :
   a. Imports concurrent.futures + Path
   b. Méthodes _cache_path/_cache_read/_cache_write
   c. _check_license avec cache + _check_license_uncached
   d. _process_repo_parallel + run_curation → appel parallel
4. filesystem:read_text_file tests/test_educator_agent.py — lire version ED-01
5. filesystem:edit_file tests/test_educator_agent.py — ajouter 3 classes de tests
6. bash: python -m pytest tests/test_educator_agent.py -v
7. bash: python -m pytest tests/ -x -q
```

## Dépendances

- `concurrent.futures` : stdlib Python 3.11 ✅
- `pathlib` : stdlib ✅
- Pas de nouvelle dépendance pip

## Mise à jour skills requise (fin de sprint)

- **001** : pattern "EducatorAgent ED-02 — fetch parallèle ThreadPool + cache licences TTL"
- **003** : mention `memory/educator_cache/` dans arborescence
- **004** : sprint ED-02 marqué TERMINÉ
