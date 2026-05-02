# -*- coding: utf-8-sig -*-
"""
file_selector.py — LCCA V5 Fusion
Sprint 04 — TASK-04-02

Sélection intelligente des fichiers à modifier à partir d'un Intent.
Combine :
    1. Recherche par symbole exact dans l'index AST
    2. Correspondance par nom de fichier (substring, case-insensitive)
    3. Recherche par contenu (multi-termes, fallback)

Contrainte hard : MAX_FILES_PER_TX = 3 (depuis config)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

log = logging.getLogger("lcca.file_selector")


class FileSelector:
    """
    Sélectionne les fichiers workspace pertinents pour un Intent.

    Attributes:
        indexer:   ASTIndexer déjà initialisé (index_repository() appelé).
        dep_graph: DependencyGraph pour étendre les candidats si nécessaire.
        workspace: Chemin racine du workspace (pour créer de nouveaux chemins).
    """

    def __init__(self, indexer, dep_graph, workspace: Path) -> None:
        """
        Args:
            indexer:   Instance ASTIndexer (index_repository() déjà exécuté).
            dep_graph: Instance DependencyGraph (build() déjà exécuté).
            workspace: Chemin absolu vers le dossier workspace/.
        """
        self.indexer = indexer
        self.dep_graph = dep_graph
        self.workspace = workspace

    def select(self, intent) -> List[str]:
        """
        Retourne une liste de chemins relatifs (max MAX_FILES_PER_TX).

        Ordre de priorité :
            1. Symbole exact dans la table d'index
            2. Nom de fichier contient le terme (target ou sub_target)
            3. Recherche dans le contenu brut du fichier
            4. Si action "crée"/"ajoute" et aucun match → chemin suggéré

        Args:
            intent: Objet Intent issu de DSLParser.

        Returns:
            Liste de chemins relatifs au workspace (strings).
        """
        from config import MAX_FILES_PER_TX

        candidates: list[str] = []
        seen: set[str] = set()

        def _add(path: str) -> None:
            if path not in seen:
                seen.add(path)
                candidates.append(path)

        # ── Stratégie 1 : symbole exact dans l'index AST ─────────────────────
        search_terms = [
            t for t in [intent.target, intent.sub_target, intent.details]
            if t and len(t) >= 2
        ]
        for term in search_terms:
            # Nettoie le terme : retire les parenthèses (ex: "validate_email()")
            clean = term.strip().rstrip("()")
            # Cherche dans la table de symboles
            matching_syms = self.indexer.symbols_table.get(clean, [])
            for sym in matching_syms:
                try:
                    rel = str(Path(sym.file).relative_to(self.workspace))
                    _add(rel)
                    log.debug(f"Symbole '{clean}' trouvé dans {rel}")
                except ValueError:
                    # sym.file est peut-être déjà relatif
                    _add(sym.file)

        # ── Stratégie 2 : nom de fichier contient le terme ────────────────────
        for rel_path in self.indexer.files:
            path_lower = rel_path.lower().replace("\\", "/")
            for term in [intent.target, intent.sub_target]:
                if not term:
                    continue
                term_norm = term.lower().replace(" ", "_")
                if term_norm in path_lower or term.lower() in path_lower:
                    _add(rel_path)
                    log.debug(f"Nom fichier match '{term}' → {rel_path}")
                    break

        # ── Stratégie 3 : contenu du fichier contient les termes ─────────────
        if len(candidates) < MAX_FILES_PER_TX:
            content_terms = [
                t.lower().rstrip("()")
                for t in search_terms
                if len(t.rstrip("()")) >= 3
            ]
            if content_terms:
                for rel_path, fi in self.indexer.files.items():
                    if rel_path in seen:
                        continue
                    content_lower = fi.raw_content.lower()
                    if all(t in content_lower for t in content_terms):
                        _add(rel_path)
                        log.debug(f"Contenu match {content_terms} → {rel_path}")
                        if len(candidates) >= MAX_FILES_PER_TX:
                            break

        # ── Fallback : action de création et aucun match ──────────────────────
        if not candidates and intent.action in {"crée", "cree", "ajoute"}:
            target_slug = (
                intent.target.lower()
                .replace(" ", "_")
                .strip("_")
            )
            suggested = f"src/{target_slug}.py"
            log.info(f"Aucun fichier trouvé, suggestion : {suggested}")
            return [suggested]

        result = candidates[:MAX_FILES_PER_TX]
        log.info(
            f"FileSelector → {len(result)} fichier(s) sélectionné(s): {result}"
        )
        return result

    def find_symbol_definition(self, name: str) -> list:
        """
        Raccourci vers l'index pour trouver un symbole par nom.

        Args:
            name: Nom du symbole recherché.

        Returns:
            Liste de Symbol (peut être vide).
        """
        clean = name.strip().rstrip("()")
        return self.indexer.symbols_table.get(clean, [])
