# EvalLoop V3 — Benchmark Curriculum LCCA

## Ce que fait EvalLoop V3
- Evalue la qualite des reponses de LCCA sur des questions progressives
- Adapte la difficulte selon les performances (curriculum par paliers)
- Injecte les corrections JudgeClaude dans MemoryEngine (lcca_context)
- Mesure les metriques de sante Ollama (temps, longueur, taux erreur)

## Limitations V3 (angles morts documentes)

### SYS-01 : Probe sans memoire active
EvalLoop V3 est un **benchmark sans memoire active**.
Le probe ne lit pas lcca_context pendant l'evaluation -- les skills deja injectes
ne sont pas fournis au modele comme contexte.
Raison : contention VRAM sur Quadro M2000M 4GB (ChromaDB embeddings + Ollama 3b).
Statut : reporte V4.

### SYS-02 : Retrogradation desactivee
La montee de palier est unidirectionnelle en V3.
Flag `retrograde_enabled = false` dans eval_config.toml.
Activer en V4 si stagnation observee.

### SYS-04 : Detection d'erreurs recurrentes desactivee
Les erreurs repetees sur une meme question ne generent pas d'alerte.
Flag `track_error_patterns = false` dans eval_config.toml.

## Regles d'utilisation

### Payload DistillEngine -- regle stricte
Le payload injecte dans MemoryEngine contient une seule cle textuelle : `"content"`.
Ne jamais ajouter `"code"`, `"snippet"`, `"error"`, `"text"` -- ces cles sont
prioritaires dans extract_content() et detourneraient silencieusement l'indexation.

### Import et sys.path
EvalLoop ne peut pas etre importe sans sys.path configure sur la racine LCCA.
Point d'entree : `lcca_eval.py` (configure sys.path automatiquement).
Tests : `tests/conftest.py` configure sys.path (existant).
