# SPEC EvalLoop — EVAL-04 : DistillEngine → SkillLibrary
**Version** : 1.0
**Date** : 2026-04-23
**Statut** : DRAFT
**Dépendances** : EVAL-01 (dataclasses), EVAL-03 (JudgeScore)

---

## 1. Objectif du sprint

Implémenter la **Phase 3 — DISTILL** :

- Lire `scores.jsonl` d'une session
- Filtrer les scores ≥ `min_inject_score`
- Formater chaque `improved_answer` en `.md` LCCA avec frontmatter YAML
- Dédupliquer par sha256[:16] (même pattern Educator)
- Injecter via `SkillLibrary.add_skill()`

Ce sprint clôt le cycle probe → judge → distill.

---

## 2. Fichiers créés / modifiés

| Fichier | Action |
|---|---|
| `EvalLoop/engines/distill_engine.py` | Créé — distillation + injection |
| `core/skill_library.py` | Aucune modification — `add_skill()` suffisant |

---

## 3. `distill_engine.py`

### Interface publique

```python
class DistillEngine:
    def __init__(self, config: dict, session_dir: Path, skill_lib_path: Path):
        # skill_lib_path : chemin vers le dossier SkillLibrary LCCA
        ...

    def run(
        self,
        min_score: float | None = None,
        questions_index: dict[str, BenchQuestion] | None = None,
    ) -> list[DistilledSkill]:
        """Distille les scores de la session courante.
        
        min_score : override config["scoring"]["min_inject_score"] si fourni.
        questions_index : pour enrichir le frontmatter (domain, palier, tags).
        Retourne la liste des DistilledSkill injectés (sans les dédupliqués skippés).
        """

    def _load_scores(self) -> list[JudgeScore]:
        """Charge scores.jsonl. Retourne [] si absent."""

    def _format_skill_md(
        self,
        score: JudgeScore,
        question: BenchQuestion | None,
    ) -> str:
        """Formate en .md LCCA avec frontmatter YAML."""

    def _sha256_content(self, content: str) -> str:
        """sha256(content.encode()).hexdigest()[:16]"""

    def _is_duplicate(self, content_hash: str) -> bool:
        """Vérifie si le hash est déjà présent dans un skill existant SkillLibrary.
        Cherche le commentaire <!-- dedup:{hash} --> dans les fichiers .md du dossier."""

    def _inject(self, skill_md: str, score: JudgeScore, question: BenchQuestion | None) -> None:
        """Appelle SkillLibrary.add_skill() avec source_type='evalloop'."""
```

---

## 4. Format `.md` du skill distillé

```markdown
---
source: evalloop/{question_id}
domain: {domain}
palier: {palier}
difficulty: {difficulty}
score: {score}
judge: {judge_id}
session: {session_name}
date: {YYYY-MM-DD}
tags: [{tag1}, {tag2}]
---

{improved_answer}

<!-- dedup:{sha256[:16]} -->
```

Exemple concret :

```markdown
---
source: evalloop/py-p0-001
domain: python_core
palier: 0
difficulty: medium
score: 0.88
judge: claude-sonnet-4-6
session: 2026-04-23_21-00
date: 2026-04-23
tags: [OOP, metaclass, memory]
---

# `__new__` vs `__init__` en Python

En Python, la création d'un objet passe par deux étapes distinctes...

[contenu rédigé par le juge]

<!-- dedup:a3f8c2d91b4e0f7a -->
```

---

## 5. Appel `SkillLibrary.add_skill()`

```python
from core.skill_library import SkillLibrary

skill_lib = SkillLibrary(skill_lib_path)
skill_lib.add_skill(
    content=skill_md,
    source_type="evalloop",
    metadata={
        "question_id": score.question_id,
        "domain": score.domain,
        "palier": score.palier,
        "score": score.score,
        "judge": score.judge,
        "session": session_name,
    }
)
```

Le `source_type = "evalloop"` est distinct de `"github"` (EducatorAgent) — permet de filtrer par source dans les recherches SkillLibrary.

---

## 6. Règles DistillEngine

- `min_score` : si `None`, utiliser `config["scoring"]["min_inject_score"]` (défaut 0.75)
- `inject_recommended=False` sur un JudgeScore → skip, même si score >= min_score
  - Ratio : le juge a explicitement signalé que la réponse n'est pas utile
- `improved_answer` vide (`""`) → skip (pas de contenu à injecter)
- Déduplication obligatoire avant injection : sha256[:16] sur le contenu brut `improved_answer`
- Ordre d'injection : scores décroissants (meilleure réponse en premier)
- Rapport distillation : log `INFO` pour chaque skill injecté, `DEBUG` pour chaque skip
- Sessions immuables : `scores.jsonl` jamais modifié par DistillEngine

---

## 7. Déduplication entre sessions

Problème : si deux sessions consécutives obtiennent le même `improved_answer` pour la même question, on ne doit pas injecter deux fois.

Solution : `<!-- dedup:{hash} -->` en fin de chaque skill .md. `_is_duplicate()` scanne les fichiers `.md` du dossier SkillLibrary pour détecter le hash.

Optimisation V1 : scan exhaustif acceptable (SkillLibrary < 1000 fichiers). V2+ : index en mémoire.

---

## 8. Tests attendus — `test_eval_04_distill.py` (~18 tests)

- `_format_skill_md` : frontmatter YAML correct (source, domain, palier, score, judge, date)
- `_format_skill_md` : improved_answer inclus dans le contenu
- `_format_skill_md` : commentaire `<!-- dedup:{hash} -->` présent
- `_sha256_content` : hash 16 caractères hexadécimaux
- `_sha256_content` : deux contenus identiques → même hash
- `_sha256_content` : deux contenus différents → hash différent (probabilistique)
- `_is_duplicate` : hash absent dans SkillLibrary → False
- `_is_duplicate` : hash présent dans un fichier SkillLibrary → True
- `_load_scores` : scores.jsonl valide → liste JudgeScore
- `_load_scores` : scores.jsonl absent → []
- `run()` : score < min_score → skippé
- `run()` : inject_recommended=False → skippé même si score >= min_score
- `run()` : improved_answer vide → skippé
- `run()` : score >= min_score + inject=True → add_skill appelé
- `run()` : doublon détecté → add_skill non appelé
- `run()` : min_score override → utilise la valeur fournie
- `run()` : retourne uniquement les skills effectivement injectés
- `run()` : injection ordonnée par score décroissant
