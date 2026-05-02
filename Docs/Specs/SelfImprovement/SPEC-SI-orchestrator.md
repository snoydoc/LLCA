# LCCA SelfImprove V10.5 — Spécification Technique : Orchestrator Light
<!-- AI-READY | LCCA V10.5 | SelfImprovement | Module : Orchestrator | Priorité P0 -->

## Responsabilité unique

Lire les observations récentes et appliquer des règles déterministes JSON pour décider d'actions.
Zéro apprentissage. Zéro appel LLM. Zéro probabilité.

---

## Classe : `OrchestratorLight`

Fichier : `SelfImprove/engines/orchestrator.py`

```python
class OrchestratorLight:
    def __init__(self, dry_run: bool = False, cfg: dict | None = None): ...
    def run(self) -> dict: ...
    # run() → {"triggered": int, "skipped": int, "matched_rules": list[dict]}

    def execute_action(self, rule_id: str, action: str, target: str, params: dict) -> str: ...
    # retourne statut : "success" | "failed" | "skipped" | "pending_ack"
```

---

## Lecture des observations

```python
def _load_signals(self) -> list[dict]:
    """Charge les N derniers fichiers observation, filtre par âge, fusionne les signaux."""
    obs_dir = Path(self._cfg["paths"]["observations_dir"])
    window = self._cfg["orchestrator"]["observation_window"]
    max_age = self._cfg["orchestrator"]["observation_max_age_sec"]

    files = sorted(obs_dir.glob("*.json"), reverse=True)[:window]
    now = datetime.now(timezone.utc).timestamp()
    signals = []
    for f in files:
        data = json.loads(f.read_text("utf-8"))
        obs_ts = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00")).timestamp()
        if now - obs_ts > max_age:
            continue
        signals.extend(data.get("signals", []))

    # Fusion par pattern : count additionné
    merged: dict[str, dict] = {}
    for s in signals:
        key = s["pattern"]
        if key not in merged:
            merged[key] = dict(s)
        else:
            merged[key]["count"] = merged[key].get("count", 1) + s.get("count", 1)
    return list(merged.values())
```

---

## Évaluation des règles

Grammaire unifiée — un seul format pour toutes les conditions :

```python
def _eval_condition(self, condition: dict, signals: list[dict]) -> tuple[bool, list[dict]]:
    """
    Évalue une condition contre les signaux fusionnés.
    Retourne (matched: bool, matching_signals: list).
    """
    field = condition["field"]          # ex: "signal.count" | "signal.severity"
    operator = condition["operator"]    # "==" | ">=" | "<=" | ">" | "<" | "!="
    value = condition["value"]
    filters = condition.get("filters", {})

    # Filtrage des signaux selon les filters
    candidates = [
        s for s in signals
        if all(s.get(k) == v for k, v in filters.items() if k != "scope")
    ]

    if not candidates:
        return False, []

    # Extraction de la valeur du champ
    field_key = field.split(".")[-1]  # "signal.count" → "count"
    matches = []
    for s in candidates:
        actual = s.get(field_key)
        if actual is None:
            continue
        if _compare(actual, operator, value):
            matches.append(s)

    return bool(matches), matches
```

Opérateurs supportés : `==`, `>=`, `<=`, `>`, `<`, `!=`.

---

## Exécution des actions

### `retry_coder_once`

```python
def _action_retry_coder_once(self, target: str, params: dict) -> str:
    mode = get_coupling_mode()
    if mode == 3:
        # Mode 3 : via A2ALocalBus
        from core.agents.a2a_bus import A2ALocalBus, TaskContract
        bus = A2ALocalBus()
        contract = TaskContract(
            intent=f"retry failed tests on {target}",
            context={"test_filter": params.get("test_filter", "only_failed"), "file": target},
            agent_target="coder",
        )
        bus.publish(contract)
        return "success"
    else:
        # Mode 2 : relance directe pytest sur le fichier
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "-m", "pytest", target, "--json-report",
             "--report-file=SelfImprove/observations/temp_results.json", "-x"],
            capture_output=True, timeout=300,
        )
        return "success" if result.returncode == 0 else "failed"
```

### `notify_human`

```python
def _action_notify_human(self, rule_id: str, action: str, target: str, params: dict,
                          require_ack: bool, matching_signals: list) -> str:
    msg = params.get("message_template", "Action requise : {pattern}").format(
        pattern=matching_signals[0].get("pattern", "?") if matching_signals else "?",
        file=matching_signals[0].get("file", "?") if matching_signals else "?",
        count=matching_signals[0].get("count", 0) if matching_signals else 0,
    )
    print(f"\n[LCCA SelfImprove] {msg}")

    if require_ack:
        action_id = add_pending_action(rule_id, action, target, params)
        print(f"  → En attente d'approbation : lcca_si approve {action_id}")
        return "pending_ack"
    return "success"
```

### `trigger_auto_fix`

```python
def _action_trigger_auto_fix(self, params: dict) -> str:
    flag = Path(self._cfg["paths"]["self_improve_dir"]) / ".auto_fix_enabled"
    if not flag.exists():
        log.info("Auto-Fix désactivé (flag absent)")
        return "skipped"
    from SelfImprove.engines.auto_fix import AutoFixEngine
    engine = AutoFixEngine(self._cfg)
    return engine.run(params["pattern_id"])
```

---

## Dry-run

En mode dry-run (`--dry-run`), `execute_action` n'est jamais appelé.
L'Orchestrator collecte les règles matchées dans `matched_rules` et retourne sans effet :

```python
if self._dry_run:
    matched_rules.append({
        "rule_id": rule["id"],
        "action": rule["action"],
        "reason": f"condition matchée : {len(matching_signals)} signal(s)",
    })
    continue  # ne pas appeler execute_action
```

---

## Gestion des erreurs d'action

```python
try:
    status = self.execute_action(rule_id, action, target, params)
except Exception as exc:
    log.error("Action %s échouée : %s", action, exc)
    status = "failed"
    force_cooldown(rule_id, rule.get("cooldown_sec", 300))

log_action(rule_id, action, target, status, details=str(exc if status == "failed" else ""))
```

---

## Conventions LCCA obligatoires

- `log.info("msg %s", var)` — jamais de f-strings dans les logs
- `callable(getattr(obj, "method", None))` avant appel dynamique sur A2ALocalBus
- `check_same_thread=False` si SQLite (A2ALocalBus utilise SQLite :memory:)
- Import A2ALocalBus en lazy (Mode 3 uniquement, évite import circulaire)
- `sys.executable` pour tout appel subprocess Python
