# Sprint SI-03 — Orchestrator Light
<!-- AI-READY | LCCA V10.5 | Sprint SI-03 | Priorité P0 | Effort 1.5j | Statut : 🔲 À FAIRE -->

## Objectif

Implémenter `OrchestratorLight` : lecture des observations récentes, évaluation des règles
JSON (grammaire unifiée), exécution des actions avec write-ahead, dry-run et garde-fous.

## Contexte

- Dépendance : SI-01 ✅, SI-02 🔲
- `orchestrator_rules.json` déjà créé (SI-01) avec 6 règles initiales
- `si_utils.py` fournit `log_action`, `check_and_update_cooldown`, `force_cooldown`
- Mode 3 : `A2ALocalBus` — import lazy, check `callable(getattr(...))`

## Fichiers cibles

| # | Fichier | Opération | Lignes estimées |
|---|---------|-----------|-----------------|
| 1 | `SelfImprove/engines/orchestrator.py` | CREATE | ~250 lignes |
| 2 | `tests/test_si_03_orchestrator.py` | CREATE | ~100 lignes |

## Spécification détaillée

### Classe `OrchestratorLight`

```python
# -*- coding: utf-8 -*-
"""
SelfImprove — Orchestrator Light V10.5
Règles déterministes JSON. Zéro LLM. Zéro apprentissage.
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from SelfImprove.si_config import load_config, get_coupling_mode
from SelfImprove.si_utils import (
    log_action, add_pending_action, approve_pending_action,
    check_and_update_cooldown, force_cooldown,
)

log = logging.getLogger(__name__)

_OPS = {"==", ">=", "<=", ">", "<", "!="}

def _compare(actual: Any, operator: str, expected: Any) -> bool:
    try:
        if operator == "==": return actual == expected
        if operator == ">=": return actual >= expected
        if operator == "<=": return actual <= expected
        if operator == ">":  return actual >  expected
        if operator == "<":  return actual <  expected
        if operator == "!=": return actual != expected
    except TypeError:
        return False
    return False


class OrchestratorLight:
    def __init__(self, dry_run: bool = False, cfg: dict | None = None) -> None:
        self._dry_run = dry_run
        self._cfg = cfg or load_config()

    def run(self) -> dict:
        signals = self._load_signals()
        rules = self._load_rules()
        mode = get_coupling_mode()

        triggered = 0
        skipped = 0
        matched_rules: list[dict] = []

        for rule in rules:
            # Guard — min_coupling_mode
            if mode < rule.get("min_coupling_mode", 1):
                log.info("Règle %s ignorée : mode %s < min %s",
                         rule["id"], mode, rule["min_coupling_mode"])
                skipped += 1
                continue

            # Évaluation condition
            matched, matching_signals = self._eval_condition(rule["condition"], signals)
            if not matched:
                skipped += 1
                continue

            # Guard — cooldown + max_trigger
            if not check_and_update_cooldown(
                rule["id"],
                rule.get("cooldown_sec", 300),
                rule.get("max_trigger_per_day", 10),
            ):
                skipped += 1
                continue

            # Dry-run — collecte sans exécution
            if self._dry_run:
                matched_rules.append({
                    "rule_id": rule["id"],
                    "action": rule["action"],
                    "reason": "%d signal(s) matchés" % len(matching_signals),
                })
                continue

            # Write-ahead AVANT exécution
            target = matching_signals[0].get("file", "system") if matching_signals else "system"
            log_action(rule["id"], rule["action"], target, "started",
                       "pre-execution write-ahead", self._cfg)

            status = self.execute_action(
                rule_id=rule["id"],
                action=rule["action"],
                target=target,
                params=rule.get("params", {}),
                require_ack=rule.get("require_human_ack", False),
                matching_signals=matching_signals,
            )

            log_action(rule["id"], rule["action"], target, status, "", self._cfg)

            if status in ("success", "pending_ack"):
                triggered += 1
            else:
                skipped += 1
                if status == "failed":
                    force_cooldown(rule["id"], rule.get("cooldown_sec", 300))

        return {"triggered": triggered, "skipped": skipped, "matched_rules": matched_rules}
```

### Méthode `_load_signals()`

```python
def _load_signals(self) -> list[dict]:
    obs_dir = Path(self._cfg["paths"]["observations_dir"])
    window = self._cfg["orchestrator"]["observation_window"]
    max_age = self._cfg["orchestrator"]["observation_max_age_sec"]
    now = datetime.now(timezone.utc).timestamp()

    files = sorted(obs_dir.glob("*.json"), reverse=True)[:window]
    raw_signals: list[dict] = []

    for f in files:
        try:
            data = json.loads(f.read_text("utf-8"))
            obs_ts = datetime.fromisoformat(
                data["timestamp"].replace("Z", "+00:00")
            ).timestamp()
            if now - obs_ts > max_age:
                log.debug("Observation %s trop ancienne, ignorée", f.name)
                continue
            raw_signals.extend(data.get("signals", []))
        except Exception as exc:  # noqa: BLE001
            log.debug("Lecture observation %s : %s", f.name, exc)

    # Fusion par pattern (count additionné)
    merged: dict[str, dict] = {}
    for s in raw_signals:
        key = s["pattern"]
        if key not in merged:
            merged[key] = dict(s)
        else:
            merged[key]["count"] = merged[key].get("count", 1) + s.get("count", 1)
            # Conserver la sévérité la plus haute
            if s.get("severity") == "high":
                merged[key]["severity"] = "high"

    return list(merged.values())
```

### Méthode `_eval_condition()`

```python
def _eval_condition(self, condition: dict,
                    signals: list[dict]) -> tuple[bool, list[dict]]:
    field = condition["field"]          # "signal.count" | "signal.severity"
    operator = condition["operator"]
    value = condition["value"]
    filters = condition.get("filters", {})

    if operator not in _OPS:
        log.warning("Opérateur inconnu : %s", operator)
        return False, []

    # Filtrage par filters (hors "scope" — non implémenté en V10.5)
    candidates = [
        s for s in signals
        if all(s.get(k) == v for k, v in filters.items() if k != "scope")
    ]
    if not candidates:
        return False, []

    # Extraction du champ (dernier segment après ".")
    field_key = field.split(".")[-1]
    matches = [s for s in candidates
               if s.get(field_key) is not None
               and _compare(s[field_key], operator, value)]

    return bool(matches), matches
```

### Méthode `execute_action()`

```python
def execute_action(self, rule_id: str, action: str, target: str,
                   params: dict, require_ack: bool = False,
                   matching_signals: list | None = None) -> str:
    matching_signals = matching_signals or []
    try:
        if action == "log_only":
            log.info("Règle %s — log_only sur %s", rule_id, target)
            return "success"

        if action == "notify_human":
            return self._action_notify_human(
                rule_id, action, target, params, require_ack, matching_signals)

        if action == "retry_coder_once":
            return self._action_retry_coder_once(target, params)

        if action == "trigger_auto_fix":
            return self._action_trigger_auto_fix(params)

        log.warning("Action inconnue : %s", action)
        return "skipped"

    except Exception as exc:  # noqa: BLE001
        log.error("execute_action %s échouée : %s", action, exc)
        return "failed"
```

### Actions

```python
def _action_notify_human(self, rule_id, action, target, params,
                         require_ack, matching_signals) -> str:
    sig = matching_signals[0] if matching_signals else {}
    msg = params.get("message_template", "Événement SelfImprove : {pattern}").format(
        pattern=sig.get("pattern", "?"),
        file=sig.get("file", "?"),
        count=sig.get("count", 0),
    )
    print("\n[LCCA SelfImprove] %s" % msg)

    if require_ack:
        action_id = add_pending_action(rule_id, action, target, params, self._cfg)
        print("  → Approbation requise : python lcca_si.py approve %s" % action_id)
        return "pending_ack"
    return "success"

def _action_retry_coder_once(self, target: str, params: dict) -> str:
    import subprocess, sys
    mode = get_coupling_mode()
    if mode == 3:
        # Import lazy + guard callable
        try:
            from core.agents.a2a_bus import A2ALocalBus, TaskContract
        except ImportError:
            log.error("A2ALocalBus non disponible (Mode 3 requis)")
            return "failed"
        bus = A2ALocalBus()
        if not callable(getattr(bus, "publish", None)):
            log.error("A2ALocalBus.publish non callable")
            return "failed"
        contract = TaskContract(
            intent="retry failed tests on %s" % target,
            context={"test_filter": params.get("test_filter", "only_failed"),
                     "file": target},
            agent_target="coder",
        )
        bus.publish(contract)
        return "success"
    else:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", target,
             "--json-report",
             "--report-file=%s" % str(
                 Path(self._cfg["paths"]["observations_dir"]) / "retry_results.json"),
             "-x", "--quiet"],
            capture_output=True, timeout=300,
        )
        return "success" if result.returncode == 0 else "failed"

def _action_trigger_auto_fix(self, params: dict) -> str:
    flag = Path(self._cfg["paths"]["self_improve_dir"]) / ".auto_fix_enabled"
    if not flag.exists():
        log.info("Auto-Fix désactivé (flag absent) — trigger ignoré")
        return "skipped"
    from SelfImprove.engines.auto_fix import AutoFixEngine
    engine = AutoFixEngine(self._cfg)
    return engine.run(params.get("pattern_id", ""))

def _load_rules(self) -> list[dict]:
    rules_file = Path(self._cfg["orchestrator"]["rules_file"])
    if not rules_file.exists():
        log.warning("orchestrator_rules.json absent")
        return []
    try:
        return json.loads(rules_file.read_text("utf-8")).get("rules", [])
    except Exception as exc:  # noqa: BLE001
        log.error("Lecture rules JSON : %s", exc)
        return []
```

## Critères d'acceptation

- [ ] `python lcca_si.py decide --dry-run` affiche les règles matchées sans exécuter
- [ ] `python lcca_si.py decide` exécute les règles et écrit `actions.log`
- [ ] Write-ahead vérifié : chaque action dans `actions.log` avant exécution
- [ ] Cooldown : règle non redéclenchée avant `cooldown_sec`
- [ ] `max_trigger_per_day` : règle bloquée après N déclenchements
- [ ] `min_coupling_mode` : règle ignorée si mode insuffisant
- [ ] Mode 3 : A2ALocalBus absent → statut "failed" (pas de crash)
- [ ] Gestion erreur action → statut "failed", cooldown forcé

## Tests (`tests/test_si_03_orchestrator.py`)

```python
class TestOrchestratorLight:
    def test_dry_run_no_side_effects(self, tmp_path): ...
    def test_eval_condition_count_gte(self): ...
    def test_eval_condition_severity_eq(self): ...
    def test_eval_condition_no_match(self): ...
    def test_cooldown_blocks_retrigger(self): ...
    def test_max_trigger_per_day(self): ...
    def test_min_coupling_mode_skips(self): ...
    def test_write_ahead_before_execute(self, tmp_path): ...
    def test_action_log_only(self): ...
    def test_action_notify_no_ack(self, capsys): ...
    def test_action_notify_require_ack(self, tmp_path): ...
    def test_action_trigger_autofix_flag_absent(self, tmp_path): ...
    def test_failed_action_forces_cooldown(self): ...
    def test_observation_window(self, tmp_path): ...
    def test_observation_max_age(self, tmp_path): ...
```

## Protocole d'exécution

```
1. filesystem:read_text_file SelfImprove/si_utils.py       → vérifier log_action
2. filesystem:read_text_file SelfImprove/orchestrator_rules.json
3. filesystem:write_file SelfImprove/engines/orchestrator.py
4. filesystem:write_file tests/test_si_03_orchestrator.py
5. [relire les deux fichiers]
6. pytest tests/test_si_03_orchestrator.py -v
7. pytest tests/ -x -q  (régression globale)
```

## Mise à jour skills (fin de sprint)

- **001** : règle "OrchestratorLight — import A2ALocalBus lazy + callable(getattr(...)) guard"
- **002** : `SelfImprove/engines/orchestrator.py` ajouté à l'arborescence
- **003** : anti-pattern "évaluer condition avec deux formats JSON différents → parsing incohérent"
