# LCCA — ANTI-PATTERNS & ERREURS CONNUES (v4)
# Lire si une session précédente a laissé des fichiers corrompus ou si des tests échouent.
# Fusion de 006-claude-deconne.md + ClaudeDesonneSkill.md

---

## ⚠️ RÈGLE FONDAMENTALE — LIRE AVANT TOUT

> **Le rythme "erreur pytest → correction rapide" désactive le jugement.**
> Chaque correction semblait simple. Aucune ne l'était vraiment.
> Le vrai coût : 6 allers-retours au lieu de 1 passe globale.

**Règle de session** : si une erreur pytest apparaît, la première réponse
n'est JAMAIS une correction. C'est un diagnostic complet.

**Workflow obligatoire avant toute correction** :
1. Identifier le TYPE d'erreur (T-01 à T-11 ci-dessous)
2. Scanner TOUS les fichiers de test pour le même pattern
3. Lister TOUTES les occurrences à corriger
4. Corriger TOUT en une seule passe (multi-edits dans la même réponse)
5. Ne PAS relancer pytest entre deux corrections partielles du même pattern

---

## ERREURS OUTILS FICHIERS

### ❌ O-01 — `write_file` sur fichier existant sans lecture préalable
**Symptôme** : le fichier est tronqué, du contenu disparaît.
**Règle** : fichier existant → `read_text_file` d'abord, puis `edit_file`.
`write_file` sur existant = INTERDIT sauf relecture complète dans la même session.

### ❌ O-02 — `str_replace` natif Claude sur fichiers Windows
**Symptôme** : `File not found` alors que le fichier existe.
**Cause** : str_replace natif = container Linux (`/home/claude`). PAS `D:\...`.
**Règle** : fichiers `D:\LLMCodeAgent\` → TOUJOURS `filesystem:edit_file` (MCP).

### ❌ O-03 — `bash_tool` pour accéder au disque Windows
**Symptôme** : `No such file or directory` même avec `/mnt/d/...`
**Règle** : bash_tool = container Linux isolé, 0 accès à `D:\`.
Lire/écrire `D:\LLMCodeAgent\` → UNIQUEMENT les outils MCP `filesystem:*`.

### ❌ O-04 — `edit_file` avec `oldText` contenant des caractères spéciaux
**Symptôme** : patch au mauvais endroit, syntaxe cassée.
**Règle** : `oldText` doit être **unique dans le fichier** (min 3 lignes de contexte).
Après chaque `edit_file` → relire les 20 lignes autour de la modification.
`oldText` de mémoire après modification du fichier = PÉRIMÉ.

### ❌ O-05 — Fichiers .bat : accents, encodage, et blocs imbriques
**Symptome 1** : `'cho' is not recognized`, `'f' is not recognized`
**Cause** : accents ou UTF-8 dans le .bat -- cmd.exe corrompt les caracteres non-ASCII.
**Regle** : ASCII pur dans tous les .bat, zero accent. `Creer` pas `Créer`. `chcp 65001` ne suffit pas.

**Symptome 2** : `': was unexpected at this time`
**Cause** : `if /i "!VAR!"=="val"` imbrique dans un bloc `if errorlevel 1 ( )` avec `enabledelayedexpansion`.
Le parser cmd ne gere pas les blocs parentheses imbriques avec expansion differee.
**Regle** : Dans un .bat avec `enabledelayedexpansion`, ne jamais imbriquer `if "!var!"` dans `if ... ( )` multi-lignes.
Refactorer avec des `goto` plats -- un label par branche, zero imbrication.

### ❌ O-06 — Déclarer un sprint TERMINÉ sans vérifier le résultat
**Règle** : Ordre obligatoire : (1) écrire le code, (2) relire les fichiers modifiés,
(3) SEULEMENT ALORS mettre à jour les skills.

### ❌ O-06 — Supposer que `create()` accepte les mêmes args qu'avant
**Symptôme** : `TypeError` en test car la signature a changé.
**Règle** : tout nouveau paramètre → valeur par défaut `= None`. Grep les tests après.

---

## ERREURS PYTEST — DÉSYNCHRONISATION CODE/TESTS

### ❌ T-01 — Valeur numérique pinnée dépassée par un sprint feature
**Symptôme** : `AssertionError: assert 12 == 9` ou `assert '7.2.0' == '7.1.0'`
**Cause** : sprint a ajouté des tools / changé une version sans mettre à jour les tests.
**Détection** : après chaque sprint qui ajoute des tools, scanner immédiatement :
```
grep -rn "== [0-9]" tests/test_mcp_*.py
```
**Correction** : lire `core/mcp_tools_schema.py` → vrai compte → corriger TOUTES les
occurrences dans `test_mcp_server.py` ET `test_mcp_integration.py` en une passe.

### ❌ T-02 — Mock HTTP non adapté au mode streaming
**Symptôme** : `AssertionError: assert 'def foo' in ''`
**Cause** : `OllamaClient` itère ligne par ligne. `mock_resp.read.return_value` = FAUX.
**Format correct** :
```python
lines = [
    json.dumps({"response": "def foo():\n    pass\n", "done": False}).encode(),
    json.dumps({"response": "", "done": True}).encode(),
]
mock_resp.__iter__ = lambda s: iter(lines)
```
**Piège** : `iter(lines)` s'épuise après le premier appel. Utiliser `side_effect` qui
reconstruit le mock à chaque appel `urlopen`.

### ❌ T-03 — Texte attendu dans un prompt non mis à jour
**Symptôme** : `AssertionError: assert 'Current function' in "...Current:\n\`\`\`python..."`
**Règle** : correction va dans le **prompt** (source de vérité), PAS dans le test.

### ❌ T-04 — Comportement `raises` incorrect par rapport au code réel
**Symptôme** : `Failed: DID NOT RAISE <class 'RuntimeError'>`
**Cause** : le code swallow silencieusement (`except: return ""`). Vérifier le chemin
réel dans le code source avant d'écrire `pytest.raises()`.

### ❌ T-05 — Dict de retour avec clés pinnées (search, tools)
**Symptôme** : `Left contains 1 more item: {'skills': []}`
**Cause** : sprint a ajouté une clé à `search()` mais le test compare l'égalité stricte.
**Correction** : ajouter toutes les clés présentes, ou tester par sous-ensemble.
**Détection** : `grep -rn "== {.solutions" tests/`

### ❌ T-06 — Race condition timeout_sec=0
**Symptôme** : `assert False is True` où `timed_out=False` alors qu'on attendait True.
**Cause** : `deadline = time.monotonic() + 0 ≈ now` → check peut être False (µs d'écart).
**Correction** : guard avant toute boucle :
```python
if self._timeout_sec <= 0:
    return OrchestratorResult(success=False, timed_out=True, ...)
```

### ❌ T-07 — Référence circulaire JSON dans les payloads de bus
**Symptôme** : `ValueError: Circular reference detected` dans `json.dumps(payload)`
**Cause** : `payload` contient `"contract"` qui contient `context` qui contient `payload`.
**Correction** : filtrer `"contract"` avant injection dans context :
```python
safe_payload = {k: v for k, v in payload.items() if k != "contract"}
contract.context["original_payload"] = safe_payload
```
**Agents concernés** : `ReviewerAgent.run_once()` ET `TesterAgent.run_once()`.

### ❌ T-08 — Clé absente dans la branche d'échec d'un payload
**Symptôme** : `AssertionError: assert 'clé' in msg.payload` sur le message envoyé à architect.
**Cause** : une clé enrichie (ex. `llm_review`, `llm_used`) ajoutée dans la branche succès (`syntax_ok=True`) a été oubliée dans la branche échec (`syntax_ok=False`).
**Règle** : toute clé présente dans le payload `tester` doit aussi être présente dans le payload `architect` — les deux branches doivent être symétriques sur les clés informationnelles.
**Correction** : ajouter les clés manquantes dans `reject_payload` :
```python
reject_payload = {
    ...,
    "llm_review": llm_review,
    "llm_used": llm_used,
}
```
**Fichier concerné** : `reviewer_agent.py` — branche `else` de `run_task()`.

### ❌ T-09 — Mock au mauvais niveau après REFACTO (agent vs sous-module)
**Symptôme** : test bloqué indéfiniment (>50 min), `KeyboardInterrupt` dans un fichier réseau (ex. `educator_github.py:60`).
**Cause** : après un REFACTO qui extrait la logique dans un sous-module (`_ingester`, `_curator`, `_gh`...), un test mocke la méthode wrapper sur `agent` (ex. `patch.object(agent, "_process_repo")`), mais `run_curation` appelle directement `agent._ingester.process_repo` — le mock ne capture pas l'appel réel.
**Règle** : après tout REFACTO qui extrait dans un sous-module, les mocks doivent cibler le sous-module, pas le wrapper :
```python
# ❌ Avant REFACTO (mocke le wrapper sur agent)
patch.object(agent, "_process_repo")
# ✅ Après REFACTO (mocke l'objet réel utilisé)
patch.object(agent._ingester, "process_repo")
```
**Fichiers concernés** : `test_ed_02.py` — `test_persist_called_after_wet_curation` et `test_persist_not_called_in_dry_run`.

### ❌ T-10 — Appels réseau accidentels bloquant la suite de tests (Windows)
**Symptôme** : `pytest` bloqué à X% pendant des dizaines de minutes, `KeyboardInterrupt` dans `urllib.request.urlopen`.
**Cause** : un test appelle `run_curation()` ou `_github_request()` sans mock. Sur Windows avec pare-feu, TCP peut attendre 5-10 min au lieu de lever `OSError` immédiatement.
**Solution permanente** : `tests/conftest.py` avec fixture `autouse` qui remplace `urllib.request.urlopen` par une version qui lève `OSError` immédiatement, ET patche `core.agents.educator_github._sleep` (binding local isolé) pour éviter les sleeps réels du retry loop. Les tests qui patchent `urlopen` eux-mêmes gardent leur comportement (patch local écrase le patch de la fixture).
**Attention T-10 bis** : ne jamais patcher `time.sleep` globalement depuis le conftest (patche le singleton C — affecte `time.perf_counter` indirectement via les tests de durée). Solution : dans le module source (`educator_github.py`), faire `from time import sleep as _sleep` puis utiliser `_sleep()` à la place de `time.sleep()`. Le conftest patche alors `core.agents.educator_github._sleep` — binding local isolé, sans impact sur `time.sleep` global.
**Fichier créé** : `tests/conftest.py`.

### ❌ T-11 — Mock au mauvais module après REFACTO (llm_generator → ollama_client)
**Symptôme** : `AttributeError: <module 'core.llm_generator'> does not have the attribute '_log_metric'` ou `AssertionError: 99 != 0` sur num_gpu.
**Cause** : REFACTO-11 a extrait `_log_metric` et `cfg_read` de `llm_generator.py` vers `ollama_client.py` / `llm_config.py`. Les tests qui patchaient `core.llm_generator._log_metric` ou `core.llm_generator._cfg_read` ne capturent plus rien.
**Règle** : toujours patcher **là où le symbole est utilisé** (binding local du module), pas là où il est défini.
```python
# ❌ Avant REFACTO (mock sur le module façade)
patch("core.llm_generator._log_metric")
patch("core.llm_generator._cfg_read")
# ✅ Après REFACTO-11 (mock sur le module qui utilise réellement le symbole)
patch("core.ollama_client._log_metric")
patch("core.ollama_client.cfg_read")
```
**Fichiers corrigés** : `test_v9_05.py` (10 occurrences), `test_v9_06.py` (2 occurrences), `test_v9_01_a.py` (1 occurrence).

---

### ❌ T-12 — auto_push = True détecté dans config AutoFix
**Symptôme** : `git push` exécuté automatiquement, code poussé sur remote sans validation humaine.
**Cause** : `cfg["auto_fix"]["auto_push"]` mis à `True` (interdit par invariant LCCA).
**Règle** : `auto_push = false` est un **invariant absolu**. `_git_commit()` ne doit jamais appeler `git push`.
`AutoFixEngine._git_commit()` possède un guard explicite qui log une erreur si `auto_push=True` — mais ne pousse quand même pas.
**Correction** : remettre `auto_push = false` dans `SelfImprove/config.toml`.

### ❌ T-13 — Rollback AutoFix non exécuté si `_run_tests` levée d'exception
**Symptôme** : fichier cible laissé dans état patché après échec post-patch.
**Cause** : `subprocess.TimeoutExpired` ou autre exception dans `_run_tests()` après écriture disque.
**Attention** : `_run_tests()` intercept les exceptions et retourne `False` — le rollback est bien déclenché via le check `if not self._run_tests(target_path)`. Ne pas modifier ce pattern.

### ❌ T-14 — `Path.rename()` échoue sur Windows si la cible existe déjà
**Symptôme** : `FileExistsError: [WinError 183] Cannot create a file when that file already exists` dans `atomic_write_json` lors du deuxième appel sur le même fichier.
**Cause** : `Path.rename()` appelle `os.rename()` qui est atomique sur Linux (remplace) mais échoue sur Windows si la destination existe. Touche tous les appels `atomic_write_json()` sur un fichier déjà existant.
**Correction** : remplacer `tmp.rename(path)` par `tmp.replace(path)` dans `si_utils.py`. `Path.replace()` est atomique et remplace la cible sur Windows ET Linux (PEP 428).
**Fichier corrigé** : `SelfImprove/si_utils.py` ligne 37.
**Règle** : toute écriture atomique `.tmp → cible` sur code multi-plateforme → **toujours `Path.replace()`**, jamais `Path.rename()`.

### ❌ T-15 — `psutil.pid_exists()` / `os.kill()` / `socket.gethostname()` bloquent sous pytest Windows
**Symptôme** : KeyboardInterrupt reproductible sur un test spécifique, `--full-trace` montre le blocage dans `psutil` ou `socket`.
**Cause** : ces appels système peuvent se bloquer sous Windows dans le contexte pytest, même sur le PID courant ou le hostname local.
**Règle source** : remplacer `socket.gethostname()` par `os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown"`. Ajouter un `_instance_suffix = uuid.uuid4().hex[:8]` si le nom de fichier temp dépend du PID (collision dans le même process).
**Règle tests** : dans le helper `_make_lock()` (ou équivalent), assigner directement `lock._verify_pid = lambda pid: True`. Les tests PID-mort overrident avec `lambda pid: False`. Ne jamais laisser `_verify_pid()` s’exécuter réellement dans les tests.

### ❌ T-18 — UnicodeEncodeError dans subprocess --help (Windows cp1252)
**Symptôme** : `UnicodeEncodeError: 'charmap' codec can't encode character` dans `argparse.print_help()`.
**Cause** : Windows utilise cp1252 pour stdout par défaut. `argparse` écrit les help strings vers `sys.stdout` — tout caractère hors cp1252 (`→`, `—` U+2014 selon contexte, etc.) lève l'erreur.
**Correction source** : help strings argparse en ASCII pur. Remplacer `→` par `->`, `é` par `e` dans les `help=` passés à `add_parser()` / `add_argument()`.
**Correction test** : passer `env={..."PYTHONIOENCODING": "utf-8"}` dans tout `subprocess.run()` qui invoque un script LCCA (double protection).
**Règle** : les docstrings et commentaires peuvent contenir des accents/flèches, mais les chaînes passées à argparse (`description`, `help=`, `prog=`) doivent être ASCII pur sur un projet Windows.

## CHECKLIST AVANT CHAQUE ÉCRITURE FICHIER

```
[ ] Fichier dans D:\LLMCodeAgent\ → filesystem:edit_file ou write_file (MCP uniquement)
[ ] Fichier existant → read_text_file d'abord, JAMAIS write_file direct
[ ] oldText tiré de la dernière lecture de cette session (pas de mémoire)
[ ] Unicité de oldText vérifiée dans le fichier
[ ] Après édition → relu les lignes modifiées avant de continuer
```

### ❌ T-16 — edit_batch silencieux : format incompatible "edits" vs "files"
**Symptôme** : le fichier n'est jamais créé, dossier cible vide. L'UI affiche le code LLM mais rien n'est écrit.
**Cause** : `coder_builder.build_patch()` produisait `{"edits": [...]}` mais `_tool_edit_batch` lit `args.get("files")` → `None` → `TypeError` swallowed dans `run_task()`.
**Fix** : renommer `"edits"` → `"files"` dans `build_patch()` + format `{"path", "action", "code"}` (FIX-EDITBATCH-01).
**Pattern** : toujours vérifier la correspondance du nom de champ entre le producteur (builder) et le consommateur (handler MCP).

### ❌ T-17 — safe_path rejette les paths absolus Windows fournis par l'UI
**Symptôme** : `PathSecurityError: Chemin absolu interdit` pour `D:\LLMCodeAgent\CodingTests\merge\merge.py`.
**Cause** : `safe_path()` rejetait tout path absolu. L'UI peut légitimement passer un path absolu dans `BASE_DIR`.
**Fix** : `safe_path()` accepte les paths absolus sous `BASE_DIR` (FIX-EDITBATCH-01). Les paths hors `BASE_DIR` lèvent toujours `PathSecurityError`.
**Règle** : `WORKSPACE_DIR` ≠ `BASE_DIR`. Le workspace MCP interne est `workspace/`, mais l'utilisateur peut cibler n'importe quel sous-dossier de `BASE_DIR`.

### ❌ T-19 — patch sur module façade quand l'import est tardif dans le handler
**Symptôme** : `AttributeError: <module 'core.mcp_handlers_projects'> does not have the attribute 'ProjectHealthChecker'`
**Cause** : le handler fait `from core.project_health_checker import ProjectHealthChecker` dans le corps de la méthode (import tardif). Le symbole n'est donc jamais un attribut du module handler — `patch("core.mcp_handlers_projects.ProjectHealthChecker")` échoue.
**Règle** : patcher là où la classe est **définie**, pas là où elle est importée en lazy :
```python
# ❌ import tardif dans le handler -> symbole absent du module
patch("core.mcp_handlers_projects.ProjectHealthChecker")
# ✅ patcher le module source
patch("core.project_health_checker.ProjectHealthChecker")
```
**Corollaire** : si on voulait patcher le binding local, il faudrait déplacer l'import au niveau module dans le handler. Mais patcher la source est plus simple et toujours correct.

```
[ ] Type d'erreur identifié (T-01 à T-19)
[ ] TOUS les fichiers de test scannés pour le même pattern
[ ] TOUTES les occurrences listées avant d'en corriger une seule
[ ] Correction en une seule passe (multi-edits dans la même réponse)
[ ] pytest non relancé entre deux corrections partielles du même pattern
```
