# Spec V9-04 — Pipeline d'Entraînement LCCA
<!-- AI-READY | LCCA V9 | Training Pipeline | Version 9.0.0-draft | 2026-04-20 -->

## Abstract

Construire un pipeline d'entraînement continu qui transforme les transactions réussies de LCCA
en données d'entraînement SFT (Supervised Fine-Tuning), puis utilise le score `CodeEvaluator`
comme fonction de récompense pour GRPO (Group Relative Policy Optimization).
Le résultat est un modèle Qwen2.5-coder:7b fine-tuné sur les conventions spécifiques du projet.

---

## Sprint V9-04-A — Collecteur de données SFT

### Contexte et motivations

Chaque transaction LCCA réussie produit un triplet exploitable :

```
intent (NLIntent.details)
    → spec (SpecEntry.body_md)     [si generate_spec appelé]
    → code (GenerationResult.code) [si eval >= 70]
    → receipt (ExecutionReceipt)   [HMAC signé, traçable]
```

Ces triplets sont stockés dans :
- `lcca_patches` : TX commitées (intent + fichiers modifiés)
- `lcca_solutions` : code validé (code + score)
- `lcca_specs` : specs générées (body_md + validation)
- `receipts/` : ExecutionReceipts HMAC

Le module `TrainingDataCollector` doit les assembler en paires (instruction, output)
au format SFT standard (ShareGPT / Alpaca) exportables vers Unsloth ou axolotl.

### Fichiers à créer / modifier

| Fichier | Opération |
|---------|-----------|
| `core/training_collector.py` | CREATE — TrainingDataCollector |
| `core/training_types.py` | CREATE — SFTPair, GRPOSample dataclasses |
| `config.py` | PATCH — `TRAINING_OUTPUT_DIR`, `TRAINING_MIN_SCORE`, `TRAINING_MIN_PAIRS` |
| `tests/test_training_collector.py` | CREATE — 10 tests |

### Spécification : `core/training_types.py`

```python
# -*- coding: utf-8-sig -*-
"""training_types.py — Dataclasses pour le pipeline d'entraînement LCCA V9."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class SFTPair:
    """
    Paire (instruction, output) pour le Supervised Fine-Tuning.

    Format ShareGPT :
        {"conversations": [
            {"from": "human", "value": instruction},
            {"from": "gpt",   "value": output}
        ]}

    Champs :
        instruction : prompt système + intent utilisateur
        output      : code Python généré et validé
        source      : origine (lcca_patches, lcca_solutions, manual)
        quality     : score CodeEvaluator (0-100)
        tx_id       : ID transaction LCCA source
        created_at  : timestamp ISO
    """
    instruction : str
    output      : str
    source      : str = "lcca_patches"
    quality     : int = 0
    tx_id       : str = ""
    created_at  : str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_sharegpt(self) -> dict:
        return {
            "conversations": [
                {"from": "human", "value": self.instruction},
                {"from": "gpt",   "value": self.output},
            ],
            "metadata": {
                "source":     self.source,
                "quality":    self.quality,
                "tx_id":      self.tx_id,
                "created_at": self.created_at,
            }
        }

    def to_alpaca(self) -> dict:
        return {
            "instruction": self.instruction,
            "input":       "",
            "output":      self.output,
        }

    def is_usable(self, min_quality: int = 70) -> bool:
        """True si la paire est de qualité suffisante pour l'entraînement."""
        return (
            bool(self.instruction) and bool(self.output)
            and self.quality >= min_quality
            and len(self.output) >= 20
        )


@dataclass
class GRPOSample:
    """
    Échantillon pour GRPO (Group Relative Policy Optimization).

    GRPO génère N completions pour un même prompt, les classe par récompense,
    puis optimise le modèle pour favoriser les meilleures.

    Champs :
        prompt   : prompt système + intent
        outputs  : liste des N générations
        rewards  : liste des scores correspondants (CodeEvaluator 0-100)
    """
    prompt  : str
    outputs : list[str]
    rewards : list[float]

    def __post_init__(self):
        if len(self.outputs) != len(self.rewards):
            raise ValueError("outputs et rewards doivent avoir la même longueur")

    def is_usable(self) -> bool:
        return len(self.outputs) >= 2 and max(self.rewards) > min(self.rewards)
```

### Spécification : `core/training_collector.py`

```python
# -*- coding: utf-8-sig -*-
"""
training_collector.py — Collecteur de données d'entraînement depuis les collections LCCA.

Usage ::

    collector = TrainingDataCollector()
    pairs = collector.collect(min_quality=70)
    stats = collector.export(pairs, output_dir=Path("training_data"))
    print(f"{stats['total']} paires exportées")
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from core.training_types import SFTPair

log = logging.getLogger("lcca.training_collector")


class TrainingDataCollector:
    """
    Collecte les paires SFT depuis MemoryEngine et ReceiptStore.

    Sources :
        1. lcca_solutions : code validé + score >= min_quality
        2. lcca_specs + lcca_patches : triplets (intent, spec, code)
        3. receipts/*.json : contexte supplémentaire
    """

    def __init__(
        self,
        memory_engine=None,
        receipt_store_path: Optional[Path] = None,
    ) -> None:
        if memory_engine is None:
            from core.memory_engine import MemoryEngine
            self._memory = MemoryEngine()
        else:
            self._memory = memory_engine

        try:
            import config
            self._receipts_dir = receipt_store_path or Path(config.A2A_RECEIPTS_DIR)
        except (ImportError, AttributeError):
            self._receipts_dir = Path("memory/receipts")

    def collect(self, min_quality: int = 70) -> list[SFTPair]:
        """
        Collecte toutes les paires SFT disponibles.

        Args:
            min_quality : seuil minimum de qualité CodeEvaluator (0-100)

        Returns:
            Liste de SFTPair filtrés et dédupliqués.
        """
        pairs: list[SFTPair] = []
        pairs.extend(self._collect_from_solutions(min_quality))
        pairs.extend(self._collect_from_receipts(min_quality))

        # Déduplication par (instruction[:100], output[:100])
        seen: set = set()
        deduped: list[SFTPair] = []
        for p in pairs:
            key = (p.instruction[:100], p.output[:100])
            if key not in seen:
                seen.add(key)
                deduped.append(p)

        log.info("collect: %d paires brutes → %d après déduplication", len(pairs), len(deduped))
        return deduped

    def export(
        self,
        pairs: list[SFTPair],
        output_dir: Path,
        format: str = "sharegpt",    # "sharegpt" | "alpaca"
    ) -> dict:
        """
        Exporte les paires en fichiers JSON/JSONL exploitables par Unsloth/axolotl.

        Structure exportée :
            output_dir/
                train.jsonl     (80% des paires)
                eval.jsonl      (20% des paires)
                stats.json      (métriques)

        Returns:
            dict avec clés : total, train, eval, skipped, avg_quality
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        usable = [p for p in pairs if p.is_usable(min_quality=0)]
        if not usable:
            log.warning("export: aucune paire utilisable")
            return {"total": 0, "train": 0, "eval": 0, "skipped": len(pairs), "avg_quality": 0}

        # Split 80/20
        split_idx = max(1, int(len(usable) * 0.8))
        train_pairs = usable[:split_idx]
        eval_pairs  = usable[split_idx:]

        def _write_jsonl(path: Path, plist: list[SFTPair]) -> None:
            with path.open("w", encoding="utf-8") as f:
                for p in plist:
                    record = p.to_sharegpt() if format == "sharegpt" else p.to_alpaca()
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

        _write_jsonl(output_dir / "train.jsonl", train_pairs)
        _write_jsonl(output_dir / "eval.jsonl",  eval_pairs)

        avg_q = sum(p.quality for p in usable) / len(usable) if usable else 0
        stats = {
            "total":       len(usable),
            "train":       len(train_pairs),
            "eval":        len(eval_pairs),
            "skipped":     len(pairs) - len(usable),
            "avg_quality": round(avg_q, 1),
            "format":      format,
        }
        (output_dir / "stats.json").write_text(
            json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        log.info("export: %d train + %d eval → %s", len(train_pairs), len(eval_pairs), output_dir)
        return stats

    # ── Méthodes privées ──────────────────────────────────────────────────────

    def _collect_from_solutions(self, min_quality: int) -> list[SFTPair]:
        """Collecte depuis lcca_solutions (code validé)."""
        if not self._memory.is_available:
            return []
        try:
            results = self._memory.search("python function implementation", n=200)
            pairs: list[SFTPair] = []
            for entry in results.get("solutions", []):
                code    = entry.metadata.get("code", "") or entry.content
                score   = int(float(entry.metadata.get("score", 0)) * 100)
                intent  = entry.metadata.get("intent", "Implémente la fonction suivante")
                tx_id   = entry.metadata.get("tx_id", "")
                if score < min_quality or not code.strip():
                    continue
                instruction = self._build_instruction(intent)
                pairs.append(SFTPair(
                    instruction = instruction,
                    output      = code,
                    source      = "lcca_solutions",
                    quality     = score,
                    tx_id       = tx_id,
                ))
            log.debug("_collect_from_solutions: %d paires", len(pairs))
            return pairs
        except Exception as exc:
            log.debug("_collect_from_solutions error: %s", exc)
            return []

    def _collect_from_receipts(self, min_quality: int) -> list[SFTPair]:
        """Collecte depuis les ExecutionReceipts (fichiers JSON dans receipts/)."""
        pairs: list[SFTPair] = []
        if not self._receipts_dir.exists():
            return pairs
        for receipt_file in self._receipts_dir.glob("*.json"):
            try:
                data = json.loads(receipt_file.read_text(encoding="utf-8"))
                code    = data.get("code_snapshot", "")
                score   = data.get("quality_score", 0)
                intent  = data.get("intent", "")
                tx_id   = data.get("task_id", "")
                if score < min_quality or not code.strip() or not intent.strip():
                    continue
                pairs.append(SFTPair(
                    instruction = self._build_instruction(intent),
                    output      = code,
                    source      = "receipts",
                    quality     = score,
                    tx_id       = tx_id,
                ))
            except Exception:
                continue
        log.debug("_collect_from_receipts: %d paires", len(pairs))
        return pairs

    @staticmethod
    def _build_instruction(intent: str) -> str:
        """Construit le prompt instruction au format LCCA."""
        return (
            "Tu es LCCA, un agent de codage Python transactionnel.\n"
            "Génère UNIQUEMENT du code Python valide, conforme aux conventions LCCA V7.2 :\n"
            "- type hints obligatoires\n"
            "- docstring en français technique\n"
            "- from __future__ import annotations\n"
            "- sys.executable (jamais 'python' hardcodé)\n"
            "- safe_path() avant toute opération disque\n\n"
            f"Tâche : {intent}"
        )
```

---

## Sprint V9-04-B — Intégration GRPO (récompense CodeEvaluator)

### Contexte et motivations

GRPO (Group Relative Policy Optimization) est la technique de RL utilisée par Qwen2.5
lui-même pour son post-training. Elle ne nécessite pas un modèle reward séparé —
on définit une **fonction de récompense programmable** qui retourne un score numérique.

`CodeEvaluator` (5 critères, score 0-100) est exactement cette fonction de récompense.

### Architecture GRPO pour LCCA

```
Pour chaque SFTPair.instruction :
    1. Générer N=4 completions via le modèle de base (Qwen2.5-coder:7b)
    2. Pour chaque completion :
       - Compiler (compile() Python) → -50 si SyntaxError
       - CodeEvaluator.evaluate() → score 0-100
       - Vérifier les règles LCCA (sys.executable, safe_path) → -20 par violation
    3. GRPO calcule l'avantage relatif (meilleure - moyenne)
    4. Gradient update pour favoriser les meilleures completions
```

### Spécification : fonction de récompense

```python
# core/training_reward.py
"""
training_reward.py — Fonctions de récompense pour GRPO.
Compatible avec Unsloth GRPO notebooks (reward_funcs parameter).
"""
from __future__ import annotations
import re
from typing import Any

from core.code_evaluator import CodeEvaluator

_evaluator = CodeEvaluator()

_LCCA_RULES = [
    (r'\bpython\b(?!.*sys\.executable)', -20, "hardcoded 'python' instead of sys.executable"),
    (r'file\.write\(', -15, "direct file.write() without snapshot"),
    (r'import\s+subprocess.*shell\s*=\s*True', -25, "shell=True subprocess injection risk"),
]


def lcca_code_reward(prompts: list[str], completions: list[str], **kwargs) -> list[float]:
    """
    Fonction de récompense GRPO pour Unsloth.

    Signature conforme à Unsloth reward_funcs :
        reward_funcs=[lcca_code_reward]

    Args:
        prompts     : liste des prompts (1 par group)
        completions : liste des completions générées

    Returns:
        Liste de scores float (0.0 à 1.0) normalisés depuis CodeEvaluator.
    """
    rewards: list[float] = []
    for code in completions:
        score = _compute_reward(code)
        rewards.append(score / 100.0)  # normaliser 0-1 pour GRPO
    return rewards


def _compute_reward(code: str) -> float:
    """Calcule le score de récompense pour un snippet de code."""
    # Penalité syntax
    try:
        compile(code, "<grpo>", "exec")
    except SyntaxError:
        return -50.0

    # Score CodeEvaluator (0-100)
    try:
        eval_result = _evaluator.evaluate(code)
        score = float(eval_result.score)
    except Exception:
        score = 30.0  # score minimal si evaluateur échoue

    # Penalités règles LCCA
    for pattern, penalty, _ in _LCCA_RULES:
        if re.search(pattern, code):
            score += penalty

    return max(-50.0, min(100.0, score))
```

### Procédure d'entraînement (Unsloth)

```bash
# 1. Installer Unsloth (WSL2 recommandé sur Windows)
pip install unsloth

# 2. Exporter les données SFT
python -c "
from core.training_collector import TrainingDataCollector
from pathlib import Path
c = TrainingDataCollector()
pairs = c.collect(min_quality=70)
stats = c.export(pairs, Path('training_data/v9'))
print(stats)
"

# 3. Lancer l'entraînement SFT (notebook Unsloth ou script)
# Paramètres recommandés pour P50 (16GB RAM, pas de GPU dédié) :
#   model       = "qwen2.5-coder:7b-instruct"
#   load_in_4bit = True
#   r = 16  (rank LoRA)
#   lora_alpha = 16
#   max_seq_length = 2048
#   per_device_train_batch_size = 1
#   gradient_accumulation_steps = 4
#   num_train_epochs = 3

# 4. Sauvegarder le modèle fine-tuné au format GGUF
# 5. Enregistrer dans Ollama : ollama create lcca-qwen7b -f Modelfile
```

### Modelfile Ollama pour le modèle fine-tuné

```
# D:\LLMCodeAgent\Modelfile.lcca-v9
FROM ./lcca-qwen7b-sft.gguf

PARAMETER temperature 0.2
PARAMETER top_p 0.9
PARAMETER num_predict 1024

SYSTEM """
Tu es LCCA V9, un agent de codage Python transactionnel spécialisé dans
le projet LLMCodeAgent. Tu génères du code conforme aux conventions LCCA V7.2.
Tu ne génères JAMAIS de code sans type hints, docstring, et from __future__ import annotations.
Tu utilises TOUJOURS sys.executable (jamais 'python' hardcodé).
Tu appelles TOUJOURS safe_path() avant toute opération disque.
"""
```

---

## Sprint V9-04-C — Pipeline d'entraînement continu

### Contexte et motivations

L'entraînement manuel est une friction. Le pipeline continu doit :
1. Surveiller les nouvelles TX (delta depuis le dernier entraînement)
2. Si delta >= `TRAINING_MIN_PAIRS` (50), déclencher un micro-fine-tune LoRA
3. Hot-swap le modèle dans Ollama après entraînement

### Fichiers à créer

| Fichier | Opération |
|---------|-----------|
| `core/training_pipeline.py` | CREATE — TrainingPipeline (scheduler + trigger) |
| `config.py` | PATCH — `TRAINING_MIN_PAIRS = 50`, `TRAINING_SCHEDULE_HOURS = 168` (1 semaine) |

### Spécification : `TrainingPipeline`

```python
class TrainingPipeline:
    """
    Pipeline d'entraînement continu LCCA.

    Cycle :
        1. check_trigger() — nouvelles TX depuis last_trained ?
        2. collect()       — assembler les paires SFT
        3. train()         — lancer Unsloth (subprocess)
        4. register()      — ollama create lcca-v9-{date}
        5. update_config() — OLLAMA_MODEL = nouveau modèle

    Déclenchement :
        - Manuel : TrainingPipeline().run()
        - Automatique : planifié toutes les TRAINING_SCHEDULE_HOURS heures
          via un thread daemon (optionnel, activé par TRAINING_AUTO_ENABLED)
    """

    def check_trigger(self) -> tuple[bool, int]:
        """
        Vérifie si l'entraînement doit être déclenché.

        Returns:
            (should_train: bool, new_pairs_count: int)
        """
        ...

    def run(self, force: bool = False) -> dict:
        """
        Exécute le pipeline complet.

        Args:
            force : ignorer le seuil TRAINING_MIN_PAIRS

        Returns:
            dict {triggered, pairs_collected, export_stats, model_name}
        """
        ...
```

### Critères d'acceptation

- [ ] `TrainingDataCollector().collect(min_quality=70)` retourne >= 1 paire sur un workspace avec TX
- [ ] `SFTPair.to_sharegpt()` produit un dict avec `conversations[0].from == "human"`
- [ ] `SFTPair.to_alpaca()` produit un dict avec `instruction`, `input`, `output`
- [ ] `TrainingDataCollector().export(pairs, dir, "sharegpt")` crée `train.jsonl` + `eval.jsonl` + `stats.json`
- [ ] `lcca_code_reward(["prompt"], ["def f(): pass"])` retourne une liste de 1 float dans [-0.5, 1.0]
- [ ] `_compute_reward("def f(: INVALID")` retourne -50.0 (SyntaxError)
- [ ] `_compute_reward("import subprocess; subprocess.run(['cmd'], shell=True)")` retourne score <= 50
- [ ] `TrainingDataCollector` silencieux si MemoryEngine non disponible (is_available = False)
- [ ] `export([], dir)` retourne `{"total": 0, "skipped": 0, ...}` sans crash
- [ ] `SFTPair.is_usable(min_quality=70)` retourne False si quality=69
