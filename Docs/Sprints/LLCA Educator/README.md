# LLCA Educator — Plan de sprints V9.1
<!-- Généré 2026-04-21 — basé sur la review critique LLCA-TrainingFast-review.md -->

## Vue d'ensemble

Le module **EducatorAgent** enrichit la mémoire de LCCA par curation externe
depuis une whitelist de repos GitHub MIT/Apache/BSD.
Il résout le problème du cold-start sans attendre des centaines de sessions utilisateur.

## Dépendances entre sprints

```
ED-01 (P0 — Fondations)
  └── ED-02 (P1 — Robustesse)
        └── ED-03 (P2 — Qualité & rareté)
              └── ED-04 (P2/P3 — Diff, SFT, NL)
```

## Tableau des sprints

| Sprint | Fichier | Priorité | Effort | Prérequis | Statut |
|--------|---------|----------|--------|-----------|--------|
| ED-01 | `sprint-ed-01-fondations-p0.md` | P0 | 1.5j | — | 🏃 À faire |
| ED-02 | `sprint-ed-02-robustesse-p1.md` | P1 | 1j | ED-01 | ⏳ Bloqué |
| ED-03 | `sprint-ed-03-qualite-rarete.md` | P2 | 1j | ED-02 | ⏳ Bloqué |
| ED-04 | `sprint-ed-04-diff-sft-nl.md`   | P2/P3 | 1j | ED-03 | ⏳ Bloqué |

**Effort total estimé : 4.5 jours**

## Corrections P0 adressées (source : review critique)

| Problème | Sprint | Solution |
|----------|--------|----------|
| `print→log` dangereux | ED-01 | Rejet pur (pas de transformation) |
| `run_task` absent | ED-01 | Implémenté + thread async |
| Déduplication absente | ED-01 | Hash SHA-256 avant `skill_lib.add()` |
| Whitelist incohérente | ED-01 | 18 repos vérifiés + pydantic/openai/anthropic |
| AST fragile (SyntaxError) | ED-01 | try/except + fallback contexte brut |
| Fetch séquentiel lent | ED-02 | ThreadPoolExecutor max_workers=5 |
| Licence peu fiable | ED-02 | Fallback lecture fichier LICENSE |
| Pas de cache | ED-02 | Cache JSON TTL 24h |
| Pas de filtre popularité | ED-03 | Stars ≥ 1000 (configurable) |
| Pas de versionning source | ED-03 | commit_hash dans SkillEntry |
| Pas de politique rareté | ED-03 | `deprecate_stale_skills()` |
| Pas d'intégration Training | ED-04 | `export_sft_pairs()` JSONL |
| CLI `main.py` inexistant | ED-04 | NL intent EDUCATOR_RUN/DIFF |

## Fichiers créés / modifiés au total

### Créés
- `core/agents/educator_agent.py` (~450 lignes)
- `tests/test_educator_agent.py` (~270 lignes)
- `Docs/EDUCATOR_README.md`

### Modifiés
- `config.py` (+31 constantes EDUCATOR_*)
- `core/agents/__init__.py` (+export)
- `core/skill_library.py` (+2 champs SkillEntry)
- `core/mcp_tools_schema.py` (+educator_status)
- `core/mcp_tool_handlers.py` (+case educator_status)
- `core/mcp_server.py` (+tool dispatcher)
- `core/nl_intent.py` (+EDUCATOR_RUN, EDUCATOR_DIFF)
- `core/nl_parser.py` (+patterns NL)
- `core/nl_orchestrator.py` (+2 cases)
- `tests/test_mcp_server.py` (12 → 13 tools)
- `tests/test_skill_library.py` (+3 tests rétrocompat)
- `tests/test_nl_parser.py` (+3 tests)

## Règles de mise à jour

À la fin de chaque sprint, mettre à jour les skills dans `.claude-skills/` :
- **001** : patterns du sprint terminé
- **003** : arborescence (nouveaux fichiers)
- **004** : sprint marqué TERMINÉ, prochain sprint identifié
