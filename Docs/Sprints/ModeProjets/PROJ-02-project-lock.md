# PROJ-02 — ProjectLock + Heartbeat %TEMP%
**Statut** : TODO
**Priorité** : P0
**Durée estimée** : 45 min
**Dépendances** : PROJ-01

---

## Objectif

Empêcher la corruption de `history.jsonl` sur ouverture simultanée de LLCA.
Stratégie : fichier `.lock` minimal dans le projet + payload heartbeat dans `%TEMP%`.
Le heartbeat ne s'écrit que dans `%TEMP%` pour éviter les scans Windows Defender sur le
répertoire projet.

---

## Nouveaux fichiers à créer

```
core/project_lock.py       # ProjectLock + ProjectAlreadyOpenError + heartbeat daemon
```

---

## Implémentation — core/project_lock.py

### Structure des fichiers

**`projects/{slug}/.llca/.lock`** — écrit une seule fois à l'ouverture (< 100 octets) :
```json
{ "temp_lock": "C:\\Users\\Adham\\AppData\\Local\\Temp\\.llca_lock_medibot_1234.json" }
```

**`%TEMP%/.llca_lock_{slug}_{pid}.json`** — mis à jour toutes les 30s par daemon :
```json
{
  "pid": 1234,
  "started_at": "2026-04-23T09:00:00Z",
  "last_heartbeat": "2026-04-23T09:05:30Z",
  "instance_id": "adham-desktop-01"
}
```

### Classe principale

```python
class ProjectLock:
    HEARTBEAT_INTERVAL = 30      # secondes
    STALE_THRESHOLD = 60         # secondes sans heartbeat → stale
    DAEMON_JOIN_TIMEOUT = 1.0    # secondes pour join() à la fermeture

    def acquire(self, slug: str) -> None:
        """
        Crée .lock dans projects/{slug}/.llca/ et fichier payload dans %TEMP%.
        Lance le thread daemon heartbeat.
        Lève ProjectAlreadyOpenError si lock valide existant.
        """

    def release(self, slug: str) -> None:
        """
        Arrête le thread heartbeat (join timeout=1.0s).
        Supprime fichier %TEMP/.llca_lock_{slug}_{pid}.json.
        Supprime projects/{slug}/.llca/.lock.
        Ordre : heartbeat stop → %TEMP% → .lock (le .lock en dernier).
        """

    def is_stale(self, slug: str) -> bool:
        """
        Lit .lock → charge fichier %TEMP.
        Stale si : fichier %TEMP absent OU last_heartbeat > STALE_THRESHOLD OU PID invalide.
        """

    def break_stale_lock(self, slug: str) -> None:
        """Supprime .lock et fichier %TEMP si stale. Appelé après confirmation utilisateur."""

    def _verify_pid(self, pid: int) -> bool:
        """
        Vérifie si le PID existe.
        Essaie psutil.pid_exists(pid) si psutil disponible.
        Sinon : os.kill(pid, 0) avec try/except ProcessLookupError.
        Fallback final : True (on se fie au heartbeat).
        """

    def _heartbeat_loop(self, temp_path: Path) -> None:
        """Thread daemon — met à jour last_heartbeat toutes les HEARTBEAT_INTERVAL secondes."""
```

### Exceptions

```python
class ProjectAlreadyOpenError(Exception):
    def __init__(self, slug: str, instance_id: str, pid: int):
        ...
```

---

## Tests requis (minimum 12)

```python
# tests/test_proj_02.py

def test_acquire_creates_lock_file(tmp_dir)
def test_acquire_creates_temp_payload(tmp_dir)
def test_acquire_raises_if_lock_exists_and_valid(tmp_dir)
def test_release_removes_lock_file(tmp_dir)
def test_release_removes_temp_file(tmp_dir)
def test_release_joins_heartbeat_thread(tmp_dir)
def test_is_stale_true_when_temp_file_absent(tmp_dir)
def test_is_stale_true_when_heartbeat_expired(tmp_dir)        # mock time
def test_is_stale_false_when_heartbeat_recent(tmp_dir)
def test_is_stale_true_when_pid_dead(tmp_dir)                 # mock _verify_pid
def test_break_stale_lock_removes_files(tmp_dir)
def test_heartbeat_updates_last_heartbeat(tmp_dir)            # mock time.sleep
def test_acquire_raises_project_already_open_error(tmp_dir)
def test_release_on_unacquired_lock_is_noop(tmp_dir)
```

---

## Points d'attention (analyse v3)

**Thread daemon join à la fermeture** : `project_close()` doit appeler
`heartbeat_thread.join(timeout=DAEMON_JOIN_TIMEOUT)` avant suppression des fichiers.
Sur Windows, un thread daemon non rejoint peut causer un `RuntimeError` au `sys.exit()`.

**Simulation crash dans les tests** : simuler un stale lock en supprimant directement
le fichier `%TEMP%` (pas le `.lock` projet). C'est le scénario réel d'un crash.

**`psutil` optionnel** : LLCA ne doit pas dépendre de `psutil`. Utiliser
`callable(getattr(psutil, "pid_exists", None))` avant appel. Fallback heartbeat si absent.

---

## Critères de validation

- [ ] `test_proj_02.py` : tous les tests passent
- [ ] Thread daemon join testé (pas de RuntimeError sur exit simulé)
- [ ] Stale lock détecté par suppression du fichier `%TEMP%` (simulation crash)
- [ ] `psutil` absent → fallback heartbeat fonctionne (mock import optionnel)
- [ ] `release()` sans `acquire()` préalable = no-op silencieux (pas d'exception)
