# LCCA — MASTER SKILL (v11)
# LIRE EN PREMIER. Résumé exécutif pour toute session.

## RÔLE & RÈGLE ABSOLUE
Tu exécutes des **transactions atomiques** sur la codebase LCCA.
**JAMAIS de correction immédiate sur le premier fichier qui échoue.**
Lire → Diagnostiquer → Corriger une seule fois, correctement.

## WORKFLOW OBLIGATOIRE
1. Lire les 4 skills dans l'ordre
2. `filesystem:list_directory_with_sizes` sur le dossier cible
3. `filesystem:read_multiple_files` sur les fichiers concernés
4. Plan (≤ 3 fichiers/TX) → PATCH via `filesystem:edit_file` → relire → COMMIT

## WORKFLOW DEBUG PYTEST (NE PAS DÉROGER)
```
1. STOP — ne pas toucher au code
2. Identifier le TYPE d'erreur (voir 003-antipatterns.md : T-01 à T-11)
3. Lire le fichier SOURCE (pas juste le test)
4. Lire TOUS les tests susceptibles d'avoir le même pattern
5. Lister TOUTES les occurrences à corriger AVANT d'éditer
6. Corriger TOUT en une seule passe
7. Relire les fichiers modifiés
```
Un seul `pytest -x` entre deux corrections = échec du protocole.

## RÈGLES OUTILS FICHIERS (CRITIQUES)
- `write_file` ÉCRASE sans merge → fichier existant : **read_text_file → edit_file**
- `str_replace` natif Claude = container Linux uniquement. Sur `D:\...` → **filesystem:edit_file**
- `bash_tool` = 0 accès disque Windows. Jamais sur `D:\LLMCodeAgent\`
- Après tout `edit_file` → relire les lignes modifiées avant de continuer
- `oldText` = copié depuis la dernière lecture de la session. Jamais de mémoire

## PROTOCOLE TRANSACTIONNEL
SNAPSHOT → WAL → PATCH (libcst) → VERIFY (compile()) → COMMIT/ROLLBACK
- ❌ `file.write()` direct sans snapshot
- ❌ regex pour modifier du code Python
- ❌ `"python"` hardcodé → toujours `sys.executable`
- ❌ op disque MCP sans `safe_path()` en amont
- ❌ Spec non validée → jamais de génération de code

## RÈGLES INVARIANTES — CODE PYTHON
- `libcst` pour MODIFICATIONS, `ast` pour INDEXATION
- `SmartPatcher.apply_patch()` retourne `str`, n'écrit jamais sur disque
- `Path` (pathlib) toujours | Classes `PascalCase` | fonctions `snake_case`
- JSON : `utf-8` (sans BOM) | `.py` : `utf-8-sig` (BOM Windows)
- `.ps1` : ASCII pur, zéro accent
- `log.info("msg %s", var)` jamais `log.info(f"msg {var}")`
- `_lock = threading.Lock()` → attribut d'**instance** (jamais de classe)
- SQLite `:memory:` → connexion persistante unique `self._conn` + `check_same_thread=False`

## RÈGLES INVARIANTES — ARCHITECTURE
- `Orchestrator` = alias legacy vers `LCCAV5Fusion`
- `callable(getattr(obj, "method", None))` avant appel dynamique
- Sérialisation dataclass : (1) dataclass (2) to_dict() (3) from_dict() (4) tests
- Import tardif dans `__init__` pour éviter imports circulaires
- Tout nouveau paramètre `create()` / `__init__()` → valeur par défaut `= None`

## RÈGLES INVARIANTES — EDUCATOR / WHITELIST
- Source de vérité whitelist : `educator_whitelist.json` (PAS educator_agent.py)
- `educator_whitelist.py` expose : WHITELIST, load_whitelist(), save_whitelist(), load_skip_set()
- `list_py_files()` lit `.endswith((".py", ".pyi"))` — stubs typeshed inclus
- Ajout repo : éditer le JSON uniquement, pas de code Python à toucher
- `skip_license_check: true` dans le JSON pour les repos à licence non-SPDX standard

## RÈGLES INVARIANTES — LLM / OLLAMA
- `generate(op, intent, context)` → `GenerationResult` — Pipeline TX uniquement
- `generate_text(system, user)` → `str` — CognitivePatterns uniquement (pas de cache)
- Toujours passer `"options": {"num_predict": self.max_tokens}` à Ollama
- `OLLAMA_TIMEOUT = None` | `SPEC_TIMEOUT = None` → NE JAMAIS mettre une valeur entière
- `AGENT_PIPELINE_TIMEOUT = 3600` (1h)

## RÈGLES INVARIANTES — MCP / McpServer
- JSON-RPC 2.0 stdio : champs `jsonrpc`, `id`, `method`, `params`
- Notifications (sans `id`) → retourner None, jamais écrire de réponse
- Logs sur `sys.stderr`, JSON-RPC sur `sys.stdout`
- Quand on ajoute des tools MCP → mettre à jour IMMÉDIATEMENT les tests `test_tools_list_*`
- 13 tools actuels (inclut `educator_status` ajouté ED-03)

## RÈGLES INVARIANTES — SPEC LAYER V7.2
- `SpecEntry.make_spec_id(body_md)` : classmethod (MD5 du corps)
- `is_usable()` : validated AND NOT deprecated AND superseded_by is None AND score >= min_score
- `validate()` retourne **dict** : `{valid, score, violations, validation_notes}`
- `SpecDirectPattern` : 1 appel LLM (~120s) vs pipeline 2 appels (~360s)

## RÈGLES INVARIANTES — TESTS
- `pytest.skip()` dans le corps pour fixtures conditionnelles (Pytest 9+)
- `ChromaDB` : `skipif(sys.version_info >= (3, 14), ...)`
- `_make_side_effect()` : rejoue le dernier élément si liste épuisée
- Tests d'intégration mockant le LLM → `config.ADAPTIVE_SPEC_ENABLED = False`

## RÈGLES INVARIANTES — UI ELECTRON/REACT
- Toute nouvelle méthode IPC = 3 fichiers : `main.ts` + `preload.ts` + composant
- `TOOL_TIMEOUTS: Record<string, number>` module-level dans `mcp-bridge.ts`
- Patterns NL français : `normalize('NFD')` avant tout test regex
- Patterns NL : ordre critique — spécifiques AVANT généraux
- `themes.css` : importé AVANT `globals.css`
- `msg.isStreaming` positionné à `true` dès `appendMessage()` avant tout token

## RÈGLES INVARIANTES — AUTOFIX ENGINE
- `AutoFixEngine.run()` → statut `'success' | 'failed' | 'skipped'`
- `SmartPatcher.apply_patch()` retourne `str` — **AutoFixEngine écrit disque** via `target_path.write_text()`
- Rollback immédiat si tests non verts après patch : `target_path.write_text(original_content)`
- Coverage check : `pytest --cov` → `coverage.json` → `files[path].summary.line_rate` (float 0-1)
- `coverage.json` absent ou fichier non référencé → mode dégradé silencieux (laisse passer)
- `auto_push = false` invariant absolu — `_git_commit()` ne fait jamais `git push`
- Commit sur branche `auto-fix/<pattern>-YYYYMMDD-HHMMSS` uniquement, jamais sur main
- 8 guards en séquence : flag → mode≥2 → whitelist → allowed_files → coverage → tests_avant → diff≤5 → tests_après
- Pattern `coroutine_never_awaited` : transformer add_await STUB (non implémenté en V10.5)
- Pattern `missing_import` : fallback template string si libcst absent (doublon vérifié avant insertion)

## AGENTS — RÈGLES SPÉCIFIQUES

### Pipeline (KarpathyLoop)
- Architect → Coder → Reviewer → Tester (orchestrator_loop.py)
- `LoopResult.timed_out=True` → `OrchestratorResult.timed_out=True`
- `timeout_sec <= 0` → guard AVANT time.monotonic() (voir T-06)
- Educator appelé APRÈS la boucle, AVANT construction finale, MÊME en timeout

### EducatorAgent V9.1
- `run_task(contract)` → lance `run_curation()` en thread daemon → `AgentResult(success=True, payload={"status":"started"})`
- Déduplication : `_ingested_hashes: set[str]` + `hashlib.sha256(src)[:16]`
- `_sandbox_check(body)` : tuple EN PREMIER (`isinstance(run_result, tuple)` avant `getattr`)
- `sandbox_check` : méthode **statique** sur `EducatorCurator`
- `educator_agent._running` : property getter/setter → `self._curator._running`
- `ED-02` : `if repos_filter is not None:` ([] est falsy — ne pas confondre avec None)

### ObserverAgent
- `_is_duplicate()` Jaccard lexical >= seuil (pas cosine)
- archivage `.json → .archived` (pas suppression)
- `make_report_id` / `should_archive` module-level dans observer_reporter, réexportés

### RefactoPattern (appliqué à tous les agents > 10 KB)
- Classe orchestration légère (< 8 KB) + modules responsabilité unique
- Aliases retrocompat sur l'agent original (wrappers 1 ligne)
- Injectable via `agent._composant = mock` dans les tests

## RÈGLE ABSOLUE — ATTENDRE INSTRUCTION AVANT TOUTE ACTION
**AUCUN outil** (lecture, scan, écriture) sans ordre explicite de l'utilisateur.
- Lire/scanner/lister un fichier ou dossier : UNIQUEMENT si l'utilisateur dit explicitement "lis", "scanne", "liste", "vérifie", etc.
- Écrire (write_file, edit_file, create_directory) : UNIQUEMENT sur ordre explicite.
- Si un processus externe est en cours → signaler l'état, ne rien faire.
- Objectif : économiser des tokens. En cas de doute → demander, ne pas agir.

## DIAGNOSTIC PRÉLIMINAIRE
Lire TOUS les fichiers cibles AVANT d'écrire une seule ligne.
Un sprint « à faire » peut être « déjà fait » — vérifier avant de coder.
Ne JAMAIS re-écrire du code conforme sous prétexte de « compléter ».

## MISE À JOUR DE SESSION (OBLIGATOIRE)
Fin de session : mettre à jour 001 (patterns nouveaux), 002 (arbo + état tests), 003 (nouvelles erreurs).
Ordre : (1) vérifier fichiers modifiés, (2) mettre à jour skills, (3) confirmer état projet.

## SESSION 2026-05-02 — AMC-MIG-04 TERMINÉ (MediBot)
- **AMC-MIG-04** : router REST `/amc` créé
  - `routers/amc.py` : **nouveau fichier** (5 endpoints + 1 bonus)
    - `GET  /amc/organismes` : liste actifs, filtrable par `type`, CNOPS exclu (AMC-04)
    - `GET  /amc/organismes/{code}` : détail par code, accepte inactifs (CNOPS legacy)
    - `GET  /amc/couverture/{patient_id}` : couverture du patient pour le cabinet (200+null si absente)
    - `POST /amc/couverture` : upsert couverture — validation code vs DB (AMC-12), profil_code uppercased
    - `POST /amc/ticket` : calcul ticket modérateur complet — AMC-16 + AMC-11 via `calcul_ticket()`
    - `GET  /amc/reseau/{organisme_code}` : check convention tiers payant cabinet ↔ organisme
  - `main.py` : import + `app.include_router(amc_router)` ajoutés (fin du bloc medications)
  - Patterns retenus :
    - `GET /couverture/{patient_id}` retourne 200+null (pas 404) si absence — absence est une info
    - Validation `profil_code` upstream dans le router avant d'appeler `upsert_couverture` (AMC-12)
    - Règle 93 : `patient_id[:8]` uniquement dans les logs, jamais les montants
    - `calcul_ticket()` reçoit `clinic_id` depuis `current_user.clinic_id` (jamais du payload)
- Prochain sprint : **AMC-MIG-05** — tests pytest `routers/amc.py` + `amc_service`

- **AMC-MIG-03** : intégration amc_service dans billing + handler WA couverture
  - `routers/handlers/amc_coverage_handler.py` : **existait déjà complet** (AMC-04/12/14, i18n, patterns regex)
    - Pattern invariant : audit préliminaire systématique confirme — handler WA 100% conforme
  - `services/billing_consultation_service.py` : `get_amc_ticket_for_appointment()` ajouté
    - Flux : RDV → transaction (tarif) → couverture AMC → `calcul_ticket()` → dict sérialisable
    - Imports tardifs (`Appointment`, `get_couverture`, `calcul_ticket`) — évite circulaire
    - Regle 93 : patient_id[:8] uniquement dans les logs
    - Retourne `ticket_result=None` si pas de couverture AMC ou pas de transaction (mode dégradé silencieux)
  - `routers/consultation_billing.py` : endpoint `GET /billing/ticket/{appointment_id}` ajouté
    - Import `get_amc_ticket_for_appointment` ajouté dans le bloc d'imports service
    - Handler `get_ticket_moderateur` : délègue au service, 404 si RDV inconnu
    - Placement : section dédiée avant LOCK REDIS
  - 2 deltas réels sur 3 livrables prévus (1 livrable déjà fait)
- Prochain sprint : **AMC-MIG-04** : router REST `/amc` (GET organismes actifs, POST couverture patient, GET ticket)

- **AMC-MIG-01** : module ETL AMC completé (3 scrapers manquants créés)
  - `scrapers/scraper_cnops.py` : taux legacy CNOPS (3 actes, confiance 80, AMC-04)
  - `scrapers/scraper_medicament_ma.py` : 4 catégories médicaments (listes A/B/C + NR)
  - `scrapers/scrapers_all.py` : runner parallèle `asyncio.gather` sur les 4 scrapers
  - `scrapers/__init__.py` : mis à jour (9 exports au lieu de 4)
  - Pattern invariant : audit préliminaire systématique — 8/11 fichiers existaient déjà
- **AMC-MIG-02** : couche backend AMC créée (modèles ORM + service métier)
  - `backend/models/amc.py` : 4 classes ORM (`AmcOrganisme`, `AmcTaux`, `AmcReseau`, `PatientCouverture`)
    - Pattern Mapped/mapped_column SQLAlchemy 2.0 (conforme au reste du projet)
    - Relations bidirectionnelles : organisme ↔ taux, organisme ↔ reseau, organisme ↔ couvertures
    - `PatientCouverture.ald_pathologies` : `ARRAY(String)` PostgreSQL
  - `backend/services/amc_service.py` : 6 fonctions async + dataclass `TicketResult`
    - `get_couverture()` / `upsert_couverture()` : lecture et écriture couverture patient
    - `get_organisme_by_code()` : lookup par code court (accepte CNOPS inactif AMC-04)
    - `get_taux_organisme()` : taux valide à une date donnée (valide_depuis ≤ ref ≤ valide_jusqua)
    - `calcul_ticket()` : coeur métier — AMC-16 (base_amo=min(tarif,tnr)) + AMC-11 (guard total≤tarif)
    - `est_dans_reseau()` : vérif convention tiers payant cabinet ↔ organisme
    - `list_organismes_actifs()` : filtre actif=True (CNOPS exclu du listing normal)
  - Invariants AMC dans le service :
    - AMC-11 : guard `total_remb > tarif_reel` → plafonner remb_amc_dh, jamais lever d'exception
    - AMC-16 : `base_amo = min(tarif_reel, tnr)` appliqué avant tout calcul AMC
    - `TicketResult.to_dict()` : tous les montants arrondis à 2 décimales
    - Formule AMC : `remb_amc = max(0, base_amc * taux_amc% - remb_amo)` (AMC couvre le solde post-AMO)
- Prochains sprints AMC :
  - **AMC-MIG-03** : intégration `amc_service` dans `consultation_billing` ou `chat.py` (collecte couverture WA)
  - **AMC-MIG-04** : router REST `/amc` (GET organismes, POST couverture patient, GET ticket)

## SESSION 2026-04-30 — SETTINGS-PROFILE TERMINÉ (0 test Python)
- `main.ts` : handler `userctx:setName(name)` — lit `user_context.json`, patch `identity.name`, écriture atomique T-14 (renameSync). Crée le dossier `projects/.llca/` si absent.
- `preload.ts` : `userContext.setName` exposé via contextBridge
- `SettingsModal.tsx` : section «👤 Profil» en tête du corps. Charge le prénom au montage via `userctx:read`, sauvegarde sur `onBlur` ou `Enter`, feedback «✓ Enregistré» 2 s. Prénom vide = écriture de `""` (efface le prénom).
- Pattern : action explicite utilisateur → écriture directe JSON (pas de WAL) — conforme spéc v3 §4.3 (`user_correction` source)

## SESSION 2026-04-30 — PROJ-UI-05 TERMINÉ (0 test Python)
- 5 fichiers modifiés en une passe
- `App.tsx` : gate `activeProject` — `ProjectWelcomeScreen` si null, `Layout` sinon. Import `useProjectStore` + `ProjectWelcomeScreen` + `handleProjectOpen` callback (no-op : store met à jour seul)
- `TitleBar.tsx` : pill projet actif (FolderOpen + nom tronqué, accent-dim, b-acc) + bouton “‹ Projets” (ChevronLeft, appelle `closeProject()`). S'affiche uniquement si `activeProject` non null
- `projectStore.ts` : `ProjectMeta` étendu avec `tags: string[]`
- `ProjectCard.tsx` : bloc tags rendu sous la méta (chips amber, meme style que modal) si `project.tags?.length > 0`
- `ProjectWelcomeScreen.tsx` : `ideaTags` state ajouté, `handleCreateFromIdea` le peuple depuis `idea.tags`, `ProjectCreationModal` reçoit `initialTags` + `onOpenInspiration`, `onClose` réinitialise `ideaTags`
- Pattern invariant : `as any` pour `-webkit-app-region` dans TitleBar (non dans `React.CSSProperties`)

## SESSION 2026-04-30 — PROJ-UI-04 TERMINÉ (audit → 2 deltas, 0 test Python)
- Audit préliminaire : `ProjectCreationModal.tsx`, `projectStore.ts`, `main.ts` étaient **déjà complets** (chips tags, StorageModeToggle, bouton Inspiration, handler project:create avec tags+storageMode)
- 2 deltas trouvés et corrigés en une passe :
  - `preload.ts` : `projects.create` ne transmettait que `(name, description)` → étendu `(name, description, tags?, storageMode?)` avec `ipcRenderer.invoke('project:create', name, description, tags ?? [], storageMode ?? 'shared')`
  - `ProjectWelcomeScreen.tsx` : `handleCreate` avait signature `(name, description)` → corrigée `(name, description, tags = [], storageMode = 'shared')` + passage à `createProject(name, description, tags, storageMode)`
- Pattern invariant confirmé : toujours auditer avant de coder — 4 fichiers sur 4 étaient déjà écrits
- 0 nouveau fichier, 0 test Python (sprint UI pur)

## SESSION 2026-04-30 — PROJ-UI-03 TERMINÉ
- `InspirationPanel.tsx` : skeleton cards animés (3 placeholders shimmer) pendant le chargement MCP
- `SkeletonCard({ delay })` + `SkeletonList()` : composants internes, délai cascade 0/160/320 ms
- Label "Génération en cours…" avec 3 dots pulsants (animation insp-dot-pulse)
- `ui05-enhancements.css` : §27 ajouté — `.insp-skeleton-*` + shimmer + `.insp-generating-*`
- Erreur masquée pendant loading (`!loading && error`) — évite le flash
- 0 nouveau fichier Python, 0 test Python (sprint UI pur)
- Pattern : skeleton toujours en 3 cartes (reflète les 3 idées attendues du LLM)

## SESSION 2026-04-30 — VOICE-11 CONFIRME DONE (audit)
- `Voice/requirements.txt` et `Voice/install.bat` existaient deja complets
- Pattern invariant confirme : toujours auditer avant de coder
- VOICE-00->11 : pipeline Voice complet (tous sprints DONE)

## SESSION 2026-04-30 — PROJ-UI-01 TERMINE
- `ProjectWelcomeScreen.tsx` : bloc Bonjour [nom] + bouton Inspiration
- `InspirationPanel.tsx` : existait deja complet (ecrit en session precedente)
- `preload.ts` + `main.ts` : userctx:read existaient deja
- `ui05-enhancements.css` : §26 ajoute (styles .proj-welcome-* + .insp-*)

## SESSION 2026-04-30 — PROJ-UI-02 TERMINE (10 tests)
- `core/mcp_handlers_projects.py` : `_tool_inspiration_generate` + `_inspiration_call_llm` + `_inspiration_fallback`
- `core/mcp_tools_schema.py` : schema `inspiration_generate` (24e tool)
- `core/mcp_server.py` : handler_map + docstring 23->24
- `ui/src/components/ProjectCreationModal.tsx` : props initialName? + initialDescription?
- `ui/src/components/ProjectWelcomeScreen.tsx` : states ideaName/ideaDescription, handleCreateFromIdea complet
- `tests/test_proj_ui_02.py` : 10 tests (fallback, LLM parsing, truncature, routage)
- `tests/test_mcp_server.py` : count 23->24 + inspiration_generate dans expected
- Pattern T-19 confirme : import tardif dans _inspiration_call_llm -> patcher core.llm_generator.LLMGenerator
- Pattern staticmethod : patch.object sur la CLASSE (McpHandlersProjects), pas l'instance

## SESSION 2026-04-30 — PROJ-11 TERMINÉ (38 passed in 1.14s)
- Audit préliminaire : `core/project_contributor.py` existait déjà (écrit en session précédente)
- `tests/test_proj_11.py` créé — 20 tests, 5 classes :
  - `TestContributionResult` : to_dict(), defaults, valeurs
  - `TestHelpers` : _load_local_skills, _is_confidential, _dedup_local, _build_global_entry_id, _increment_skills_generated (atomique T-14, silencieux si absent)
  - `TestContributorPalaceAbsent` : palace None → mode dégradé, no skills, contribute() ne lève jamais
  - `TestContributorPipeline` : quality guard, confidential guard, global dedup, contribution réussie, stats++, multiple skills, wing/metadata corrects, erreur mine_content capturée
  - `TestExtractQuality` : prefixes quality_score/score, case-insensitive, absent→0, invalide→0, # stripped
- 2 bugs corrigés post-création en une passe :
  - Bug 1 : `_is_in_global` comparait `body` avec frontmatter vs `existing_entry.content` sans → Jaccard sous 0.85. Fix : `_strip_frontmatter()` helper module-level, appelé avant `_is_in_global()`. Body complet préservé pour `mine_content()`.
  - Bug 2 : `_seed_project(tmp_path)` créait `test-proj/` mais `_make_meta(slug="mon-projet")` → répertoire absent → `mine_content` jamais appelé. Fix : `_seed_project(tmp_path, slug="mon-projet")`.
- Pattern invariant : `_strip_frontmatter()` retire les lignes `quality_score:/score:` (10 premières lignes, prefixe `#` inclus) avant comparaison Jaccard globale
- `~2089 passed` (estimation — 38 passed test_proj_11.py confirmés)

## SESSION 2026-04-30 — PROJ-09 TERMINÉ (21 passed in 0.67s)
- `core/project_history_compactor.py` — `ProjectHistoryCompactor.compact(project_dir, keep=200)` + `CompactionResult`
- `tests/test_proj_09.py` — 21 tests, 5 classes
- `core/mcp_handlers_projects.py` — stub `_tool_project_compact_history` remplacé par vraie implémentation
- 2 tests corrigés en cours de route : `ProjectMeta` est une dataclass sans defaults — utiliser `from_dict()` pour les tests MCP
- Invariants PROJ-09 : écriture atomique T-14, mode dégradé silencieux, lignes NDJSON invalides ignorées, keep=0 clampé à 1, archive dans `history_archive/YYYYMMDD_HHMMSS.jsonl`
- Pattern sliding-window : `entries[:-keep]` → archive, `entries[-keep:]` → history.jsonl

## SESSION 2026-04-30 — PROJ-06/07/08 VALIDÉS (88 passed in 1.50s)
- PROJ-06 : `core/project_wal.py` + `tests/test_proj_06.py` — 35 tests ✅
- PROJ-07 : `core/user_context_injector.py` + `tests/test_proj_07.py` — existaient déjà (audit préliminaire)
- PROJ-08 : `core/user_context_learner.py` + `tests/test_proj_08.py` — existaient déjà (audit préliminaire)
- 2 tests corrigés dans `test_proj_08.py` (tests mal calibrés vs comportement défensif du source) :
  - `test_tone_unknown` : `_normalize_value("communication.tone", "zen")` retourne `None` (non dans `_TONE_MAP`) — pas `"zen"`
  - `test_explicit_command_written_to_wal` : `identity.name` est dans `SENSITIVE_FIELDS` → `explicit_command` bloqué aussi (seul `user_correction` passe). Test réécrit avec champ non-sensible (`communication.tone`)
- Pattern confirmé : `SENSITIVE_FIELDS` bloque `auto_detected` ET `explicit_command` — seul `user_correction` passe pour `identity.*` et `communication.language`
- Pattern confirmé : `_TONE_MAP` retourne `None` pour ton inconnu (comportement défensif voulu)
- `user_context.py` : `SENSITIVE_FIELDS = frozenset({"identity.name", "identity.locale", "identity.timezone", "communication.language"})` — guard dans `append_wal()`
- `user_context_learner.py` : `_TONE_MAP` exhaustif — tout ton non listé → `None` (pas de passthrough)
- `user_context_injector.py` : budget `MAX_INJECT_CHARS = 3200` (800 tokens × 4 chars/token) — FIFO sur `learned` si dépassement

## SESSION 2026-04-30 — VOICE-10 TERMINÉ
- VOICE-10 : SettingsModal.tsx + ChatPanel.tsx
  - `SettingsModal.tsx` : section `🎤 Voix` déjà présente depuis VOICE-09 (diagnostic préliminaire confirme : ne pas re-écrire)
  - `ChatPanel.tsx` : `useEffect` Alt+V ajouté — `keydown` sur `window`, guard `sttEnabled`, `e.preventDefault()`, cleanup `removeEventListener`
  - Dépendances : `[sttEnabled, toggleListening]` (re-bind si STT toggle ou store change)
  - Invariant : le raccourci n'est actif que si `sttEnabled === true` (évite la confusion quand STT désactivé)

## SESSION 2026-04-29 — VOICE-02 TERMINÉ
- VOICE-02 : `Voice/voice_transcriber.py` créé (faster-whisper wrapper)
  - `VoiceTranscriber` : `_model_factory` injectable, `WhisperModel` lazy dans `load()`
  - `transcribe(pcm_bytes)` : WAV temp créé + supprimé dans `finally`, logprob→conf via `math.exp` clampé [0,1]
  - `TranscriptionResult` : `to_dict/from_dict/failure()`, `duration_ms` calculé même en cas d'échec
  - `_write_wav_temp()` + `_pcm_duration_ms()` : helpers module-level testables
  - `test_voice_02.py` : 7 classes, 34 tests — **34 passed in 0.58s**
  - FL-04 vérifié : déjà implémenté (`record_usage/record_outcome` dans skill_library.py + orchestrator_loop.py)

## SESSION 2026-04-29 — FL-03 TERMINÉ
- FL-03 : `sandbox_engine.py` durci (fichier unique, stdlib, zero dependance)
  - `_FORBIDDEN_SOFT` frozenset : subprocess, socket, os, shutil, urllib, http, pty, ctypes, importlib, zipimport, multiprocessing, winreg, ftplib, smtplib
  - `_prescan_imports(code)` : AST walk, retourne le root interdit ou None, silencieux sur SyntaxError
  - Bug corrige en cours : `alias.name` et `node.module` remplacés par `root`/`mod` (retourner le root, pas le nom complet)
  - `_run_subprocess_hardened()` : prescan + PYTHONPATH='' + cwd=tempdir isole, exit_code=-2 si import bloque
  - `_run_subprocess_legacy()` : ancienne impl conservee, jamais appelee par run()
  - `_run_subprocess()` : alias retrocompat -> _run_subprocess_hardened()
  - `effective_mode` : soft -> 'soft_hardened', auto sans docker -> 'soft_hardened'
  - `test_fl_03.py` : 27 tests — **27 passed in 1.98s**

## SESSION 2026-04-29 — FL-02 CORRIGÉ (rollback mutation + model_override propre)
- FL-02 rollback : mutation `self._llm.ollama.model` remplacée par `model_override` local à l'appel
  - `ollama_client.py` : `generate(system, user, model_override=None)` — `model` local, `self.model` inchangé
  - `llm_generator.py` : `generate_text(system, user, model_override=None)` — transmis à `ollama.generate()`
  - `coder_agent.py` : `model_override: Optional[str] = None` local à `_generate_code()`, passé à `generate_text()`
  - `test_fl_02.py` : 2 tests mis à jour (testent `model_override` dans `call_args`, pas mutation)
  - `test_v8_08.py` : 3 tests `TestBuildPatchV808` corrigés (`edits`→`files`, `mode`→`action`, `content`→`code`) — désalignement préexistant REFACTO-07 révélé
  - Run final : **113 passed in 2.51s**
  - Invariant FL-02-R4 : `model_override=None` → `self.ollama.model` utilisé (jamais muté)

## SESSION 2026-04-29 — FL-02 TERMINÉ
- FL-02 : `ModelRouter` branché dans `CoderAgent._generate_code()` via `self._model_router`
  - `coder_agent.py` : `__init__` + `create()` étendus avec `model_router=None` (rétrocompat totale)
  - `_generate_code()` : bloc FL-02 avant `_build_coder_prompt()` — consulte le router, change `self._llm.ollama.model` si différent, swallowe toute exception
  - `agent_orchestrator.py` : `__init__` + `create()` étendus — `create()` instancie `ModelRouter()` automatiquement si non injecté, passe à `CoderAgent.create()`
  - `test_fl_02.py` : 12 tests — **69 passed** (fl_02 + refacto_07 + agent_orchestrator + orchestrator)
  - Pattern : `routing.enabled=false` par défaut → zéro régression si `online_models.json` absent

## SESSION 2026-04-29 — FL-01 TERMINÉ
- FL-01 : `StructuredReflection` dataclass dans `tester_runner.py` — remplace la str vague
  - `_HINT_MAP` + `_criteria_to_fix_hints(criteria)` : traduit CodeEvaluator → hints LLM (max 5)
  - `_build_reflection()` : signature étendue `(sandbox_result, receipt, eval_result=None, iteration=0)` → retourne `StructuredReflection` (pas str)
  - Rétrocompat : `eval_result=None` → `fix_hints=[]`, `quality_criteria=[]`, `quality_score=0`
  - `tester_agent.py` : `eval_result` conservé après `evaluator.evaluate()`, `reject_payload` enrichi avec `reflection_structured` (dict) + `fix_hints` (list) + `reflection` reste str rétrocompat
  - `orchestrator_loop.py` : `structured_reflections: list[dict]` locale à `run()` (pas attribut d'instance), injection `fix_hints` dédupliqués + `last_quality_score` dans `arch_context` à partir de la 2ème itération
  - `coder_builder.py` : `build_coder_prompt()` args optionnels `fix_hints` + `last_quality_score`
  - `coder_agent.py` : `_generate_code()` passe les nouveaux args depuis `contract.context`
  - `test_refacto_05.py` : 3 tests `TestBuildReflection` mis à jour (str → attributs StructuredReflection)
  - `test_fl_01.py` : 20 tests créés — **20 passed + 47 passed rétrocompat**
  - Pattern : `import field` inutilisé retiré de `tester_runner.py` après première passe

## SESSION 2026-04-25 — PATTERNS APPRIS (Voice VOICE-00 + VOICE-01)
- Nouveau package `Voice/` crée — pipeline voix local offline, isolation totale de core/
- Tests Voice : `sys.path.insert(0, _VOICE_DIR)` en tête de chaque fichier test (Voice/ n'est pas un package Python)
- `_vad_factory` injectable dans `VoiceCapture.__init__` : pattern préféré au `patch` global pour les libs C (webrtcvad)
- `_FakeVad(sequence, default)` : séquence bool consommée chunk par chunk, retourne `default` quand épuisée
- Import tardif `webrtcvad` dans `__init__` (pas niveau module) → `_DummyVad` fallback si absent
- `_lock_instance = threading.Lock()` : attribut d'instance (règle LCCA invariante confirmée)
- `collections.deque(maxlen=N)` pour le pre-speech buffer (ring buffer O(1))
- `stop()` flush l'utterance en cours si buffer non vide → retourner le résultat partiel
- Chunks taille incorrecte : ignorer silencieusement, NE PAS compter dans `total_chunks`
- `load_voice_config()` : Python 3.11 tomllib stdlib, fallback tomli, fallback défauts si absent/corrompu
- `BeepSpec.generate_pcm()` : retourne `None` si numpy absent (pas d'exception), fade-out 10% pour éviter le clic audio
- Tests Voice : `pytest.importorskip("numpy")` pour les tests dépendant de numpy
- `make_speech_chunk()` / `make_silent_chunk()` : helpers dans le module source (voice_capture.py), pas dans les tests
- Invariant confirmé : Voice/ n'importe JAMAIS depuis core/ — 0 dépendance croisée
- `VRAM_MIN_MB_FOR_CUDA = 1500.0` MB libre minimum pour activer CUDA (STT + TTS ensemble)
- Avant tout sprint VOICE-* : vérifier si le fichier cible existe déjà (même pattern récurrent que SI-*/PROJ-*)

## SESSION 2026-04-23 — PATTERNS APPRIS (session 7 — SI-03 audit)
- SI-03 : `OrchestratorLight` (existait déjà) — même pattern que SI-02
  - `get_coupling_mode()` dans `si_config.py` lit `cfg["general"]["coupling_mode"]` (int, clamp 1-3)
  - Tests qui patchent `get_coupling_mode` : cibler `SelfImprove.engines.orchestrator.get_coupling_mode` (binding local)
  - `_cooldowns`, `_trigger_counts`, `_trigger_date` : dicts module-level dans `si_utils.py` — à vider via `.clear()` dans setUp des tests pour isolation
  - `force_cooldown()` : utilise `time.monotonic()`, pas datetime — compatible avec les tests qui mockent le temps
  - Avant tout sprint SI-*, vérifier si le code EXISTE déjà (pattern récurrent sur ce projet)

## SESSION 2026-04-23 — PATTERNS APPRIS (session 6 — SI-02 tests)
- SI-02 : `observer_daemon.py` (était déjà implémenté en session 5) — tests créés (`test_si_02_observer.py`, 22 tests)
  - Pattern `_make_cfg(tmp_path)` helper local dans le test : évite de dépendre de `load_config()` (chemins absolus Windows)
  - `sys.modules` patch via `patch.dict` pour simuler import absent de TelemetryStore
  - Test accumulation borgnes_map : deux `run_once()` successifs sans recréer le daemon
  - `_parse_wal` : NDJSON (une ligne JSON = une entrée), lignes invalides ignorées silencieusement
  - `import pytest` inclus dans les imports même si non utilisé directement (convention LCCA tests)
- Règle confirmée : avant tout sprint, vérifier si le code cible EXISTE déjà (ne pas re-écrire du code conforme)

## SESSION 2026-04-23 — PATTERNS APPRIS (session 5 — V10.5 SelfImprove)
- SI-V10.5 : nouveau package `SelfImprove/` créé — système auto-amélioration LCCA
  - `lcca_si.py` : CLI point d'entrée (racine projet) — 8 commandes : observe/decide/auto-fix/educator/history/approve/borgnes/mode
  - `SelfImprove/si_config.py` : loader config.toml avec fallback défauts — rechargé à chaque run (pas de cache)
  - `SelfImprove/si_utils.py` : atomic_write_json (.tmp→rename), log_action (write-ahead CSV), add_pending_action, approve_pending_action, check_and_update_cooldown
  - `SelfImprove/engines/` : 4 modules — observer_daemon.py, orchestrator.py, auto_fix.py, educator.py
  - Pattern écriture atomique : TOUJOURS `tmp = path.with_suffix('.tmp')` → write → `tmp.rename(path)` — jamais écriture directe JSON
  - Pattern write-ahead : `log_action(..., status='started')` AVANT toute exécution d'action
  - Pattern cooldown : `check_and_update_cooldown(rule_id, cooldown_sec, max_per_day)` → bool
  - Grammaire unifiée règles : `{field, operator, value, filters}` — un seul format pour toutes les conditions
  - 3 modes couplage : 1=lecture seule (~50MB) | 2=semi-couplé défaut (~150MB) | 3=pipeline A2ABus (~300MB+LLM)
  - `min_coupling_mode` dans chaque règle JSON — règle ignorée si mode courant insuffisant
  - Auto-Fix : SmartPatcher (libcst) pour coroutine_never_awaited | template string pour missing_import
  - Auto-Fix conditions bloquantes : whitelist + mode≥2 + flag + test existant + coverage≥60% + tests verts avant+après
  - Borgnes Map (héritage V10) : clustering WAL → borgnes_map.json alimenté par Observer via ChromaDB
  - Import TelemetryStore en lazy dans ObserverDaemon (éviter import circulaire au démarrage)
  - `auto_push = false` codé en dur — jamais de push git automatique
  - Specs : `Docs/Specs/SelfImprovement/` (5 fichiers) | Sprints : `Docs/Sprints/SelfImprovement/` (7 sprints)

## SESSION 2026-04-23 — PATTERNS APPRIS (session 4 — clôture dette)
- DETTE-01 : `orchestrator.py` — suppression `_generate_stub()` (dead code DEPRECATED Sprint 09)
  - Classe `Orchestrator` dupliquée remplacée par `from core.orchestrator_compat import Orchestrator  # noqa: F401`
  - Pattern : re-export module-level préserve `from core.orchestrator import Orchestrator` sans dupliquer le code
  - Règle : quand un alias legacy existe dans un fichier _compat, le fichier source doit juste le ré-exporter
- DETTE-02 : `web_search_engines.py` — imports locaux `import json` / `import os` remontés au niveau module
  - Violation R9 (imports dans corps de méthode) corrigée sans aucun changement de comportement
  - Règle : imports stdlib toujours au niveau module sauf import circulaire avéré
- DETTE-03 : `002-context.md` — tailles obsolètes corrigées + arbo complétée
  - llm_generator.py : 28.3 KB → 9.09 KB | mcp_tool_handlers.py : 28.9 KB → 2.36 KB
  - 9 modules REFACTO-10/11 ajoutés à l'arbo (llm_config, ollama_client, llm_prompt_builder, llm_code_utils, mcp_context_builders, mcp_handlers_core/spec/llm/extras)
- FIX-MCP-CRASH-01 : `core/mempalace_adapter.py` créé (module manquant depuis MIG-04/05)
  - Cause : `memory_engine.py` l.70 fait `from core.mempalace_adapter import ExistingMemPalaceAdapter` mais le fichier n'avait jamais été créé malgré MIG-04/MIG-05 marqués ✅ FAIT
  - Pattern : `ExistingMemPalaceAdapter` expose `is_available` (bool), `palace_path` (str), `lcca_collections` (dict ChromaDB)
  - Design : si chromadb absent ou palace inaccessible → `is_available=False` (mode dégradé silencieux) — MCP Server démarre quand même
  - Règle : tout import tardif dans `__init__` d'une façade doit avoir son module cible créé. Vérifier via `filesystem:list_directory core/` que le fichier existe.
- MIG-05 AUDIT COMPLÉTé (FIX-MCP-CRASH-01) : 2 drawers LLCA dans le MCP (pas 1 comme indiqué dans migration_report)
  - `wing_lccacodeagent/diary` : sp03 2026-04-16 — déjà exporté
  - `wing_claude/diary` : V7-env-validation 2026-04-18 — **manquant** → exporté dans `claude_diary_lcca_v7_2026-04-18.json`
  - `migrate_palace.py` mis à jour pour importer les 2 drawers (boucle générique sur liste)
  - `run_migration.bat` créé dans `mempalace/migration/` : vérifie venv + chromadb, menu dry-run/réel
  - Palace ChromaDB toujours **vide** — à peupler en lançant `run_migration.bat` [2] avec venv actif
- MIG-05 TERMINÉ (2026-04-23) : 75/75 drawers importes, 0 erreur
  - palace local peuple : 192 KB ChromaDB dans `mempalace/palace/chroma.sqlite3`
  - 3 skills (73 sections) + 2 drawers historiques MCP (sp03 + V7-env-validation)
  - `run_migration.bat` [1] dry-run valide puis [2] reel confirme
  - Bugs corriges : `parents[3]` -> `parents[2]` dans migrate_palace.py | bat : goto plats + ASCII pur
  - Migration MIG-01->MIG-05 : toutes etapes terminees, LLCA 100% autonome, 0 dependance MediBot

## SESSION 2026-04-23 — PATTERNS APPRIS (session 3)
- REFACTO-17 : `ollama_client.py` — nettoyage interne (12.61 KB → 10.27 KB)
  - Extraction 3 helpers module-level : `_build_request()`, `_stream_lines()`, `_capture_tps()`
  - Règle : nettoyage INTRA-fichier (duplication × 4) — PAS de nouveau module (responsabilité unique)
  - 0 nouveau fichier, 0 alias rétrocompat nécessaire
  - Couverture : test_refacto_11.py + test_v9_05.py + test_v9_06.py (tests existants suffisants)
  - `warmup()` laissé intact : construit son Request manuellement (stream:False, options différentes)
- Audit coverage B — `planner.py` (11.46 KB) : `test_planner.py` créé (18 tests)
  - PatchOperation + Plan.is_valid() (dédup fichiers identiques)
  - PlannedOperation.file_path + priorité par défaut
  - Planner.build() : chemin normal + ValueError > MAX_FILES_PER_TX
  - MultiFilePlanner.create_plan() : vide, dédup, limite MAX, tri topologique (core en premier)
  - validate_plan_consistency() : 3 règles (max fichiers, symbole dupliqué, delete+modify)
  - _infer_op_params() : 7 cas (ajoute/cree/supprime/corrige/inconnu + import + core)
  - _infer_symbol() : regex, fallback snake_case, cas vide
- Audit coverage B — `spec_validator_rules.py` (13.82 KB) : couverture satisfaisante via test_spec_layer.py (pas de lacune bloquante)

## SESSION 2026-04-23 — PATTERNS APPRIS (session 2) ✅ VALIDÉ 143 tests
- REFACTO-15 : `memory_engine.py` (17.16 KB → 6.6 KB) — ✅ test_refacto_15.py + test_memory_engine.py PASSED
  - memory_engine_store.py : StoreResult, check_threshold, enrich_payload, extract_content, store_via_adapter, MemoryStoreService (7.7 KB)
  - memory_engine_search.py : MemoryEntry, chromadb_query, normalize_entry, MemorySearchService (5.3 KB)
  - memory_engine.py : façade légère, aliases privés rétrocompat (_check_threshold, _enrich_payload, _store_via_adapter, _extract_content)
  - Helpers store : signature modifiée (available: bool en param) — privés dans MemoryStoreService, appelés via façade avec self._available
  - 18 tests ajoutés (test_refacto_15.py)
- REFACTO-16 : `spec_generator.py` (16.75 KB → 8.8 KB) — ✅ test_refacto_16.py + test_spec_layer.py + test_spec_retry.py PASSED
  - spec_generator_helpers.py : _extract_title, _extract_abstract, _compute_complexity (2.4 KB)
  - spec_generator_context.py : _DOMAIN_FILES, _KEYWORD_FILES, _build_technical_context SPEC-02 (4.1 KB)
  - spec_generator.py : façade SpecGeneratorService + réexports rétrocompat (from ... import ... préservé pour les tests existants)
  - Réexport pattern : `from core.spec_generator import _extract_title` fonctionne grâce à `from core.spec_generator_helpers import _extract_title` dans spec_generator.py
  - 18 tests ajoutés (test_refacto_16.py)
- Mise à jour 002-context : table dette corrigée, PROCHAIN SPRINT SUGGÉRÉ à jour, arborescence complétée, +ollama_client.py dans surveillance
- Whitelist educator : source de vérité = `educator_whitelist.json` (pas `educator_agent.py`)
- 6 repos ajoutés P0/P1 : flake8, dataclasses-json, cattrs, sqlalchemy, typeshed, ruff
- `python/typeshed` débloqué : 1 ligne dans `list_py_files()` — `.endswith((".py", ".pyi"))`
- Analyse logs Educator : astroid (LGPL) + hypothesis (MPL-2.0) retirés | numpy skip_license_check
- REFACTO-12 : `cognitive_patterns.py` (16 KB) — prompts extraits dans `cognitive_prompts.py`
  - cognitive_patterns.py : 7.4 KB (classes + _call_llm + imports retrocompat)
  - cognitive_prompts.py  : 7.2 KB (4 constantes DEEP/FORMATTER/VALIDATOR/DIRECT)
  - Aliases `_*_SYSTEM` maintenus dans cognitive_patterns pour retrocompat tests
  - 18 tests ajoutés (test_refacto_12.py)
- REFACTO-13 : `error_analyzer.py` (14.6 KB → 5.8 KB)
  - error_classifier.py      : 9.3 KB (classify_syntax/import/attribute/name, méthodes statiques)
  - error_recovery_hints.py  : 5.6 KB (is_module_fixable, build_fix_prompt, try_auto_fix)
  - Aliases rétrocompat maintenus dans error_analyzer.py (analyze_syntax_error, etc.)
  - 18 tests ajoutés (test_refacto_13.py)
- REFACTO-14 : `mempalace_client.py` (14.5 KB → 6.1 KB)
  - mempalace_layers.py : 10.6 KB (PalaceLayers : 4 collections ChromaDB + MemoryEntry)
  - mempalace_fs.py     : 2.6 KB (PalaceFilesystem : write_entry, _ensure_dirs)
  - Proxy `palace.collections` maintenu dans MemPalaceClient pour rétrocompat
  - 18 tests ajoutés (test_refacto_14.py)
- V9-09 feature spec : SpecDiff dataclass + SpecEntry.diff() | 6 tests (test_spec_diff.py)
- V9-09 feature spec : generate_with_retry() dans SpecGeneratorService | 6 tests (test_spec_retry.py) ✅ PASSED
- V9-09 UI : TelemetryPanel.tsx + telemetryStore.ts + telemetry:readHistory IPC
  - TelemetryPanel intégré dans ContextPanel (après TxSection)
  - Sparkline SVG sans dépendance externe (var CSS pour thématisation)
  - telemetryStore découplé de contextStore (SRP)

## SESSION 2026-04-23 — PATTERNS APPRIS (session 19 — REFACTO-20 transaction_manager)
- REFACTO-20 : `transaction_manager.py` (16.7 KB → ~9 KB façade)
  - `transaction_wal.py` créé : `TransactionWalMixin` — `_read_wal_for_tx` + `_get_tx_completion_timestamp` + `cleanup_old_snapshots` + `archive_old_wal_entries` (~5 KB)
  - `transaction_manager.py` : façade `TransactionManager(TransactionWalMixin, TransactionLegacyMixin)` — cœur ACID uniquement (begin/log_operation/commit/rollback + _snapshot + _backup)
  - MRO : `TransactionWalMixin` avant `TransactionLegacyMixin` (maintenance > legacy)
  - `TransactionWalMixin` réexporté depuis `transaction_manager.py` via `# noqa: F401`
  - `_make_mixin()` helper dans le test : instancie `_Concrete(TransactionWalMixin)` minimal pour tester le mixin seul (pattern réutilisable)
  - `List` retiré de `typing` dans `transaction_manager.py` (plus utilisé après extraction)
  - +18 tests `test_refacto_20.py` : imports, MRO, _read_wal_for_tx, _get_tx_completion_timestamp, cleanup, archive, smoke

- REFACTO-19 : `web_search_engines.py` (13.2 KB → ~3.5 KB façade)
  - `web_search_clients.py` EXISTAIT DÉJÀ (9.03 KB) — même pattern récurrent SI-02/03/04/05
  - `web_search_engines.py` réécrit en façade : `MultiEngineSearchClient` uniquement + réexports rétrocompat
  - Réexports : `BaseSearchClient, _DdgLiteClient, _BraveSearchClient, _WikipediaClient` via `# noqa: F401`
  - `test_web_search.py` importe les 3 classes depuis `core.web_search_engines` → rétrocompat garantie
  - 0 nouveau test nécessaire : tests existants couvrent déjà le comportement
  - Pattern : **toujours vérifier si le module cible EXISTE déjà avant de coder**

- REFACTO-18 : `orchestrator.py` (15.6 KB → ~6 KB) — 3 modules créés
  - `orchestrator_pipeline.py` : `OrchestratorPipeline` (phases 3-9) + `_validate_changes()` pur (~5 KB)
  - `orchestrator_helpers.py` : `update_sprint_log()` + `dry_run()` helper pur (~2.5 KB)
  - `orchestrator.py` : façade `LCCAV5Fusion(OrchestratorSpecMixin, OrchestratorPipeline)` (~6 KB)
  - Aliases rétrocompat `_validate_changes()` et `_update_sprint_log()` maintenus sur la façade
  - `dry_run()` délègue via `_dry_run_fn` importé de `orchestrator_helpers`
  - Imports nettoyés : `datetime`, `List` supprimés de la façade (ne servent plus)
  - MRO : `LCCAV5Fusion(OrchestratorSpecMixin, OrchestratorPipeline)` — OrchestratorSpecMixin en premier (méthodes `_run_spec_layer` prioritaires)
  - `run_pipeline()` reçoit toutes les déps en arguments explicites (pas de self-state caché)
  - Pattern `_validate_changes(tx_manager, workspace)` : fonction module-level (pas méthode) pour faciliter les tests
  - Audit UI complèt (session 17) : UI 100% implémentée (SI-06 + TelemetryPanel + tous stores + electron handlers)
  - Fix docstring `mcp_server.py` : "11 tools" → "23 tools (PROJ-04)"

- PROJ-04 : `mcp_handlers_projects.py` créé (nouveau, n'existait pas)
  - Mixin `McpHandlersProjects` : 10 handlers `_tool_project_*` + 3 getters lazy + `_active_ctx` / `_set_active_ctx`
  - `_active_context` : variable module-level (`None` par défaut) — un seul projet ouvert par process MCP
  - Tests isolation : fixture `autouse` remet `_proj_mod._active_context = None` avant+après chaque test
  - pattern `_call_tool(server, tool, args) -> dict` : factorisation des appels `server.handle()` + parse JSON
  - `_initialized(server)` helper : handshake complet (initialize + notifications/initialized) en 2 lignes
  - `project_healthcheck` : import `_LCCA_ROOT` depuis `core.project_manager` pour détecter la racine projets
  - `project_compact_history` : stub dry-run — retourne stats sans modifier les données (PROJ-09 placeholder)
  - MRO update : `McpHandlersProjects` ajouté EN DERNIER dans `McpToolHandlers` (6 bases au lieu de 5)
  - `mcp_server.py` : `_project_manager = None`, `_project_lock = None`, `_project_orch = None` dans `__init__`
  - Pattern T-01 appliqué : `test_mcp_server.py` mis à jour 13→23 (count + set de noms)
  - Invariant : quand on ajoute des tools MCP → mettre à jour IMMEDÍATEMENT les tests `test_tools_list_*`

## SESSION 2026-04-23 — PATTERNS APPRIS (session 15 — PROJ-03)
- PROJ-03 : 4 fichiers créés (n'existaient pas — premier vrai sprint de création PROJ-*)
  - `ProjectContext` dataclass dans `project_context_assembler.py` (cohabite avec `get_palace`)
  - `get_palace()` : import tardif `MemPalaceClient` + mode dégradé silencieux si chromadb absent
  - `ProjectCheckpoint.save()` : écriture atomique `.tmp → Path.replace()` (règle T-14)
  - `ProjectOrchestrator.save_project()` : `lock.release()` dans `finally` invariant absolu
  - `_load_history()` : lecture LIFO (reversed), accumulation jusqu'à `max_tokens * 4 chars`, puis reverse
  - Tests : `get_palace` mocké via `patch("core.project_context_assembler.get_palace", return_value=None)` dans tous les tests assembler
  - Tests orchestrateur : 100% mocks (MagicMock pour tous les workers) — test d'intégration unitaire pur
  - `test_save_project_releases_lock_even_if_checkpoint_raises` : test invariant try/finally
  - `_make_mock_lock()` : `MagicMock(spec=ProjectLock)` — pas besoin d'instance réelle pour les tests orches

## SESSION 2026-04-23 — PATTERNS APPRIS (session 14 — PROJ-02)
- PROJ-02 : `ProjectLock` (existait déjà) — même pattern que SI-02/03/SI-04/PROJ-01
  - `_verify_pid()` : appel `psutil.pid_exists()` ou `os.kill(pid, 0)` **bloque sur Windows** dans pytest (même sur le PID courant)
  - Fix source : `_instance_id()` — remplacer `socket.gethostname()` par `os.environ.get("COMPUTERNAME") or ...` (zéro appel réseau)
  - Fix source : `_instance_suffix = uuid.uuid4().hex[:8]` dans `__init__` — évite collision de noms de fichiers temp quand deux instances `ProjectLock` tournent dans le même process (tests)
  - Fix tests : `_make_lock()` helper — assigner `lock._verify_pid = lambda pid: True` **dans le helper** pour isoler tous les tests d’un coup
  - Pattern : les tests qui veulent tester PID mort overrident directement `lock._verify_pid = lambda pid: False` (pas besoin de `patch.object`)
  - Règle générale : tout appel `psutil`, `os.kill`, `socket.gethostname` dans du code Windows = à isoler dans le helper de test, pas test par test
  - Anti-pattern T-10 bis confirmé : `psutil.pid_exists(current_pid)` peut bloquer sous pytest Windows même pour le PID courant

## SESSION 2026-04-23 — PATTERNS APPRIS (session 13 — PROJ-01)
- PROJ-01 : `ProjectManager` + `ProjectMeta` créés dans `core/project_manager.py`
  - `ProjectMeta` : dataclass avec `to_dict()` + `from_dict()` (pattern LCCA standard)
  - `list_projects()` : glob `*/.llca/project.json` (source de vérité), jamais index.cache.json
  - JSON invalide dans `_parse_meta()` : log warning + return None + continue (0 crash)
  - Tri `last_opened` desc : `projects.sort(key=lambda p: p.last_opened, reverse=True)`
  - `_generate_slug()` : NFD normalize → encode ascii ignore → regex `[^a-z0-9]+` → strip tirets
  - Unicité slug : `while (self._projects_dir / slug).exists()` + counter
  - `_rebuild_cache()` appelé après chaque mutation (create, archive) ET dans list_projects()
  - `get_project()` : délègue à `list_projects(include_archived=True)` + filtre id/slug
  - `update_last_opened()` : relit le meta via get_project, patch last_opened, réécrit project.json
  - 23 tests (vs 15 du sprint spec) : +6 tests bonus (include_archived, storage_mode isolated, uuid, migrated_from_v9, archive_false, get_none)
  - Pattern `_seed_project(tmp_path, slug, last_opened, status)` : helper local réutilisable PROJ-02+
  - `import field` dans le source : importé mais non utilisé — à retirer si warning lint
- Règle confirmée : `_write_json()` staticmethod identique dans PROJ-00 et PROJ-01 — ne pas factoriser (trop petite, dupliquer est OK dans ce contexte)

## SESSION 2026-04-23 — PATTERNS APPRIS (session 12 — PROJ-00)
- PROJ-00 : `MigrationManager` créé dans `core/migration_manager.py` (nouveau, n'existait pas)
  - `MigrationResult` : dataclass avec `success`, `already_done`, `projects_dir`, `legacy_project_id`, `skills_copied`, `errors`, `report`
  - `needs_migration()` : 2 conditions (projects/ absent OU index.cache.json absent)
  - `run()` : pipeline 6 étapes, idempotent (retourne `already_done=True` si déjà migré)
  - `_rewrite_paths()` : 3 passes string replace (double backslash, simple backslash, forward slash)
  - `_write_json()` : staticmethod, UTF-8 sans BOM, indent=2
  - `project.json` legacy : `migrated_from_v9=True`, `storage_mode="shared"`, `legacy_namespaces=["lcca_*"]`
  - `index.cache.json` : créé EN DERNIER (c'est le sentinel de `needs_migration()`)
  - Copie skills : `global_skills_dir = self._root / "skills"` — 0 erreur si absent
  - `_LCCA_ROOT = Path(__file__).parent.parent` — détection dynamique, pas de chemin Windows codé
  - 15 tests couvrant : needs_migration (3), arborescence (4), project.json contenu (5), _rewrite_paths (4), idémpotence, skills, MigrationResult
  - Delta +43 tests vs compteur session-11 : explication probable = tests ajoutés manuellement entre sessions
- Règle : tout nouveau sprint PROJ-* → `lcca_root` injectable dans le constructeur (pattern `tmp_path` pour les tests)
- Règle : `index.cache.json` = CACHE UNIQUEMENT, jamais source de vérité

## SESSION 2026-04-23 — PATTERNS APPRIS (session 11 — SI-07 tests)
- SI-07 : `test_si_integration.py` (11 tests) + `test_si_guardrails.py` (19 tests) créés
  - Pattern fixture `_make_cfg(tmp_path)` : dict complet sans monkeypatch — plus robuste que monkeypatch `load_config` (pas de pollution entre tests)
  - `_write_obs_file(obs_dir, filename, signals, age_sec)` : helper avec timestamp UTC calculé (`timedelta`) — préférer `age_sec` sur datetime absolue
  - `_reset_cooldowns()` dans `setup_method` : vider `_cooldowns`, `_trigger_counts`, `_trigger_date` (dicts module-level si_utils) pour isolation totale
  - Guard mode A2ABus absent : `patch.dict("sys.modules", {"core.agents.a2a_bus": None})` force `ImportError` dans `_action_retry_coder_once`
  - Guardrail rollback : mock `_run_tests` avec `call_count` dict (closure-safe) — retourne True puis False pour simuler pré/post-patch
  - Test no-git-push : capturer les `cmd` dans `_fake_run`, vérifier qu'aucune liste ne contient `"push"`
  - `_ingest_borgnes()` cherche `b.get("id")` mais borgnes_map stocke `"name"` — retourne `"borgne_inconnu"` si clé absente (comportement OK pour les tests, pas un bug bloquant)
  - 11 tests intégration couvrent : observe+decide dry_run, log_only, notify, ack, approve, fusion, max_age, cooldown, max_trigger_day, mode_1_block, write_ahead
  - 19 tests guardrails couvrent : 9 guards AutoFix, 4 EducatorSI (never modifies, md-only, dedup), 4 Orchestrator (atomic_write, no_retry_infinite, mode3_a2abus, mode_block)
  - Correction : `import time` retiré de test_si_integration (non utilisé) — import conservé uniquement si utilisé

## SESSION 2026-04-23 — PATTERNS APPRIS (session 10 — SI-06 UI)
- SI-06 : `SelfImprovePanel.tsx` créé + 4 fichiers patchés — UI SelfImprove complète
  - `mcp-timeouts.ts` : `si_observe: 10_000` ajouté (SOURCE DE VÉRITÉ timeouts)
  - `main.ts` : import `spawn` + 3 handlers IPC `si:getStatus`, `si:getHistory`, `si:runCommand`
  - `preload.ts` : bloc `si: { getStatus, getHistory, runCommand }` exposé via contextBridge
  - `SelfImprovePanel.tsx` : composant complet (ModeSection + SystemStateSection + MiniLogSection + FullLogModal)
  - `Sidebar.tsx` : badge `pending_count` sur bouton Settings (position relative, ambre, mono 9px)
  - `si:getStatus` : lit config.toml (regex coupling_mode), auto_fix_whitelist.json, observations/ (tri alpha), pending_actions.json
  - `si:getHistory` : parse CSV actions.log (split ','), retourne { timestamp, rule_id, action, status }
  - `si:runCommand` : spawn venv/Scripts/python.exe lcca_si.py + args, timeout 10s, resolve {stdout,stderr,exitCode}
  - Pattern `window as unknown as { lcca: { si: {...} } }` : cast TypeScript pour accès contextBridge typisé
  - Polling 30s dans `SelfImprovePanel` ET dans `Sidebar` (indépendants, pas de store partagé)
  - 0 couleur hardcodée — tout via tokens themes.css (--accent, --bg-surface, --success-dim, etc.)
  - `observer_active = coupling_mode >= 1`, `orchestrator_active = coupling_mode >= 2` (dérivé côté main)
  - Bouton "Observer maintenant" → runCommand('observe') + load() immédiat post-commande
  - Modal log complet : grille 3 colonnes (110px timestamp | 1fr rule+action | 70px badge)
  - Invariant : `SelfImprovePanel` ne modifie PAS `orchestrator_rules.json` ni `auto_fix_whitelist.json` (lecture seule depuis UI)

## SESSION 2026-04-23 — PATTERNS APPRIS (session 9 — SI-05 audit)
- SI-05 : `EducatorSI` (existait déjà) — même pattern que SI-02/SI-03/SI-04
  - `educator.py` : 3 sources (auto-fix/borgnes/manual), déduplication sha256[:16], suggestions .md uniquement
  - `test_si_05_educator.py` : 8 tests (log vide, auto-fix→suggestion, borgnes vide, borgnes→suggestion, dédup, manual, invariant system files, source invalide)
  - `_count_to_confidence()` : statique, seuils 1→faible / 3→moyenne / 10→haute
  - Invariant absolu : EducatorSI ne modifie JAMAIS `orchestrator_rules.json` ni `auto_fix_whitelist.json`
  - Déduplication : `<!-- dedup:{sha256[:16]} -->` en commentaire HTML invisible dans le fichier .md
  - Règle confirmée : avant tout sprint SI-*, vérifier si le code EXISTE déjà (pattern récurrent)
- Tous les engines SelfImprove (SI-01→SI-05) étaient déjà implémentés — sprints restants : SI-06 (UI) + SI-07 (tests)

## SESSION 2026-04-23 — PATTERNS APPRIS (session 8 — SI-04 audit)
- SI-04 : `AutoFixEngine` (existait déjà) — même pattern que SI-02/SI-03
  - `auto_fix.py` : 8 guards en séquence, rollback automatique si tests post-patch échouent
  - `test_si_04_autofix.py` : 14 tests couvrant toutes les guards + missing_import + rollback + auto_push
  - `_add_import_template()` méthode statique : fallback sans libcst, vérifie doublon avant insertion
  - `_compute_patch()` retourne `(None, 0)` pour pattern `coroutine_never_awaited` (STUB V10.5)
  - `_get_latest_signal()` : cherche dans les 5 derniers fichiers `observations/*.json` (tri décroissant)
  - `_check_coverage()` : mode dégradé silencieux si `coverage.json` absent ou fichier non référencé
  - Règle confirmée : avant tout sprint SI-*, vérifier si le code EXISTE déjà

## SESSION 2026-04-22 — PATTERNS APPRIS
- Audit cohérence 002-context.md : ~30 fichiers core/ non documentés détectés par list_directory vs skills
- Workflow audit coverage : lire tests + sources en parallèle (read_multiple_files), analyser les lacunes
- REFACTO-10 identifié : mcp_tool_handlers.py (28.9 KB) = prochain candidat
- llm_generator.py (28.3 KB) = autre candidat REFACTO prioritaire
- orchestrator_medi.py : execute() non testable en CI (D:\MediBot absent) — couverture acceptée via mocking filesystem
- Lors d’une session d’audit, ne pas corriger le code — lire, analyser, documenter uniquement
