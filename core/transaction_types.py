# -*- coding: utf-8-sig -*-
"""
transaction_types.py — Dataclasses et enums partagés du TransactionManager (Sprint REFACTO-01).

Zéro logique métier — que des structures de données.
Importé par transaction_manager.py et tout module qui manipule des types TX.

Rétrocompatibilité : ces types sont ré-exportés depuis transaction_manager.py,
donc les imports existants `from core.transaction_manager import TxStatus` continuent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class TxStatus(Enum):
    PENDING     = "pending"
    RUNNING     = "running"
    COMMITTED   = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED      = "failed"


class OpType(Enum):
    WRITE_FILE  = "write_file"
    EDIT_FILE   = "edit_file"
    DELETE_FILE = "delete_file"
    PATCH_FILE  = "patch_file"   # Modification AST (principal)
    CREATE_FILE = "create_file"  # V7 — fichier inexistant avant TX
    CREATE_DIR  = "create_dir"
    MOVE_FILE   = "move_file"


@dataclass
class FileSnapshot:
    """État complet d'un fichier à un instant T."""
    path: str
    content_hash: Optional[str]  # MD5 du contenu ; None si fichier absent
    content: Optional[str]
    exists: bool                  # True si fichier existait avant l'op
    mtime: Optional[float]        # None si fichier absent


@dataclass
class Operation:
    """Une opération atomique enregistrée dans la transaction."""
    op_id: str                          # UUID court : 8 chars hex
    type: OpType
    target_path: str
    before: FileSnapshot
    after: Optional[FileSnapshot]
    timestamp: str
    metadata: Dict[str, Any]
    rollback_data: Optional[str] = None  # Path vers backup physique (.bak)


@dataclass
class Transaction:
    """Contexte complet d'une transaction en cours ou terminée."""
    tx_id: str
    dsl_input: str
    project: str
    intent: str
    status: TxStatus
    created_at: str
    completed_at: Optional[str]
    operations: List[Operation] = field(default_factory=list)
    context_refs: List[str] = field(default_factory=list)
    checkpoint_path: Optional[str] = None


class TransactionError(RuntimeError):
    """Erreur levée quand la transaction ne peut pas continuer."""
