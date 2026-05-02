# SPEC EvalLoop — EVAL-02 : ProbeEngine + CurriculumTracker
**Version** : 1.0
**Date** : 2026-04-23
**Statut** : DRAFT
**Dépendances** : EVAL-01 (dataclasses + config)

---

## 1. Objectif du sprint

Implémenter les deux composants de la **Phase 1 — PROBE** :

1. **`curriculum_tracker.py`** — Gestion des paliers, unlock, état persisté
2. **`probe_engine.py`** — Soumission des questions à LLCA via Ollama (100% offline)

Ce sprint produit `responses.jsonl` dans le dossier de session.

---

## 2. Fichiers créés

| Fichier | Rôle |
|---|---|
| `EvalLoop/engines/curriculum_tracker.py` | Paliers + unlock + eval_state.json |
| `EvalLoop/engines/probe_engine.py` | Questions → LLCA → responses.jsonl |

---

## 3. `curriculum_tracker.py`

### Responsabilités
- Charger / sauvegarder `eval_state.json` (écriture atomique)
- Retourner le palier courant pour un domaine
- Décider si un palier peut être débloqué (score moyen ≥ seuil_unlock)
- Sélectionner les questions du palier courant depuis `benchmarks/{domain}/palier_{N}.json`

### Interface publique

```python
class CurriculumTracker:
    def __init__(self, evalloop_dir: Path, config: dict):
        ...

    def get_current_palier(self, domain: str) -> int:
        """Retourne le palier courant pour un domaine (0 si jamais testé)."""

    def get_questions_for_session(self, domain: str, count: int) -> list[BenchQuestion]:
        """Charge count questions du palier courant pour le domaine.
        Fallback palier 0 si le fichier palier N n'existe pas encore."""

    def record_palier_scores(
        self,
        domain: str,
        palier: int,
        scores: list[float],
        session_timestamp: str,
    ) -> bool:
        """Enregistre les scores d'un palier. Retourne True si le palier suivant
        est débloqué (score_moyen >= seuil_unlock)."""

    def get_state(self, domain: str) -> PalierState:
        """Retourne l'état complet d'un domaine."""

    def _load_state(self) -> dict[str, PalierState]:
        """Charge eval_state.json. Retourne {} si absent."""

    def _save_state(self) -> None:
        """Écriture atomique .tmp → Path.replace() (règle T-14)."""

    def _load_bench_file(self, domain: str, palier: int) -> list[BenchQuestion]:
        """Charge benchmarks/{domain}/palier_{N}.json.
        Retourne [] si fichier absent (log warning)."""
```

### Règles CurriculumTracker
- `eval_state.json` absent → créé avec `{}` au premier appel `_save_state`
- Palier inconnu pour un domaine → défaut 0 (jamais d'exception)
- `get_questions_for_session` : si count > questions disponibles → retourne tout ce qui existe
- Ordre questions dans `get_questions_for_session` : aléatoire (shuffle) pour éviter le biais de position
- `record_palier_scores` : score_moyen = `sum(scores) / len(scores)` si `len(scores) > 0`, sinon 0.0
- Unlock atomique : `_save_state()` appelé même si unlock = False (persistance scores)

---

## 4. `probe_engine.py`

### Responsabilités
- Recevoir une liste de `BenchQuestion`
- Soumettre chaque question à LLCA via Ollama REST API (local)
- Produire `responses.jsonl` dans le dossier session
- Mesurer `duration_ms` par question

### Interface publique

```python
class ProbeEngine:
    def __init__(self, config: dict, session_dir: Path):
        ...

    def run(self, questions: list[BenchQuestion]) -> list[ProbeResponse]:
        """Lance le probe sur toutes les questions.
        Écrit responses.jsonl au fur et à mesure (append JSONL, pas batch).
        Retourne la liste complète des ProbeResponse."""

    def _probe_one(self, question: BenchQuestion) -> ProbeResponse:
        """Soumet une seule question à Ollama. Retourne ProbeResponse."""

    def _build_prompt(self, question: BenchQuestion) -> str:
        """Construit le prompt système + user pour la question."""
```

### Format du prompt Ollama

```
SYSTEM:
Tu es LCCA, un assistant expert en développement Python.
Réponds en français. Sois précis, structuré, et cite des exemples concrets.
Domaine : {domain} | Palier : {palier}

USER:
{question.question}
```

### Écriture JSONL — append ligne par ligne

```python
# Après chaque _probe_one(), écrire immédiatement :
with open(session_dir / "responses.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps(response.to_dict(), ensure_ascii=False) + "\n")
```

Pourquoi append ligne par ligne : si Ollama plante à mi-session, les réponses déjà obtenues sont préservées.

### Appel Ollama REST

```python
import urllib.request
import json

payload = {
    "model": config["llca"]["model"],
    "prompt": prompt,
    "stream": False,
    "options": {
        "num_predict": config["llca"]["max_tokens"],
    }
}
# POST http://localhost:11434/api/generate
# timeout=None (règle LCCA : OLLAMA_TIMEOUT = None)
```

### Règles ProbeEngine
- `urllib.request` stdlib uniquement (pas de `requests`)
- `timeout=None` obligatoire sur `urllib.request.urlopen` (règle LCCA)
- Si Ollama répond avec une erreur HTTP → `ProbeResponse.response = f"[ERREUR OLLAMA: {status}]"`, `duration_ms = 0`
- Si `OSError` (Ollama éteint) → log critique + `raise` (pas de swallow silencieux)
- `responses.jsonl` ouvert en mode `"a"` (append) — jamais tronqué si relance en milieu de session
- Reprendre une session interrompue : `ProbeEngine.run()` vérifie les IDs déjà présents dans `responses.jsonl` et skip les questions déjà répondues

---

## 5. Format `responses.jsonl`

Une ligne JSON par réponse (NDJSON) :

```jsonl
{"question_id": "py-p0-001", "model": "qwen2.5-coder:3b", "response": "...", "duration_ms": 4230, "timestamp": "2026-04-23T21:05:12", "domain": "python_core", "palier": 0}
{"question_id": "py-p0-002", "model": "qwen2.5-coder:3b", "response": "...", "duration_ms": 3810, "timestamp": "2026-04-23T21:06:01", "domain": "python_core", "palier": 0}
```

---

## 6. Tests attendus — `test_eval_02_probe.py` (~18 tests)

### CurriculumTracker
- `get_current_palier` domaine inconnu → 0
- `get_current_palier` domaine existant → palier persisté
- `get_questions_for_session` fichier absent → [] + log warning
- `get_questions_for_session` count > dispo → retourne tout
- `get_questions_for_session` ordre aléatoire (shuffle)
- `record_palier_scores` score_moyen calculé correctement
- `record_palier_scores` unlock si score >= seuil → retourne True + palier incrémenté
- `record_palier_scores` no unlock si score < seuil → retourne False + palier inchangé
- `record_palier_scores` liste vide → score 0.0 + no unlock
- Écriture atomique : `eval_state.json.tmp` créé puis renommé

### ProbeEngine
- `_build_prompt` contient domain + palier + question
- `_probe_one` appel Ollama mocké → ProbeResponse correct
- `_probe_one` Ollama erreur HTTP → ProbeResponse avec `[ERREUR OLLAMA: 500]`
- `run` écrit responses.jsonl ligne par ligne
- `run` skip questions déjà présentes dans responses.jsonl (reprise session)
- `run` retourne liste ProbeResponse dans le même ordre que questions
- `run` OSError Ollama → exception propagée (pas swallowée)
