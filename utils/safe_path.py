# -*- coding: utf-8-sig -*-
"""
safe_path.py — LCCA V7
Validation de chemins pour prévenir les attaques de type path traversal.

Tous les outils MCP qui acceptent un chemin en argument DOIVENT appeler
safe_path() avant toute opération disque.

Usage :
    from utils.safe_path import safe_path, PathSecurityError

    full_path = safe_path("relative/file.py")           # OK → Path absolu dans workspace
    full_path = safe_path("../../../etc/passwd")        # → PathSecurityError
    full_path = safe_path("file.py", workspace=custom)  # workspace personnalisé
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


class PathSecurityError(Exception):
    """Levée quand un chemin tente de sortir du workspace autorisé."""


def safe_path(
    relative_path: str | Path,
    workspace: Optional[Path] = None,
) -> Path:
    """
    Résout un chemin relatif et vérifie qu'il reste dans le workspace.

    Args:
        relative_path : Chemin relatif fourni par l'utilisateur / outil MCP.
        workspace     : Répertoire racine autorisé.
                        Par défaut : config.WORKSPACE_DIR.

    Returns:
        Path absolu résolu, garanti dans le workspace.

    Raises:
        PathSecurityError : Si le chemin sort du workspace ou est suspect.
        ValueError        : Si relative_path est vide.
    """
    if workspace is None:
        try:
            from config import WORKSPACE_DIR  # type: ignore
            workspace = WORKSPACE_DIR
        except ImportError:
            workspace = Path("D:/LLMCodeAgent/workspace")

    rel = Path(str(relative_path).strip())

    # Vérifier le vide sur la chaîne originale (Path("") → Path(".") donc non vide)
    if not str(relative_path).strip():
        raise ValueError("Le chemin ne peut pas être vide.")

    # FIX-EDITBATCH-01 : accepter les chemins absolus sous BASE_DIR
    # UNIQUEMENT quand aucun workspace explicite n'est fourni (cas UI via MCP).
    # Si un workspace est fourni (tests, injection), les absolus restent interdits.
    if rel.is_absolute():
        if workspace is not None:
            # Workspace explicite → politique stricte inchangée
            raise PathSecurityError(
                f"Chemin absolu interdit : {relative_path!r}. "
                "Utiliser un chemin relatif au workspace."
            )
        from pathlib import Path as _P
        try:
            from config import BASE_DIR as _BASE  # type: ignore
        except ImportError:
            _BASE = _P("D:/LLMCodeAgent")
        base_resolved = _P(_BASE).resolve()
        full_abs = rel.resolve()
        try:
            full_abs.relative_to(base_resolved)
            return full_abs  # path absolu dans BASE_DIR → accepté (UI MCP)
        except ValueError:
            raise PathSecurityError(
                f"Chemin absolu hors du projet : {relative_path!r}. "
                f"Doit être sous {base_resolved}."
            )

    # Défense en profondeur : rejeter '..' explicitement avant resolve()
    # (resolve() gère aussi, mais cela donne un message d'erreur plus clair)
    if ".." in rel.parts:
        raise PathSecurityError(
            f"Séquence '..' interdite : {relative_path!r}. "
            "Path traversal détecté."
        )

    full = (workspace / rel).resolve()
    workspace_resolved = workspace.resolve()

    # Vérification de containment : full doit être sous workspace_resolved
    try:
        full.relative_to(workspace_resolved)
    except ValueError:
        raise PathSecurityError(
            f"Path traversal détecté : {relative_path!r} → {full} "
            f"est hors du workspace {workspace_resolved}."
        )

    return full


def safe_path_or_none(
    relative_path: str | Path | None,
    workspace: Optional[Path] = None,
) -> Optional[Path]:
    """
    Variante de safe_path qui retourne None si relative_path est None ou vide.
    Utile pour les champs optionnels dans les outils MCP.
    """
    if not relative_path:
        return None
    return safe_path(relative_path, workspace=workspace)
