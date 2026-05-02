# -*- coding: utf-8-sig -*-
"""
orchestrator_pipeline.py — REFACTO-18
Boucle TX/LLM/Patch extraite de LCCAV5Fusion.execute() (phases 3-9).

Responsabilite unique : executer le pipeline V5 core sur un intent + plan deja calcules.

OrchestratorPipeline.run_pipeline(intent, plan, tx_manager, workspace, llm, patcher, indexer, dep_graph)
    → bool

_validate_changes(tx_manager, workspace) → bool

Pas d'import circulaire : ce module n'importe jamais orchestrator.py.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List

log = logging.getLogger("lcca.orchestrator_pipeline")


def _validate_changes(tx_manager, workspace: Path) -> bool:
    """
    Verifie la syntaxe Python de tous les fichiers modifies dans la TX courante.
    Extrait de LCCAV5Fusion._validate_changes() — REFACTO-18.
    """
    if not tx_manager.current_tx:
        return True

    from core.executor import Executor

    modified = [
        op.target_path
        for op in tx_manager.current_tx.operations
        if str(op.target_path).endswith(".py")
    ]

    if not modified:
        return True

    executor = Executor(workspace=workspace, tests_dir=Path("/dev/null"))
    syntax_errors = []
    for rel_path in modified:
        try:
            rel = Path(rel_path).relative_to(workspace)
        except ValueError:
            rel = Path(rel_path).name
        err = executor.check_syntax(str(rel))
        if err:
            syntax_errors.append(err)
            log.error("Syntaxe invalide apres patch: %s", err)

    return len(syntax_errors) == 0


class OrchestratorPipeline:
    """
    Phases 3-9 du pipeline LCCA V5 :
        3. FileSelector  → fichiers cibles
        4. MultiFilePlanner → plan
        5. TransactionManager → BEGIN
        6. LLMGenerator  → code
        7. SmartPatcher  → patches
        8. _validate_changes()
        9. COMMIT / ROLLBACK

    Utilise :
        run_pipeline(intent, tx_manager, workspace, llm, patcher, indexer, dep_graph,
                     planner, selector) -> bool
    """

    def run_pipeline(
        self,
        intent,
        tx_manager,
        workspace: Path,
        llm,
        patcher,
        indexer,
        dep_graph,
        planner,
        selector,
        auto_rollback: bool = True,
    ) -> bool:
        """
        Execute les phases 3-9 du pipeline V5.

        Args:
            intent       : Intent parse (DSLParser).
            tx_manager   : TransactionManager ouvert.
            workspace    : Path racine workspace.
            llm          : LLMGenerator.
            patcher      : SmartPatcher.
            indexer      : ASTIndexer.
            dep_graph    : DependencyGraph.
            planner      : MultiFilePlanner.
            selector     : FileSelector.
            auto_rollback: rollback auto si erreur.

        Returns:
            True si commit OK, False sinon.
        """
        from core.transaction_manager import OpType

        try:
            # ── Phase 3 : selection fichiers ──────────────────────────────────
            target_files = selector.select(intent)
            if not target_files:
                log.error("Aucun fichier cible identifie. Abandon.")
                return False

            log.info("Fichiers cibles: %s", target_files)

            # ── Phase 4 : plan ────────────────────────────────────────────────
            plan = planner.create_plan(
                intent_details=intent.details,
                target_files=target_files,
                intent_action=intent.action,
                intent_target=intent.target,
            )

            valid, errors = planner.validate_plan_consistency(plan)
            if not valid:
                log.error("Plan invalide: %s", errors)
                return False

            log.info("Plan valide: %d operation(s)", len(plan))

            # ── Phase 5 : BEGIN TX ────────────────────────────────────────────
            tx_id = tx_manager.begin(
                dsl_input=str(intent.raw),
                project=intent.project or "lcca",
                intent=f"{intent.action} {intent.details}",
            )
            log.info("Transaction ouverte: %s", tx_id)

            # ── Phases 6-7 : LLM + patch ──────────────────────────────────────
            for op in plan:
                full_path = workspace / op.file

                existing_context = ""
                if full_path.exists():
                    try:
                        existing_context = full_path.read_text(encoding="utf-8-sig")
                    except Exception:
                        pass

                gen_result = llm.generate(op, intent, context=existing_context)
                generated_code = gen_result.code

                if gen_result.from_fallback:
                    log.warning("  LLM indisponible pour %s -> stub", op.file)
                elif gen_result.from_cache:
                    log.debug("  Cache hit pour %s", op.file)
                else:
                    log.info(
                        "  Code genere via %s (%dms)",
                        gen_result.model,
                        gen_result.duration_ms,
                    )

                def _do_patch(
                    _full=full_path, _op=op, _code=generated_code
                ) -> str:
                    if _op.action == "create":
                        _full.parent.mkdir(parents=True, exist_ok=True)
                        _full.write_text(_code, encoding="utf-8-sig")
                        return _code
                    new_code = patcher.apply_patch(
                        str(_full),
                        _op.patch_type,
                        code=_code,
                        name=_op.target_symbol or "",
                    )
                    _full.write_text(new_code, encoding="utf-8-sig")
                    return new_code

                op_type = (
                    OpType.WRITE_FILE if op.action == "create"
                    else OpType.PATCH_FILE
                )
                tx_manager.log_operation(
                    workspace / op.file,
                    op_type,
                    _do_patch,
                    metadata={
                        "intent":      intent.details,
                        "symbol":      op.target_symbol,
                        "patch_type":  op.patch_type,
                        "llm_model":   gen_result.model,
                        "from_cache":  gen_result.from_cache,
                    },
                )
                log.info("  OK %s %s [%s]", op.action, op.file, op.patch_type)

            # ── Phase 8 : validation syntaxe ──────────────────────────────────
            if not _validate_changes(tx_manager, workspace):
                raise RuntimeError("Validation syntaxe echouee apres patch")

            # ── Phase 9 : COMMIT ──────────────────────────────────────────────
            tx_manager.commit()
            log.info("Commit OK — TX: %s", tx_id)

            try:
                indexer.index_repository()
                dep_graph.build(indexer.files)
            except Exception as exc:
                log.warning("Re-indexation partielle: %s", exc)

            return True

        except Exception as exc:
            log.error("Erreur pipeline: %s", exc, exc_info=True)
            if auto_rollback and tx_manager.current_tx is not None:
                try:
                    tx_manager.rollback()
                    log.info("Rollback effectue")
                except Exception as rb_err:
                    log.error("Rollback echoue: %s", rb_err)
            return False
