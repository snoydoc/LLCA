# LCCA V10 — L'Hypothèse du Miroir Brisé
> **Version** : V10.0 — Architecture de rupture totale  
> **Date** : 2026-04-23  
> **Statut** : PROPOSITION — validation humaine requise avant tout code  
> **Contraintes machine** : 16 GB RAM · 4 GB VRAM Quadro M2000M · 100% offline

---

## Le vrai problème que personne ne pose

La V10 originale demande : *"Comment LCCA peut-il s'améliorer ?"*

Ce n'est pas la bonne question.

La bonne question : **LCCA sait-il ce qu'il ne sait pas ?**

LCCA a un KarpathyLoop (Architect→Coder→Reviewer→Tester), un MemPalace avec 410 skills, un SpecLayer V7.2, un TransactionManager ACID. C'est un organisme sophistiqué. Mais il a un angle mort fondamental : **il ne peut observer que ce qu'il génère**. Il voit ses outputs, jamais ses patterns d'échec cachés.

Un humain qui travaille 6 mois développe des *angles morts cognitifs* — des façons de penser qui deviennent invisibles précisément parce qu'elles sont devenues automatiques. LCCA a le même problème, mais à l'échelle du code.

V10 ne propose pas de scanner les TODO. V10 propose de **rendre visible l'invisible**.

---

## Trois idées que ni toi ni moi n'avons probablement explorées

---

### Idée 1 — L'Archéologie des Rollbacks

**Principe** : Les erreurs que LCCA corrige *sans laisser de trace* sont la mine d'or.

Quand LCCA fait un rollback, la transaction échoue, le code revient à l'état précédent — et personne n'enregistre *pourquoi*. Ces rollbacks sont des fossiles d'échec. Ils contiennent la signature des limites cognitives du système.

**Ce qu'on ferait :**

```
D:\LLMCodeAgent\transactions\   ← déjà existant (WAL files)
         │
         ▼
  RollbackArcheologist
         │
         ├── Lit tous les WAL des 30 derniers jours
         ├── Extrait : (intent_original, fichiers_touchés, raison_echec)
         ├── Vectorise chaque échec avec ChromaDB (déjà présent)
         └── Cherche des CLUSTERS d'échec similaires
```

**Question qu'on n'a jamais posée** : Est-ce que LCCA échoue *toujours* sur le même type de pattern ? Est-ce qu'il y a une classe d'intent (ex: "modifie une fonction avec des closures imbriquées") qui déclenche systématiquement un rollback ?

Si oui, cette classe d'intent est un **borgne cognitif** — et la spec qui en sort n'est pas "améliore le code", c'est "apprends à voir ce que tu ne vois pas".

```python
# Sketch — RollbackArcheologist
@dataclass
class RollbackFossil:
    tx_id: str
    date: datetime
    intent: str           # ce que LCCA voulait faire
    files_touched: list   # où il a échoué
    error_type: str       # SyntaxError / ValidationError / PatchFailed
    error_msg: str        # message brut
    vector: list[float]   # embedding ChromaDB

class RollbackArcheologist:
    def excavate(self) -> list[FailureCluster]:
        fossils = self._read_all_wal_files()
        clusters = self._cluster_by_embedding(fossils)
        # Un cluster = une limite cognitive récurrente
        return [FailureCluster(fossils=c, pattern=self._name_pattern(c))
                for c in clusters if len(c) >= 3]
```

**Ce qui est nouveau ici** : On ne cherche pas à corriger les erreurs passées. On cherche à *nommer les patterns d'échec* pour en faire des specs d'amélioration ciblées. C'est de l'archéologie cognitive, pas du debugging.

---

### Idée 2 — Le Témoin Silencieux

**Principe** : Introduire un agent qui ne fait rien d'autre qu'*observer LCCA pendant qu'il travaille*, sans intervenir.

LCCA a déjà un ObserverAgent — mais il observe les *outputs* (qualité des skills ingérés, doublons). Ce qu'on veut est différent : un agent qui observe le **processus de génération lui-même**.

**L'insight** : Quand un humain expert travaille, ses hésitations sont aussi informatives que ses décisions. Un pianiste qui *ralentit* sur un passage dit quelque chose sur ce passage. LCCA "ralentit" aussi — via les tokens/seconde, les retries, les timeouts.

```
                    ┌─────────────────────┐
                    │   KarpathyLoop      │
                    │  (Arch→Code→Rev→Test│
                    └────────┬────────────┘
                             │ événements temps réel
                             ▼
                    ┌─────────────────────┐
                    │  SilentWitness      │
                    │                     │
                    │  Enregistre :       │
                    │  - tok/s par phase  │
                    │  - nb_retries LLM   │
                    │  - longueur context │
                    │  - type d'intent    │
                    │  - résultat final   │
                    └────────┬────────────┘
                             │
                    ┌────────▼────────────┐
                    │  WitnessReport      │
                    │                     │
                    │  "Tu génères 3×     │
                    │  plus lentement     │
                    │  sur les intents    │
                    │  avec 'async'"      │
                    └─────────────────────┘
```

**Le SilentWitness ne génère pas de code. Il génère des observations.**

Et une observation du type "les intents contenant le mot *async* prennent 4× plus longtemps et échouent 60% du temps" est une spec d'amélioration bien plus précise qu'un scan de TODO.

**Ce qui est nouveau ici** : On instrumente non pas le résultat mais le *comportement temporel* du système. C'est ce que font les profilers — mais appliqué à la cognition LLM, pas à la performance CPU. La telemetry `tok/s` existe déjà dans LCCA (TelemetryPanel V9-09). On a déjà les capteurs. Il manque juste le corrélateur.

---

### Idée 3 — La Bifurcation Fantôme

**Principe** : À chaque génération de code, créer une *branche parallèle invisible* avec un prompt légèrement différent, comparer les deux résultats, et apprendre de la divergence.

**L'idée est contre-intuitive** : on veut délibérément générer *deux versions* du même code, pas pour choisir la meilleure, mais pour voir *comment elles diffèrent*.

```
Intent : "Ajoute une validation email dans auth.py"

Branche A (normale)     │     Branche B (fantôme)
─────────────────────   │   ─────────────────────
Prompt standard         │   Prompt + "Tu es le
                        │   reviewer de la version A.
                        │   Génère une version
                        │   alternative que A aurait
                        │   ratée."
        │               │         │
        ▼               │         ▼
   Code_A.py            │    Code_B.py
        │               │         │
        └───────────────┤─────────┘
                        │
                   DivergenceAnalyzer
                        │
              "A utilise regex,
               B utilise email-validator.
               Divergence sur : gestion
               des edge cases internationaux"
                        │
                   → Spec : "LCCA ne connaît
                     pas les edge cases
                     d'emails internationaux"
```

La branche B n'est jamais commitée. Elle coûte 1 appel LLM supplémentaire (~120s). Mais elle révèle ce que le prompt standard *laisse dans l'ombre*.

**Ce qui est nouveau ici** : On utilise le LLM comme son propre adversaire — pas pour valider (c'est le rôle du Reviewer), mais pour *révéler les angles morts du prompt lui-même*. C'est une forme d'introspection par contradiction.

---

## Comment les trois idées se connectent

```
┌──────────────────────────────────────────────────────────────────┐
│                     LCCA en train de travailler                   │
└──────┬─────────────────────┬──────────────────────────┬──────────┘
       │                     │                          │
       ▼                     ▼                          ▼
  Rollback WAL         tok/s + retries           Bifurcation
  (passé)              (présent)                 fantôme
       │                     │                          │
       ▼                     ▼                          ▼
  Fossiles            Comportement              Divergences
  d'échec             temporel                  cachées
       │                     │                          │
       └─────────────────────┴──────────────────────────┘
                             │
                    MemPalace (déjà là)
                    ChromaDB (déjà là)
                             │
                    Clusters sémantiques
                             │
                    ┌────────▼─────────┐
                    │  BORGNES MAP     │
                    │                  │
                    │  "Ce que LCCA    │
                    │  ne voit pas     │
                    │  qu'il ne voit   │
                    │  pas"            │
                    └────────┬─────────┘
                             │
                    Specs d'amélioration
                    ciblées (SelfImprove/)
```

La **Borgnes Map** est l'output final de V10. Pas une liste de bugs. Pas une liste de TODO. Une cartographie des zones cognitives aveugles du système — organisée par fréquence et impact.

---

## Ce que ça donne concrètement

### Structure SelfImprove/ V10

```
D:\LLMCodeAgent\SelfImprove\
├── LLCACSelfImprove.md              ← ce fichier
├── borgnes_map.json                 ← la carte des angles morts (generée)
├── .index.json                      ← index specs
│
├── engines\
│   ├── rollback_archeologist.py     ← Idée 1
│   ├── silent_witness.py            ← Idée 2
│   └── phantom_bifurcation.py       ← Idée 3
│
├── self_enhance.py                  ← orchestrateur (appelle les 3 engines)
│
└── 2026-04-23\
    ├── 2026-04-23-001-borgne-async-patterns-draft.md
    ├── 2026-04-23-002-borgne-email-edge-cases-draft.md
    └── 2026-04-23-003-borgne-closure-rollbacks-draft.md
```

### Nomenclature V10 (légèrement différente de V10 originale)

```
{YYYY-MM-DD}-{SEQ:03d}-borgne-{SLUG}-{STATUS}.md

borgne : remplace "feature|refactor|fix" — toutes les specs V10
         sont des specs de zones aveugles, pas des tâches techniques
SLUG   : description du borgne (kebab-case)
STATUS : draft | reviewed | approved | rejected | implemented
```

---

## Ce qu'on NE fait PAS (et pourquoi)

| Ce que la V10 originale fait | Pourquoi V10 LCCA l'abandonne |
|---|---|
| Scan TODO/FIXME | Détecte seulement ce qui est *explicitement marqué* — pas les borgnes |
| Calcul complexité cyclomatique | Métrique statique qui ne prédit pas l'échec réel |
| API cloud pour cross-review | Dépendance réseau, coût, confidentialité — et le vrai adversaire est déjà dans le modèle local |
| Renommage manuel de fichiers pour changer le status | Friction inutile — `.index.json` fait foi |

---

## Les dépendances — zéro nouveau package

| Composant | Ce qu'on utilise | Déjà présent ? |
|---|---|---|
| Archéologie WAL | `pathlib` + `json` + transaction WAL existant | ✅ oui |
| Vectorisation | ChromaDB + collections Palace existantes | ✅ oui |
| SilentWitness | TelemetryStore V9-09 (tok/s déjà capturé) | ✅ oui |
| Bifurcation fantôme | `generate_text()` (CognitivePattern déjà là) | ✅ oui |
| Clustering | ChromaDB `.query()` + k-means stdlib | ✅ oui |

**Zéro nouveau package.** Tout s'appuie sur ce qui existe déjà dans LCCA.

---

## Roadmap d'implémentation — une idée à la fois

### V10.0 — Archéologie des Rollbacks (commencer ici)
Raison : les WAL files existent déjà, le risque est nul, et c'est la source de vérité la plus riche.

- [ ] `RollbackArcheologist.excavate()` — lit les WAL, extrait les fossiles
- [ ] Vectorisation des fossiles dans une nouvelle collection ChromaDB `failure_fossils`
- [ ] `FailureCluster.name_pattern()` — appel LLM 3b pour nommer le cluster en 5 mots
- [ ] Génération de specs dans `SelfImprove/YYYY-MM-DD/`
- [ ] Commandes Claude Desktop : "borgnes du jour", "détail borgne 001"

### V10.1 — Le Témoin Silencieux
Raison : la telemetry tok/s existe (TelemetryStore), on ajoute juste le corrélateur intent→perf.

- [ ] `SilentWitness` s'abonne aux événements KarpathyLoop (hook post-run existant)
- [ ] Corrélation intent_type × tok/s × success_rate
- [ ] Alerte si un intent_type a success_rate < 50% sur les 10 derniers runs

### V10.2 — La Bifurcation Fantôme
Raison : le plus risqué (double le coût LLM), à faire en dernier une fois V10.0/V10.1 validés.

- [ ] Mode `--phantom` sur le KarpathyLoop (opt-in, pas activé par défaut)
- [ ] `DivergenceAnalyzer` — compare Code_A vs Code_B, extrait les zones de divergence
- [ ] Les divergences alimentent la Borgnes Map (même pipeline que V10.0)

---

## La question à se poser avant de coder

**Une seule** : est-ce que les WAL files de `D:\LLMCodeAgent\transactions\` contiennent assez d'historique pour que l'archéologie soit intéressante ?

Si oui → on commence demain.  
Si non (peu de rollbacks) → on commence par V10.1 (SilentWitness, instrumenté sur les prochains runs).

---

*Ce document est une proposition de direction, pas un plan d'implémentation. Les trois idées sont nouvelles — aucune d'elle n'a été testée sur LCCA. C'est exactement pour ça qu'elles sont intéressantes.*
