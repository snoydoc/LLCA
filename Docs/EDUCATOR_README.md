# LLCA-Educator — Agent de curation externe

## Rôle

EducatorAgent est un agent satellite V9.1 qui enrichit la mémoire de LCCA
en collectant du code exemplaire depuis une whitelist de repos GitHub open-source
(MIT, Apache-2.0, BSD). Il filtre, déduplique et ingère les snippets dans
`lcca_context` pour améliorer la pertinence du contexte RAG.

## Activation

```python
# config.py
EDUCATOR_ENABLED       = True
EDUCATOR_DRY_RUN       = False         # Autoriser l'écriture en mémoire
EDUCATOR_GITHUB_TOKEN  = "ghp_..."     # Recommandé pour dépasser 60 req/h
EDUCATOR_STARS_THRESHOLD = 1000        # Filtrer les repos peu populaires
```

## Commandes NL

| Commande | Intent | Effet |
|---|---|---|
| "lance la curation" | `EDUCATOR_RUN` | Démarre la curation en arrière-plan |
| "run educator" | `EDUCATOR_RUN` | Idem (anglais) |
| "diff curation" | `EDUCATOR_DIFF` | Rapport sans écriture |
| "rapport curation" | `EDUCATOR_DIFF` | Idem (français) |

## Outil MCP

```json
{ "name": "educator_status" }
```
Retourne le statut de la dernière curation (repos traités, skills ingérés, erreurs).

## Whitelist

18 repos MIT/Apache/BSD sélectionnés (pydantic, fastapi, requests, numpy, anthropic-sdk…).
Liste complète dans `core/agents/educator_agent.py : _WHITELIST`.

## Politique de licences

- Licences acceptées : MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause
- Fallback : lecture du fichier LICENSE si l'API échoue
- Refus si GPL détecté, même sur un repo MIT
- Cache TTL : `EDUCATOR_CACHE_TTL_HOURS` (défaut 24h)

## Politique de rareté

Les skills externes non utilisés après `EDUCATOR_SKILL_DEPRECATION_DAYS` jours
(défaut 30) sont marqués `deprecated` via `deprecate_stale_skills()`.

## Mode diff (ED-04)

```python
diff = agent.run_diff()
# {
#   "new_skills"       : [...],  # skill_ids à ingérer
#   "stale_skills"     : [...],  # skills externes inutilisés
#   "repos_checked"    : 18,
#   "files_would_fetch": 540,
#   "errors"           : [],
# }
```

## Export SFT

```python
count = agent.export_sft_pairs()
# → training_data/educator/sft_pairs.jsonl
# Format : {"instruction": "Écris une fonction Python ...", "response": "<code>", "source": "external"}
```

## Sandbox check (opt-in)

```python
# config.py
EDUCATOR_SANDBOX_CHECK = True   # Lent mais vérifie l'exécutabilité de chaque skill
```

## Sprints

| Sprint | Contenu |
|---|---|
| ED-01 | Fondations P0 (run_task, filtres 7 règles, dédup hash) |
| ED-02 | Robustesse P1 (retry backoff, persistance hashes, repos_filter) |
| ED-03 | Qualité P2 (stars, commit hash, cache TTL, SkillEntry, tool MCP) |
| ED-04 | Diff, SFT, NL intent, sandbox check |
