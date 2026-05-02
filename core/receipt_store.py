# -*- coding: utf-8-sig -*-
"""
Audit trail A2A avec HMAC local.
Cle stockee dans .secret/a2a_key (hors git, chmod 600 sur Linux/Mac).
V8-Regle-17 : Aucun skill stocke sans ExecutionReceipt valide.
"""
import hmac
import hashlib
import json
import secrets
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import BASE_DIR

SECRET_DIR   = BASE_DIR / ".secret"
KEY_PATH     = SECRET_DIR / "a2a_key"
RECEIPTS_DIR = BASE_DIR / "memory" / "receipts"


@dataclass
class ExecutionReceipt:
    """Receipt d'execution signe par HMAC. Produit par TesterAgent."""
    task_id:        str
    agent:          str
    input_hash:     str
    output_hash:    str
    sandbox_passed: bool
    tests_passed:   int
    tests_failed:   int
    tx_id:          Optional[str]
    timestamp:      str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    signature:      str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ExecutionReceipt":
        fields = {k for k in cls.__dataclass_fields__}
        return cls(**{k: d.get(k) for k in fields})


def _ensure_key() -> bytes:
    """Cree la cle HMAC si elle n'existe pas encore."""
    SECRET_DIR.mkdir(parents=True, exist_ok=True)
    if not KEY_PATH.exists():
        key = secrets.token_hex(32).encode()
        KEY_PATH.write_bytes(key)
        if sys.platform != "win32":
            import os
            os.chmod(KEY_PATH, 0o600)
    return KEY_PATH.read_bytes()


def sign_receipt(task_id: str, output_hash: str) -> str:
    """Signe task_id + output_hash avec la cle locale. Retourne hexdigest."""
    key = _ensure_key()
    payload = f"{task_id}:{output_hash}".encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def verify_receipt(receipt: ExecutionReceipt) -> bool:
    """Verifie l'integrite HMAC d'un receipt. Retourne False si tampered."""
    try:
        expected = sign_receipt(receipt.task_id, receipt.output_hash)
        return hmac.compare_digest(expected, receipt.signature)
    except Exception:
        return False


def store_receipt(receipt: ExecutionReceipt):
    """Persiste le receipt dans memory/receipts/{task_id}.json."""
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RECEIPTS_DIR / f"{receipt.task_id}.json"
    path.write_text(
        json.dumps(receipt.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_receipt(task_id: str) -> Optional[ExecutionReceipt]:
    """Charge un receipt depuis le disque. Retourne None si absent."""
    path = RECEIPTS_DIR / f"{task_id}.json"
    if not path.exists():
        return None
    return ExecutionReceipt.from_dict(
        json.loads(path.read_text(encoding="utf-8"))
    )


def rotate_key() -> int:
    """
    Regenere la cle HMAC. Invalide tous les receipts existants.
    Retourne le nombre de fichiers invalides.
    """
    count = 0
    if RECEIPTS_DIR.exists():
        for f in RECEIPTS_DIR.glob("*.json"):
            f.rename(f.with_suffix(".invalid"))
            count += 1
    KEY_PATH.unlink(missing_ok=True)
    _ensure_key()
    return count
