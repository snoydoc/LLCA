# -*- Sprint 11 — TASK-11-03 -*-
# LCCA V7.1 — ProjectScaffolder : LLM Scaffold Generator

## Métadonnées
| Champ        | Valeur                          |
|--------------|---------------------------------|
| Sprint       | 11                              |
| Task         | TASK-11-03                      |
| Version      | V7.1                            |
| Statut       | À faire                         |
| Priorité     | Haute                           |
| Dépendance   | TASK-11-01, TASK-11-02          |
| Fichier cible| `core/scaffold_generator.py`    |

---

## Objectif

Créer `core/scaffold_generator.py` : module qui utilise Ollama (qwen2.5-coder:14b)
pour générer le contenu de chaque fichier d'un projet scaffoldé,
avec fallback stub si Ollama est indisponible.

---

## Contexte

Quand `ProjectScaffolder` reçoit un `ScaffoldIntent`, il doit produire
du contenu pour chaque fichier. Ce contenu provient soit du LLM, soit d'un
template statique (stub). C'est le rôle de `ScaffoldGenerator`.

---

## Interface publique

```python
class ScaffoldGenerator:
    def __init__(self, llm=None) -> None: ...

    def generate_project_plan(self, intent: ScaffoldIntent) -> list[ScaffoldFile]:
        """
        Demande au LLM de planifier l'arborescence du projet
        (liste de fichiers à créer + description de chaque fichier).
        Retourne une liste de ScaffoldFile avec contenu vide.
        """

    def generate_file_content(
        self,
        scaffold_file: ScaffoldFile,
        project_context: str,
    ) -> str:
        """
        Génère le contenu d'un fichier via Ollama.
        Retourne un stub si Ollama est indisponible.
        """
```

---

## Prompt LLM — Phase 1 : planification

### System prompt

```
You are an expert Python project architect.
Given a project description, return a JSON list of files to create.
Respond ONLY with a valid JSON array. No markdown. No explanations.

Schema:
[
  {
    "relative_path": "main.py",
    "description": "Entry point of the application",
    "is_entrypoint": true
  },
  ...
]

Rules:
- Always include a README.md
- Always include at least one test file in tests/
- Keep the structure minimal and focused
- Use snake_case for Python files
- Max 8 files per project
```

### User prompt

```
Project name: {project_name}
Description: {description}
Target directory: {target_dir}
```

---

## Prompt LLM — Phase 2 : génération de contenu

### System prompt

```
You are an expert Python developer.
Generate the complete content for the file described below.
Return ONLY the file content. No explanations. No markdown fences.
The code must be production-ready, with docstrings and type hints.
```

### User prompt

```
Project: {project_name}
File: {relative_path}
Description: {description}
Project context (other files):
{project_context}
```

---

## Fallback stub

Si Ollama est indisponible, générer des fichiers minimalistes :

| Fichier        | Contenu stub                                         |
|----------------|------------------------------------------------------|
| `main.py`      | `# {project_name}\n# TODO: implement\n\nif __name__ == '__main__':\n    pass\n` |
| `README.md`    | `# {project_name}\n\n{description}\n`                |
| `tests/test_*.py` | `# Tests pour {project_name}\nimport pytest\n`    |
| Autres `.py`   | `# {relative_path}\n# TODO: implement\n`             |

---

## Gestion du cache LLM

- Utiliser `LLM_CACHE_DIR` existant (`transactions/.llm_cache`)
- Clé de cache : `sha256(project_name + description + relative_path)`
- TTL : pas de TTL (cache permanent, invalidation manuelle)

---

## Critères d'acceptance

- [ ] `generate_project_plan()` retourne une liste cohérente de fichiers
- [ ] `generate_file_content()` produit du code Python valide (testable avec `compile()`)
- [ ] Fallback stub activé si Ollama retourne HTTP 500 ou timeout
- [ ] Cache utilisé si même description + même fichier déjà généré
- [ ] README.md toujours inclus dans le plan
- [ ] Au moins un fichier de test toujours inclus

---

## Tests à écrire

Fichier : `tests/test_scaffold_generator.py`

```
test_generate_project_plan_returns_files()
test_generate_project_plan_includes_readme()
test_generate_project_plan_includes_tests()
test_generate_file_content_valid_python()
test_fallback_stub_on_ollama_error()
test_cache_hit_skips_llm_call()
```
