# Addendum de Révision — SPEC EvalLoop (EVAL-00 à EVAL-07)
**Date** : 2026-04-24  
**Auteur** : Revue externe LCCA  
**Statut** : DRAFT — À intégrer avant implémentation EVAL-01

---

## 1. Executive Summary

Les specs EvalLoop sont **architecturalement solides** et bien structurées (paliers, séparation probe/judge/distill, immutabilité des sessions). Cependant, **trois problèmes critiques** doivent être résolus avant le sprint EVAL-01, sous peine de construire une évaluation biaisée sur un modèle déjà identifié comme défaillant (hallucination de patch, routing incorrect).

---

## 2. Points Forts ✅

| Aspect | Commentaire |
|--------|-------------|
| **Séparation des phases** | Probe → Judge → Distill est le bon pattern. L'immutabilité des sessions (`responses.jsonl` append-only) est essentielle pour la traçabilité. |
| **Paliers curriculum** | Le découpage 0→5 avec seuil d'unlock est pertinent pour un agent apprenant. Le fallback palier 0 est bien pensé. |
| **Benchmarks initiaux** | Les questions palier 0 (fondations) écrites à la main sont de bonne qualité. Ne pas générer les paliers 0/1 par LLM est le bon choix. |
| **Déduplication sha256** | Réutilise le pattern EducatorAgent. Cohérent. |
| **Mode dégradé juge** | Le graceful degradation quand Claude est indisponible est correctement spécifié. |
| **Écriture atomique** | `.tmp → Path.replace()` pour `eval_state.json` respecte la règle T-14. |

---

## 3. Problèmes Critiques 🔴 (Blockers — corriger avant EVAL-01)

### CRIT-01 : Le modèle probe est le modèle défaillant
**Problème** : `probe_engine.py` utilise `qwen2.5-coder:3b` pour répondre aux questions. Or ce modèle a démontré des **hallucinations de patch** et un **routing incorrect** (il génère du code alors qu'il devrait classifier).  
**Impact** : EvalLoop va mesurer la performance d'un modèle qu'on sait dysfonctionnel, produisant des données d'apprentissage (`improved_answer`) potentiellement basées sur des réponses hallucinées. C'est un **feedback loop toxique**.  
**Correction proposée** :
- Ajouter un paramètre `probe_model` dans `eval_config.toml` découplé du modèle de production LCCA.
- Documenter explicitement que EvalLoop peut (et doit) être exécuté avec différents modèles pour comparer leurs courbes d'apprentissage.
- Prévoir un `model_card` dans `ProbeResponse` pour tracker quelle version de LLCA a été évaluée.

### CRIT-02 : Dépendance critique à une API externe payante et "américaine"
**Problème** : Le juge par défaut est Claude (Anthropic API). Cela crée :
1. Une dépendance réseau externe pour un système censé être **100% offline** (règle LCCA)
2. Un coût récurrent non quantifié (chaque session = N appels API × tokens)
3. Une dépendance "américaine" contraire à la contrainte projet "non-American solutions"  
**Impact** : Si la clé API expire, le système d'évaluation s'effondre (même le mode dégradé skip la distill).  
**Correction proposée** :
- **V1 offline** : Ajouter `JudgeLocal` (Ollama critique) comme juge par défaut, même si moins précis. Claude devient optionnel (`--judge claude` pour calibration croisée).
- Quantifier le coût estimé par session dans la spec (ex: 5 questions × ~2k tokens × 2 passages = ~20k tokens/session).
- Prévoir un `judge_local.py` utilisant un modèle 7B en RAM (CPU) pour le scoring. Le prompt de scoring est plus simple que la génération de code — un 7B local peut le faire.

### CRIT-03 : Le bench_generator alimente le biais du modèle 3B
**Problème** : `bench_generator.py` utilise Ollama local (3B) pour générer des questions palier 2+. Un modèle 3B produira des questions de qualité médiocre, avec des ambiguïtés, des erreurs de fait, ou des questions hors sujet.  
**Impact** : Mauvaises questions → mauvaises réponses → mauvais skills injectés.  
**Correction proposée** :
- Restreindre la génération automatique aux paliers 2+ **uniquement après** que le juge externe ait validé un palier inférieur.
- Ajouter une étape `validate` humaine (ou semi-automatique) : les questions générées sont écrites en `.json` mais marquées `"status": "draft"` jusqu'à revue.
- Alternative : utiliser un template system + variation paramétrique plutôt que de la génération libre par LLM.

---

## 4. Problèmes Majeurs 🟠 (À corriger avant EVAL-03)

### MAJ-01 : Pas de mécanisme de routing dans le probe
Le prompt système du probe est unique :
Tu es LCCA, un assistant expert en développement Python.
Or LCCA est **hybride** (Router 3B / Coder 7B / Critic 7B). Le probe évalue un modèle unique comme s'il représentait tout le système.  
**Suggestion** : Ajouter un mode `probe_mode = "monolithic" | "orchestrated"` :
- `monolithic` : comportement actuel (pour benchmark rapide)
- `orchestrated` : le probe passe par l'orchestrateur réel de LCCA, évaluant le système complet (routing + coder + critic)

### MAJ-02 : Le prompt système force le français sur un modèle coder anglophone
`qwen2.5-coder:3b` est entraîné principalement sur du code et de l'anglais. Forcer le français dans le system prompt peut dégrader la qualité des réponses techniques (moins de tokens d'entraînement FR pour le vocabulaire technique).  
**Suggestion** : Tester A/B :
- Prompt FR vs Prompt EN avec réponse FR demandée
- Ou laisser le modèle répondre dans sa langue de force (EN) et traduire post-probe si besoin

### MAJ-03 : `improved_answer` du juge risque d'être trop long pour SkillLibrary
La spec demande 200–600 mots en Markdown. Si 5 questions par palier × 6 domaines = 30 skills/session, et que chaque skill fait ~500 mots, la SkillLibrary va gonfler rapidement.  
**Suggestion** : Ajouter une limite de taille skill (`max_skill_tokens` dans config) et un mécanisme de compaction (le juge produit une version "longue" pour le rapport et une "compacte" pour l'injection).

### MAJ-04 : Pas de gestion de la mémoire contextuelle entre questions
`probe_engine.py` envoie chaque question indépendamment (`_probe_one`). LLCA n'a pas de mémoire d'une question à l'autre dans la même session.  
**Impact** : Impossible d'évaluer si LLCA "apprend" au fil d'une session (curriculum adaptatif).  
**Suggestion** : Prévoir un mode `contextual = true/false` dans `eval_config.toml`. Si true, les réponses précédentes sont injectées dans le contexte (avec un résumé) pour simuler une session de travail réelle.

### MAJ-05 : Le scoring est scalaire (0.0–1.0) sans granularité
Un score unique masque les compétences partielles. Ex: LLCA peut être excellent en architecture (0.9) mais nul en debugging (0.3), pour un score moyen de 0.6.  
**Suggestion** : Le `JudgeScore` devrait inclure un dictionnaire de sous-scores :
```python
sub_scores: dict[str, float]  # {"exactitude": 0.8, "clarté": 0.6, "exemples": 0.9}
Cela permettrait à DistillEngine d'injecter des skills partiels (ex: "bonne explication mais mauvais exemple").
5. Questions Ouvertes ❓ (À décider avant EVAL-02)
| ID       | Question                                                                                    | Impact                                                           |
| -------- | ------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| **Q-01** | Quel est le budget API mensuel alloué au juge Claude ?                                      | Détermine si le mode local est obligatoire ou optionnel.         |
| **Q-02** | `SkillLibrary.add_skill()` existe-t-il déjà dans `core/skill_library.py` ?                  | La spec EVAL-04 suppose son existence sans le définir.           |
| **Q-03** | Le modèle 7B (Coder) sera-t-il disponible pour le probe, ou seulement le 3B ?               | Détermine si on évalue le vrai LCCA ou seulement le chatbot.     |
| **Q-04** | Faut-il versionner `eval_state.json` dans git, ou est-ce un artefact local uniquement ?     | Impact sur la règle `auto_push = false`.                         |
| **Q-05** | Que se passe-t-il si le même `improved_answer` est généré pour deux questions différentes ? | Collision de hash sha256\[:16] possible (bien que peu probable). |
6. Suggestions d'Amélioration 🟡 (Nice-to-have, post-V1)
Métriques de probe : Ajouter tokens_generated, tokens_per_second, ram_usage_mb dans ProbeResponse pour corréler qualité et performance hardware.
Juge auto-évalué : Pour les paliers 0–1, un script de validation automatique (regex sur concepts attendus) pourrait remplacer le juge LLM pour 80% des cas, réduisant les coûts API.
Dashboard texte : lcca_eval.py status pourrait afficher un graphique ASCII des progressions (sparklines) pour visualiser l'apprentissage.
Cross-validation juge : Quand plusieurs juges sont actifs, stocker les écarts de score (ex: Claude 0.8 vs Local 0.4) comme métrique de divergence.
7. Checklist de Révision Prioritaire
Avant de valider EVAL-00 (overview) et de lancer EVAL-01 :
[ ] CRIT-01 : Découpler probe_model du modèle de production LCCA dans eval_config.toml
[ ] CRIT-02 : Spécifier JudgeLocal (Ollama) comme juge par défaut V1 ; Claude = option --judge claude
[ ] CRIT-03 : Ajouter un statut "draft" aux questions générées par bench_generator.py
[ ] MAJ-01 : Documenter le mode probe_mode = "monolithic" | "orchestrated"
[ ] MAJ-02 : Ajouter une note A/B testing FR vs EN dans le prompt probe
[ ] MAJ-03 : Ajouter max_skill_tokens et compaction dans distill_engine.py
[ ] Q-02 : Confirmer l'existence de core/skill_library.py et son interface add_skill()
[ ] Q-05 : Documenter la stratégie de collision sha256 (fallback : sha256 complet ?)
8. Verdict Global
Table
Critère	Note	Commentaire
Architecture	8/10	Bonne séparation des responsabilités, flux clair
Cohérence LCCA	5/10	Dépendance API externe et modèle probe non adapté au contexte hardware/contraint
Faisabilité V1	6/10	116 tests + 7 sprints est ambitieux pour un projet solo ; prioriser le core probe+judge+distill
Robustesse	7/10	Bons patterns (atomic write, append JSONL, mode dégradé)
Note globale	6.5/10	Bonne base, mais les 3 problèmes critiques doivent être résolus avant de coder.
Ce document est destiné à être envoyé à Claude Desktop pour révision et intégration dans les specs EVAL-00 à EVAL-07.