# SPEC EvalLoop — EVAL-06 : CLI lcca_eval.py + Rapport
**Version** : 1.0
**Date** : 2026-04-23
**Statut** : DRAFT
**Dépendances** : EVAL-02, EVAL-03, EVAL-04, EVAL-05

---

## 1. Objectif du sprint

Implémenter le **CLI `lcca_eval.py`** (racine projet) et le **rapport de session Markdown**.

Le CLI est le seul point d'entrée pour tout EvalLoop. Il orchestre les engines
dans l'ordre correct et expose les 6 commandes principales.

---

## 2. Fichiers créés

| Fichier | Rôle |
|---|---|
| `lcca_eval.py` | CLI racine EvalLoop |
| `EvalLoop/engines/session_reporter.py` | Générateur de session_report.md |

---

## 3. Interface CLI

```bash
# 1. Générer / enrichir les benchmarks pour un domaine
python lcca_eval.py gen-bench --domain python_core --palier 0 --count 5

# 2. Probe : soumettre les questions du palier courant à LLCA
python lcca_eval.py probe --domain python_core --session 2026-04-23

# 3. Judge : scorer les réponses via Claude
python lcca_eval.py judge --session 2026-04-23 --judge claude

# 4. Distill : injecter les meilleures réponses dans SkillLibrary
python lcca_eval.py distill --session 2026-04-23 --min-score 0.75

# 5. Rapport de session
python lcca_eval.py report --session 2026-04-23

# 6. Statut curriculum (paliers courants par domaine)
python lcca_eval.py status
```

---

## 4. Sous-commandes détaillées

### `gen-bench`

```
Arguments :
  --domain DOMAIN     Domaine cible (python_core|architecture|...)
  --palier N          Palier à enrichir (défaut : palier courant du domaine)
  --count N           Nombre de questions à générer (défaut : 5)

Sortie :
  [GEN] python_core palier 0 — 5 questions générées → benchmarks/python_core/palier_0.json
  [GEN] Doublons ignorés : 0
  [GEN] Total questions fichier : 10
```

### `probe`

```
Arguments :
  --domain DOMAIN     Domaine cible (ou "all" pour tous les domaines actifs)
  --session LABEL     Label session (YYYY-MM-DD ou YYYY-MM-DD_HH-MM)
                      Si absent : généré automatiquement (datetime now)
  --questions N       Nombre de questions par domaine (défaut : config questions_per_palier)

Sortie :
  [PROBE] Session : sessions/2026-04-23_21-00/
  [PROBE] Domaine : python_core | Palier : 0 | 5 questions
  [PROBE] py-p0-001 ✓ (4230 ms)
  [PROBE] py-p0-002 ✓ (3810 ms)
  ...
  [PROBE] Terminé — 5/5 réponses | responses.jsonl écrit
```

### `judge`

```
Arguments :
  --session LABEL     Label session (ou "latest" pour la dernière session)
  --judge JUDGE       Juge à utiliser : "claude" | "all" (défaut : config active)

Sortie :
  [JUDGE] Session : sessions/2026-04-23_21-00/
  [JUDGE] Juge : claude-sonnet-4-6
  [JUDGE] py-p0-001 → score 0.82 (inject: ✓)
  [JUDGE] py-p0-002 → score 0.61 (inject: ✗ score < 0.75)
  ...
  [JUDGE] Terminé — 5/5 scorés | scores.jsonl écrit
  [JUDGE] Score moyen palier 0 : 0.71 (seuil unlock : 0.70) → PALIER 1 DÉBLOQUÉ ✓
```

### `distill`

```
Arguments :
  --session LABEL     Label session
  --min-score FLOAT   Override seuil d'injection (défaut : config 0.75)

Sortie :
  [DISTILL] Session : sessions/2026-04-23_21-00/
  [DISTILL] py-p0-001 → INJECTÉ (score 0.82)
  [DISTILL] py-p0-002 → SKIP (score 0.61 < 0.75)
  [DISTILL] py-p0-003 → SKIP (doublon détecté)
  ...
  [DISTILL] Terminé — 3 skills injectés / 5 évalués
```

### `report`

```
Arguments :
  --session LABEL     Label session

Sortie : génère sessions/{label}/session_report.md et l'affiche
```

### `status`

```
Sortie :
  [STATUS] Curriculum EvalLoop — état actuel
  ┌─────────────────┬────────┬──────────────┬─────────────────┐
  │ Domaine         │ Palier │ Score actuel │ Prochain seuil  │
  ├─────────────────┼────────┼──────────────┼─────────────────┤
  │ python_core     │   2    │    0.82      │ 0.70 (palier 3) │
  │ architecture    │   0    │    —         │ 0.70 (palier 1) │
  │ debugging       │   0    │    —         │ 0.70 (palier 1) │
  │ algorithms      │   0    │    —         │ 0.70 (palier 1) │
  │ refactoring     │   0    │    —         │ 0.70 (palier 1) │
  │ llca_meta       │   0    │    —         │ 0.70 (palier 1) │
  └─────────────────┴────────┴──────────────┴─────────────────┘
```

---

## 5. `session_reporter.py`

### Format `session_report.md`

```markdown
# Rapport EvalLoop — Session 2026-04-23_21-00

**Date** : 2026-04-23 21:00:00
**Domaine** : python_core | **Palier** : 0
**Modèle LLCA** : qwen2.5-coder:3b
**Juge** : claude-sonnet-4-6

---

## Résumé

| Métrique | Valeur |
|---|---|
| Questions posées | 5 |
| Réponses obtenues | 5 |
| Score moyen | 0.72 |
| Score min | 0.55 |
| Score max | 0.88 |
| Skills injectés | 3 |
| Durée probe totale | 21.4s |
| Palier débloqué | ✓ Palier 1 débloqué |

---

## Détail par question

### py-p0-001 — Score : 0.88 ✓ INJECTÉ

**Question** : Qu'est-ce que le GIL en Python ? ...

**Forces** :
- Définition correcte du GIL
- Distinction I/O vs CPU-bound claire

**Faiblesses** :
- Pas de mention de multiprocessing comme alternative

**Durée réponse LLCA** : 4230 ms

---

### py-p0-002 — Score : 0.61 ✗ SKIP

...

---

## Progression Curriculum

python_core palier 0 → score moyen 0.72 ≥ 0.70 → **Palier 1 débloqué** ✓
```

### Interface publique

```python
class SessionReporter:
    def __init__(self, session_dir: Path):
        ...

    def generate(
        self,
        responses: list[ProbeResponse],
        scores: list[JudgeScore],
        distilled: list[DistilledSkill],
        palier_unlocked: bool,
        palier_current: int,
    ) -> Path:
        """Génère session_report.md dans session_dir. Retourne le chemin."""
```

---

## 6. Résolution de session par label

```
"2026-04-23"        → sessions/2026-04-23_*/ (première trouvée, tri alpha)
"2026-04-23_21-00"  → sessions/2026-04-23_21-00/ (exact)
"latest"            → sessions/ dernier dossier (tri alpha décroissant)
```

Si le dossier de session n'existe pas → erreur explicite + exit(1).

---

## 7. Règles CLI

- `argparse` stdlib uniquement (pas de click, typer)
- Exit code 0 = succès, 1 = erreur (fichier manquant, API indispo), 2 = usage incorrect
- Toutes les sorties sur `sys.stdout` sauf erreurs fatales (`sys.stderr`)
- `--help` sur chaque sous-commande (argparse natif)
- Import tardif des engines (évite import circulaire au démarrage)
- `lcca_eval.py` autonome : `sys.path.insert(0, str(Path(__file__).parent))` pour import EvalLoop

---

## 8. Tests attendus — `test_eval_06_cli.py` (~15 tests)

- `gen-bench` : args parsés + BenchGenerator appelé + sortie console correcte
- `probe` : session créée automatiquement si absent
- `probe` : `--domain all` → tous les domaines actifs config
- `judge` : `--session latest` → dernier dossier session
- `judge` : juge indisponible → exit code 1 + message explicite
- `distill` : `--min-score` override correct
- `report` : session_report.md généré
- `status` : tableau curriculum affiché
- Session resolve : "2026-04-23" → premier dossier correspondant
- Session resolve : "latest" → dernier dossier
- Session resolve : inexistante → exit 1 + message
- `SessionReporter.generate()` : frontmatter correct, toutes les sections présentes
- `SessionReporter.generate()` : palier_unlocked=True → message unlock dans rapport
- `SessionReporter.generate()` : 0 scores → rapport partiel (probe only)
- Import tardif engines : `import lcca_eval` ne plante pas si Ollama absent
