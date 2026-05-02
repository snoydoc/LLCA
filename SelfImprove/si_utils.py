# -*- coding: utf-8 -*-
"""
SelfImprove — Utilitaires communs V10.5
Fonctions partagées : actions.log write-ahead, pending_actions, écriture atomique.
Conforme aux conventions LCCA (skill 001).
"""
from __future__ import annotations

import csv
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from SelfImprove.si_config import load_config, get_paths

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Écriture atomique (correction race condition — spec V10.5 §4.4)
# ---------------------------------------------------------------------------

def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Écrit payload en JSON de façon atomique : .tmp → rename.

    Jamais de JSON corrompu même si le process est interrompu pendant l'écriture.
    """
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)  # replace() est atomique et remplace sur Windows et Linux
    except Exception as exc:  # noqa: BLE001
        log.error("atomic_write_json échoué sur %s : %s", path, exc)
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# actions.log — write-ahead CSV (spec V10.5 §5.9)
# ---------------------------------------------------------------------------

def log_action(
    rule_id: str,
    action: str,
    target: str,
    status: str,
    details: str = "",
    cfg: dict[str, Any] | None = None,
) -> None:
    """Écrit une ligne dans actions.log AVANT l'exécution de l'action.

    Format CSV : timestamp,rule_id,action,target,status,details
    """
    if cfg is None:
        cfg = load_config()
    actions_log = Path(cfg["paths"]["actions_log"])
    actions_log.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = [timestamp, rule_id, action, target, status, details]

    try:
        with actions_log.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(row)
    except Exception as exc:  # noqa: BLE001
        log.error("log_action échoué : %s", exc)


# ---------------------------------------------------------------------------
# pending_actions.json (spec V10.5 §5.7)
# ---------------------------------------------------------------------------

def add_pending_action(
    rule_id: str,
    action: str,
    target: str,
    params: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> str:
    """Ajoute une action en attente d'ACK humain. Retourne l'action_id."""
    if cfg is None:
        cfg = load_config()
    pending_path = Path(cfg["paths"]["pending_actions"])

    action_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    entry: dict[str, Any] = {
        "action_id": action_id,
        "timestamp": timestamp,
        "rule_id": rule_id,
        "action": action,
        "target": target,
        "params": params,
        "status": "pending",
        "requires_ack": True,
    }

    # Lecture → modification → écriture atomique
    existing = _read_pending(pending_path)
    existing["actions"].append(entry)
    atomic_write_json(pending_path, existing)

    log.info("Action en attente ajoutée : %s (rule=%s)", action_id, rule_id)
    return action_id


def approve_pending_action(action_id: str, cfg: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Passe le statut d'une action pending à 'approved'. Retourne l'entrée ou None."""
    if cfg is None:
        cfg = load_config()
    pending_path = Path(cfg["paths"]["pending_actions"])

    data = _read_pending(pending_path)
    approved = None
    for entry in data["actions"]:
        if entry["action_id"] == action_id and entry["status"] == "pending":
            entry["status"] = "approved"
            entry["approved_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            approved = entry
            break

    if approved:
        atomic_write_json(pending_path, data)
        log.info("Action approuvée : %s", action_id)
    else:
        log.warning("Action introuvable ou non-pending : %s", action_id)

    return approved


def _read_pending(path: Path) -> dict[str, Any]:
    """Lit pending_actions.json. Retourne structure vide si absent ou corrompu."""
    if not path.exists():
        return {"actions": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.error("Lecture pending_actions.json échouée : %s", exc)
        return {"actions": []}


# ---------------------------------------------------------------------------
# Cooldown tracker (en mémoire — remis à zéro au restart, c'est voulu)
# ---------------------------------------------------------------------------

_cooldowns: dict[str, float] = {}
_trigger_counts: dict[str, int] = {}
_trigger_date: dict[str, str] = {}


def check_and_update_cooldown(rule_id: str, cooldown_sec: int, max_per_day: int) -> bool:
    """Vérifie si une règle peut être déclenchée (cooldown + max_trigger_per_day).

    Retourne True si la règle PEUT être déclenchée, False sinon.
    Met à jour les compteurs si True.
    """
    import time

    now = time.monotonic()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Reset compteur quotidien si nouveau jour
    if _trigger_date.get(rule_id) != today:
        _trigger_counts[rule_id] = 0
        _trigger_date[rule_id] = today

    # Vérification max_per_day
    if _trigger_counts.get(rule_id, 0) >= max_per_day:
        log.info("Règle %s : max_trigger_per_day (%s) atteint", rule_id, max_per_day)
        return False

    # Vérification cooldown
    last = _cooldowns.get(rule_id, 0.0)
    if now - last < cooldown_sec:
        remaining = int(cooldown_sec - (now - last))
        log.info("Règle %s : cooldown actif (%ss restantes)", rule_id, remaining)
        return False

    # Mise à jour
    _cooldowns[rule_id] = now
    _trigger_counts[rule_id] = _trigger_counts.get(rule_id, 0) + 1
    return True


def force_cooldown(rule_id: str, cooldown_sec: int) -> None:
    """Force le cooldown d'une règle (ex: après échec d'action)."""
    import time
    _cooldowns[rule_id] = time.monotonic()
    log.info("Cooldown forcé sur règle %s (%ss)", rule_id, cooldown_sec)
