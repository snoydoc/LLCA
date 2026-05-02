# -*- Sprint 11 — TASK-11-05 -*-
# LCCA V7.1 — ProjectScaffolder : Intégration & Tests end-to-end

## Métadonnées
| Champ        | Valeur                                         |
|--------------|------------------------------------------------|
| Sprint       | 11                                             |
| Task         | TASK-11-05                                     |
| Version      | V7.1                                           |
| Statut       | À faire                                        |
| Priorité     | Haute                                          |
| Dépendance   | TASK-11-01, 02, 03, 04                         |
| Fichiers     | `tests/test_scaffold_e2e.py`, `check_env.py`   |

---

## Objectif

Valider l'intégration complète du pipeline scaffold de bout en bout,
mettre à jour `check_env.py` avec les nouvelles vérifications V7.1,
et documenter les commandes de test humain.

---

## Tests end-to-end

Fichier : `tests/test_scaffold_e2e.py`

### Cas de test principaux

```python
def test_e2e_scaffold_simple_project(tmp_path):
    """
    Commande NL → NLParser → ScaffoldIntent → ProjectScaffolder → fichiers sur disque.
    Vérifie que tous les fichiers existent et sont syntaxiquement valides.
    """

def test_e2e_scaffold_with_ollama_stub(tmp_path):
    """
    Même test avec LLM mocké (stub), sans Ollama réel.
    Doit produire des fichiers stubs valides.
    """

def test_e2e_scaffold_rollback_on_error(tmp_path):
    """
    Simule une erreur à mi-scaffold (fichier 3/5 échoue).
    Vérifie que le rollback supprime les 2 premiers fichiers créés.
    """

def test_e2e_scaffold_dry_run(tmp_path):
    """
    dry_run=True → aucun fichier créé, NLResult.success=True,
    NLResult.dry_run=True, plan affiché.
    """

def test_e2e_full_command_file_merger(tmp_path):
    """
    Commande : "Crée une application dans {tmp_path}/FileMerge
               qui merge des fichiers .MD en un seul fichier"
    Vérifie :
    - Dossier FileMerge créé
    - Au moins un .py présent
    - README.md présent
    - Syntaxe Python valide sur tous les .py
    """
```

---

## Mise à jour `check_env.py`

Ajouter une section **#16 — ProjectScaffolder** :

```python
# Section 16 — ProjectScaffolder V7.1
def check_scaffolder():
    results = []
    try:
        from core.scaffolder import ProjectScaffolder, ScaffoldIntent, ScaffoldFile
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "TestScaffold"
            intent = ScaffoldIntent(
                project_name="TestScaffold",
                target_dir=target,
                description="test project",
                files=[ScaffoldFile(relative_path="main.py", content="# test\n")],
                raw_command="test",
            )
            scaffolder = ProjectScaffolder()
            result = scaffolder.scaffold(intent)
            assert result.success, f"Scaffold échoué : {result.error}"
            assert (target / "main.py").exists(), "main.py non créé"
            results.append(("[OK]", "ProjectScaffolder — scaffold + rollback"))
    except Exception as e:
        results.append(("[KO]", f"ProjectScaffolder — {e}"))
    return results
```

---

## Commandes de test humain (REPL)

Une fois le sprint implémenté, ces commandes doivent fonctionner :

```
# Test 1 — Scaffolding complet
▶ Crée une application dans D:\LLMCodeAgent\CodingTests\FileMerge qui merge des fichiers .MD

# Test 2 — Création de dossier simple
▶ Crée un dossier MonProjet dans D:\LLMCodeAgent\CodingTests

# Test 3 — Dry run
▶ dry
▶ Crée une application Flask dans D:\LLMCodeAgent\CodingTests\MonAPI

# Test 4 — Projet avec sous-dossiers
▶ Crée un projet Python avec tests dans D:\LLMCodeAgent\CodingTests\Utils
```

---

## Critères d'acceptance globaux V7.1

| # | Critère                                                                 | Statut |
|---|-------------------------------------------------------------------------|--------|
| 1 | `scaffold_project` reconnu par NLParser (Ollama + fallback)             | ☐      |
| 2 | `create_directory` reconnu par NLParser                                 | ☐      |
| 3 | `target_dir` extrait depuis chemins Windows absolus                     | ☐      |
| 4 | `ProjectScaffolder.scaffold()` crée l'arborescence sur disque           | ☐      |
| 5 | Rollback supprime les fichiers créés en cas d'erreur mi-parcours        | ☐      |
| 6 | `dry_run` retourne le plan sans écriture                                | ☐      |
| 7 | Sécurité : path traversal et dossiers système bloqués                   | ☐      |
| 8 | LLM génère le contenu de chaque fichier (stub si indisponible)          | ☐      |
| 9 | Pipeline existant LCCAV5Fusion non cassé (check_env.py : 56/58 → 58/58)| ☐      |
|10 | check_env.py section #16 : scaffolder passe [OK]                       | ☐      |
