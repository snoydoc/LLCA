# -*- coding: utf-8-sig -*-
"""
planner.py — LCCA V5 Fusion
Sprint 04 — TASK-04-03 (refonte de la version Sprint 01)

Ordonnancement des opérations multi-fichiers pour l'Orchestrateur.
Gère : PatchOperation, Plan, MultiFilePlanner + validation de cohérence.

Contrainte hard : MAX_FILES_PER_TX = 3 (depuis config)
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger("lcca.planner")


# ──────────────────────────────────────────────────────────────────────────────
# Enums & Dataclasses
# ──────────────────────────────────────────────────────────────────────────────

class OpPriority(enum.IntEnum):
    """Priorité d'exécution d'une opération (plus bas = plus tôt)."""
    HIGH   = 1
    NORMAL = 2
    LOW    = 3


@dataclass
class PatchOperation:
    """
    Opération atomique élémentaire : un patch sur un fichier précis.
    Rétrocompatible avec la version Sprint 01.
    """
    file: Path
    operation: str           # "add_function" | "modify_function" | "add_import" | "create"
    target_name: str = ""    # Nom du symbole concerné (fonction, classe)
    code: str = ""           # Code source à injecter


@dataclass
class PlannedOperation:
    """
    Opération enrichie utilisée par MultiFilePlanner (Sprint 04).
    Étend PatchOperation avec métadonnées d'ordonnancement.
    """
    file: str                              # Chemin relatif au workspace
    action: str                            # 'create' | 'modify' | 'delete'
    target_symbol: Optional[str]           # Symbole cible (fonction/classe)
    description: str                       # Description lisible pour les logs
    dependencies: List[str] = field(default_factory=list)  # Fichiers requis avant
    priority: OpPriority = OpPriority.NORMAL
    patch_type: str = "add_function"       # 'add_function' | 'modify_function' | 'add_import'

    @property
    def file_path(self) -> Path:
        return Path(self.file)



@dataclass
class Plan:
    """
    Plan d'exécution : liste ordonnée de PatchOperation.
    Rétrocompatible avec la version Sprint 01.
    """
    task_label: str
    operations: list[PatchOperation] = field(default_factory=list)

    def is_valid(self, max_files: int = 3) -> bool:
        """Vérifie que le plan ne dépasse pas max_files fichiers distincts."""
        unique_files = {op.file for op in self.operations}
        return len(unique_files) <= max_files


# ──────────────────────────────────────────────────────────────────────────────
# Planner (API Sprint 01 — conservée pour rétrocompatibilité)
# ──────────────────────────────────────────────────────────────────────────────

class Planner:
    """
    API manuelle Sprint 01.
    Construit un Plan depuis une liste de dicts fournis par l'utilisateur.
    """

    def build(self, task_label: str, operations: list[dict]) -> Plan:
        """
        Construit un Plan depuis une liste de dicts.

        Format attendu :
            [{"file": "path.py", "operation": "add_function",
              "target_name": "fn", "code": "def fn(): ..."}]

        Raises:
            ValueError: Si plus de MAX_FILES_PER_TX fichiers distincts.
        """
        from config import MAX_FILES_PER_TX

        patch_ops = [
            PatchOperation(
                file=Path(op["file"]),
                operation=op["operation"],
                target_name=op.get("target_name", ""),
                code=op.get("code", ""),
            )
            for op in operations
        ]
        plan = Plan(task_label=task_label, operations=patch_ops)

        if not plan.is_valid(max_files=MAX_FILES_PER_TX):
            unique = {str(op.file) for op in patch_ops}
            raise ValueError(
                f"Plan dépasse MAX_FILES_PER_TX={MAX_FILES_PER_TX}. "
                f"Fichiers: {unique}"
            )
        return plan


# ──────────────────────────────────────────────────────────────────────────────
# MultiFilePlanner (Sprint 04 — planification automatique)
# ──────────────────────────────────────────────────────────────────────────────

class MultiFilePlanner:
    """
    Planificateur automatique Sprint 04.
    À partir d'un Intent + liste de fichiers cibles, produit des PlannedOperation
    triées par dépendances (tri topologique simple).
    """

    def create_plan(
        self,
        intent_details: str,
        target_files: List[str],
        intent_action: str = "modifie",
        intent_target: str = "",
    ) -> List[PlannedOperation]:
        """
        Génère un plan d'opérations à partir de l'intent et des fichiers sélectionnés.

        Args:
            intent_details: Détails de l'action (ex: "validate_email()").
            target_files:   Liste de chemins relatifs (depuis FileSelector).
            intent_action:  Action normalisée (ajoute / modifie / supprime / cree).
            intent_target:  Terme cible (ex: "Auth", "Modal").

        Returns:
            Liste de PlannedOperation triée (fichiers sans dépendances en premier).
        """
        from config import MAX_FILES_PER_TX

        if not target_files:
            return []

        # Dédoublonnage + limite MAX
        seen: set[str] = set()
        unique_files: list[str] = []
        for f in target_files:
            if f not in seen:
                seen.add(f)
                unique_files.append(f)
            if len(unique_files) >= MAX_FILES_PER_TX:
                break

        ops: list[PlannedOperation] = []
        for file in unique_files:
            action, patch_type, priority = self._infer_op_params(
                intent_action, file, intent_target, intent_details
            )
            symbol = self._infer_symbol(intent_details)
            op = PlannedOperation(
                file=file,
                action=action,
                target_symbol=symbol,
                description=f"{intent_action} {intent_details} dans {file}",
                dependencies=[],          # V1: pas de dépendances croisées
                priority=priority,
                patch_type=patch_type,
            )
            ops.append(op)
            log.debug("PlannedOp: %s %s → %s", action, patch_type, file)

        return self._topological_sort(ops)

    # ── Validation ────────────────────────────────────────────────────────────

    def validate_plan_consistency(
        self, ops: List[PlannedOperation]
    ) -> Tuple[bool, List[str]]:
        """
        Vérifie la cohérence d'un plan.

        Règles :
            - Pas le même symbole modifié 2 fois
            - Pas de fichier supprimé ET modifié dans la même TX
            - Max MAX_FILES_PER_TX fichiers distincts

        Returns:
            (valide: bool, erreurs: List[str])
        """
        from config import MAX_FILES_PER_TX

        errors: list[str] = []

        # Règle 1 : max fichiers
        distinct_files = {op.file for op in ops}
        if len(distinct_files) > MAX_FILES_PER_TX:
            errors.append(
                f"Trop de fichiers ({len(distinct_files)} > {MAX_FILES_PER_TX}): "
                f"{distinct_files}"
            )

        # Règle 2 : même symbole modifié 2× dans des fichiers différents
        symbol_files: dict[str, list[str]] = {}
        for op in ops:
            if op.target_symbol:
                symbol_files.setdefault(op.target_symbol, []).append(op.file)
        for sym, files in symbol_files.items():
            if len(files) > 1:
                errors.append(
                    f"Symbole '{sym}' modifié dans plusieurs fichiers: {files}"
                )

        # Règle 3 : fichier supprimé ET modifié
        deleted = {op.file for op in ops if op.action == "delete"}
        modified = {op.file for op in ops if op.action in {"modify", "create"}}
        conflict = deleted & modified
        if conflict:
            errors.append(
                f"Fichier(s) à la fois supprimé(s) et modifié(s): {conflict}"
            )

        is_valid = len(errors) == 0
        if not is_valid:
            log.warning(f"Plan invalide: {errors}")
        return is_valid, errors

    # ── Helpers internes ──────────────────────────────────────────────────────

    def _infer_op_params(
        self,
        intent_action: str,
        file: str,
        intent_target: str,
        intent_details: str,
    ) -> Tuple[str, str, OpPriority]:
        """Déduit (action, patch_type, priority) depuis l'intent."""
        action_map = {
            "ajoute":  ("modify", "add_function",    OpPriority.NORMAL),
            "modifie": ("modify", "modify_function", OpPriority.NORMAL),
            "supprime": ("delete", "add_function",   OpPriority.LOW),
            "cree":    ("create", "add_function",    OpPriority.HIGH),
            "crée":    ("create", "add_function",    OpPriority.HIGH),
            "refactor": ("modify", "modify_function", OpPriority.LOW),
            "corrige": ("modify", "modify_function", OpPriority.HIGH),
        }
        defaults = ("modify", "add_function", OpPriority.NORMAL)
        action, patch_type, priority = action_map.get(intent_action.lower(), defaults)

        # Si le detail contient "import" → patch_type prioritaire
        if "import" in intent_details.lower():
            patch_type = "add_import"

        # Fichiers "core" ont priorité haute
        if "core" in file.lower() or "__init__" in file:
            priority = OpPriority.HIGH

        return action, patch_type, priority

    def _infer_symbol(self, details: str) -> Optional[str]:
        """Extrait le nom de symbole depuis les détails (ex: 'validate_email()' → 'validate_email')."""
        import re
        match = re.search(r'\b([a-zA-Z_]\w*)\s*\(', details)
        if match:
            return match.group(1)
        # Pas de parenthèses → premier mot en snake_case
        words = details.strip().split()
        if words:
            candidate = words[0]
            if re.match(r'^[a-zA-Z_]\w*$', candidate):
                return candidate
        return None

    def _topological_sort(self, ops: List[PlannedOperation]) -> List[PlannedOperation]:
        """
        Tri topologique simple par priorité + dépendances.
        Fichiers sans dépendances et haute priorité en premier.
        """
        # Tri stable : HIGH (1) < NORMAL (2) < LOW (3)
        return sorted(ops, key=lambda op: (op.priority.value, len(op.dependencies)))
