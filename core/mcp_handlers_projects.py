# -*- coding: utf-8-sig -*-
"""
mcp_handlers_projects.py — PROJ-04
10 handlers MCP Mode Projets.

Responsabilite unique : handlers project_open, project_close, project_list,
project_create, project_archive, project_switch, project_get_context,
project_save_context, project_healthcheck, project_compact_history.

McpHandlersProjects est un mixin pur : aucun __init__, aucun lifecycle.
Suppose que self._project_manager, self._project_lock, self._project_orch
sont injectes (ou instancies lazy via _get_project_*).
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

log = logging.getLogger("lcca.mcp_handlers_projects")

# Contexte actif en memoire (un seul projet ouvert a la fois par process MCP)
_active_context = None


class McpHandlersProjects:
    """
    Mixin portant les 10 handlers tools Mode Projets.

    Attributs optionnels injectes par McpServer (tous avec valeur par defaut None) :
        self._project_manager  — ProjectManager
        self._project_lock     — ProjectLock
        self._project_orch     — ProjectOrchestrator
    """

    # ------------------------------------------------------------------
    # Getters lazy (instanciation a la premiere utilisation)
    # ------------------------------------------------------------------

    def _get_project_manager(self):
        if not hasattr(self, "_project_manager") or self._project_manager is None:
            from core.project_manager import ProjectManager
            self._project_manager = ProjectManager()
        return self._project_manager

    def _get_project_lock(self):
        if not hasattr(self, "_project_lock") or self._project_lock is None:
            from core.project_lock import ProjectLock
            self._project_lock = ProjectLock()
        return self._project_lock

    def _get_project_orchestrator(self):
        if not hasattr(self, "_project_orch") or self._project_orch is None:
            from core.project_loader import ProjectLoader
            from core.project_context_assembler import ProjectContextAssembler
            from core.project_checkpoint import ProjectCheckpoint
            from core.project_orchestrator import ProjectOrchestrator
            pm   = self._get_project_manager()
            lock = self._get_project_lock()
            self._project_orch = ProjectOrchestrator(
                project_manager=pm,
                lock=lock,
                loader=ProjectLoader(pm, lock),
                assembler=ProjectContextAssembler(),
                checkpoint=ProjectCheckpoint(),
            )
        return self._project_orch

    # ------------------------------------------------------------------
    # Helpers contexte actif
    # ------------------------------------------------------------------

    def _active_ctx(self):
        """Retourne le contexte actif (None si aucun projet ouvert)."""
        global _active_context
        return _active_context

    def _set_active_ctx(self, ctx) -> None:
        global _active_context
        _active_context = ctx

    # ------------------------------------------------------------------
    # Handlers tools
    # ------------------------------------------------------------------

    def _tool_project_list(self, args: Dict) -> Dict:
        """Liste tous les projets actifs (+ archived si demande)."""
        include_archived = bool(args.get("include_archived", False))
        pm = self._get_project_manager()
        projects = pm.list_projects(include_archived=include_archived)
        return {
            "projects": [
                {
                    "id":          p.id,
                    "slug":        p.slug,
                    "name":        p.name,
                    "status":      p.status,
                    "last_opened": p.last_opened,
                    "description": p.description,
                    "tags":        p.tags,
                }
                for p in projects
            ],
            "count": len(projects),
        }

    def _tool_project_create(self, args: Dict) -> Dict:
        """Cree un nouveau projet LCCA V10."""
        name = str(args.get("name", "")).strip()
        if not name:
            raise ValueError("'name' est requis et ne peut pas etre vide")
        description  = str(args.get("description", ""))
        storage_mode = str(args.get("storage_mode", "shared"))
        tags         = args.get("tags", [])
        if not isinstance(tags, list):
            raise TypeError("'tags' doit etre une liste de chaines")

        pm   = self._get_project_manager()
        meta = pm.create_project(
            name=name,
            description=description,
            storage_mode=storage_mode,
            tags=tags,
        )
        log.info("MCP project_create : slug=%s id=%s", meta.slug, meta.id)
        return {
            "created": True,
            "id":      meta.id,
            "slug":    meta.slug,
            "name":    meta.name,
            "status":  meta.status,
        }

    def _tool_project_open(self, args: Dict) -> Dict:
        """Ouvre un projet (charge le contexte, acquiert le lock)."""
        project_id = str(args.get("project_id", "")).strip()
        if not project_id:
            raise ValueError("'project_id' est requis")

        orch = self._get_project_orchestrator()
        ctx  = orch.load_project(project_id)
        self._set_active_ctx(ctx)

        log.info("MCP project_open : id=%s slug=%s", ctx.meta.id, ctx.meta.slug)
        return {
            "opened":          True,
            "id":              ctx.meta.id,
            "slug":            ctx.meta.slug,
            "name":            ctx.meta.name,
            "status":          ctx.meta.status,
            "skills_count":    len(ctx.skills),
            "specs_count":     len(ctx.specs),
            "history_entries": len(ctx.history_window),
        }

    def _tool_project_close(self, args: Dict) -> Dict:
        """Ferme le projet actif (sauvegarde checkpoint + release lock)."""
        ctx = self._active_ctx()
        if ctx is None:
            return {"closed": False, "reason": "Aucun projet ouvert"}

        orch = self._get_project_orchestrator()
        slug = ctx.meta.slug
        orch.save_project(ctx)
        self._set_active_ctx(None)

        log.info("MCP project_close : slug=%s", slug)
        return {"closed": True, "slug": slug}

    def _tool_project_archive(self, args: Dict) -> Dict:
        """Archive un projet (status: active -> archived)."""
        project_id = str(args.get("project_id", "")).strip()
        if not project_id:
            raise ValueError("'project_id' est requis")

        pm      = self._get_project_manager()
        success = pm.archive_project(project_id)
        if not success:
            return {"archived": False, "reason": f"Projet introuvable : {project_id}"}

        log.info("MCP project_archive : id=%s", project_id)
        return {"archived": True, "project_id": project_id}

    def _tool_project_switch(self, args: Dict) -> Dict:
        """Ferme le projet courant (si ouvert) puis ouvre le projet cible."""
        project_id = str(args.get("project_id", "")).strip()
        if not project_id:
            raise ValueError("'project_id' est requis")

        # Fermer le projet actif si besoin
        closed_slug: Optional[str] = None
        ctx = self._active_ctx()
        if ctx is not None:
            closed_slug = ctx.meta.slug
            orch = self._get_project_orchestrator()
            orch.save_project(ctx)
            self._set_active_ctx(None)

        # Ouvrir le nouveau
        orch    = self._get_project_orchestrator()
        new_ctx = orch.load_project(project_id)
        self._set_active_ctx(new_ctx)

        log.info("MCP project_switch : closed=%s opened=%s", closed_slug, new_ctx.meta.slug)
        return {
            "switched":    True,
            "closed_slug": closed_slug,
            "opened_id":   new_ctx.meta.id,
            "opened_slug": new_ctx.meta.slug,
            "opened_name": new_ctx.meta.name,
        }

    def _tool_project_get_context(self, args: Dict) -> Dict:
        """Retourne le contexte du projet actif (meta + stats)."""
        ctx = self._active_ctx()
        if ctx is None:
            return {"active": False, "context": None}

        return {
            "active": True,
            "context": {
                "id":              ctx.meta.id,
                "slug":            ctx.meta.slug,
                "name":            ctx.meta.name,
                "status":          ctx.meta.status,
                "storage_mode":    ctx.meta.storage_mode,
                "skills_count":    len(ctx.skills),
                "specs_count":     len(ctx.specs),
                "history_entries": len(ctx.history_window),
                "user_prefix":     ctx.user_prefix,
                "snapshot_keys":   list(ctx.snapshot.keys()),
            },
        }

    def _tool_project_save_context(self, args: Dict) -> Dict:
        """Force un checkpoint (sauvegarde context_snapshot.json sans fermer)."""
        ctx = self._active_ctx()
        if ctx is None:
            return {"saved": False, "reason": "Aucun projet ouvert"}

        from core.project_checkpoint import ProjectCheckpoint
        ckpt = ProjectCheckpoint()
        ckpt.save(ctx)

        log.info("MCP project_save_context : slug=%s", ctx.meta.slug)
        return {"saved": True, "slug": ctx.meta.slug}

    def _tool_project_healthcheck(self, args: Dict) -> Dict:
        """Rapport de sante complet d'un projet (delegue a ProjectHealthChecker)."""
        project_id = str(args.get("project_id", "")).strip()
        # Si pas de project_id, utilise le projet actif
        if not project_id:
            ctx = self._active_ctx()
            if ctx is None:
                return {
                    "healthy": False,
                    "reason":  "Aucun projet ouvert et project_id absent",
                }
            project_id = ctx.meta.id

        pm   = self._get_project_manager()
        meta = pm.get_project(project_id)
        if meta is None:
            return {
                "healthy":    False,
                "project_id": project_id,
                "issues":     [f"Projet introuvable : {project_id}"],
                "issues_count": 1,
            }

        from core.project_manager import _LCCA_ROOT
        from core.project_health_checker import ProjectHealthChecker
        project_dir = _LCCA_ROOT / "projects" / meta.slug

        checker = ProjectHealthChecker()
        report  = checker.check(project_dir, meta)

        log.info(
            "MCP project_healthcheck : slug=%s healthy=%s issues=%d",
            meta.slug, report.healthy, len(report.issues),
        )
        return report.to_dict()

    def _tool_inspiration_generate(self, args: Dict) -> Dict:
        """
        Genere 3 idees de projets via le LLM local (PROJ-UI-02).

        Parametres :
            keyword (str) : domaine / theme (ex: 'agent medical')
            online  (bool): True = tenter un modele online (non supporte en V1, ignore)

        Retourne :
            {ideas: [IdeaCard, ...], keyword: str, source: 'llm'|'fallback'}
        """
        keyword = str(args.get("keyword", "")).strip()
        if not keyword:
            raise ValueError("'keyword' est requis")
        if len(keyword) > 120:
            keyword = keyword[:120]

        try:
            ideas = self._inspiration_call_llm(keyword)
            source = "llm"
        except Exception as exc:
            log.warning("inspiration_generate : LLM indisponible, fallback templates (%s)", exc)
            ideas = self._inspiration_fallback(keyword)
            source = "fallback"

        return {"ideas": ideas, "keyword": keyword, "source": source}

    # ------------------------------------------------------------------
    # Helpers inspiration (prives)
    # ------------------------------------------------------------------

    _INSP_SYSTEM = (
        "Tu es un assistant expert en architecture logicielle. "
        "Reponds UNIQUEMENT en JSON valide, sans explication, sans markdown. "
        "Format attendu : [{\"title\":\"...\",\"description\":\"...\","
        "\"domain\":\"...\",\"tech_stack\":[...],"
        "\"difficulty\":\"debutant|intermediaire|avance\","
        "\"estimated_sprints\":N,\"tags\":[...],\"quality_score\":0.7}]"
    )

    def _inspiration_call_llm(self, keyword: str):
        """Appel LLM Ollama — retourne liste de 3 IdeaCard (dicts)."""
        import json as _json
        from core.llm_generator import LLMGenerator

        gen = LLMGenerator()
        prompt = (
            f"Genere exactement 3 idees de projets logiciels sur le theme : '{keyword}'. "
            "Reponds avec un tableau JSON de 3 objets. "
            "Chaque objet doit avoir : title, description, domain, tech_stack (liste), "
            "difficulty ('debutant'|'intermediaire'|'avance'), "
            "estimated_sprints (entier), tags (liste), quality_score (float 0-1). "
            "UNIQUEMENT le JSON brut, pas de markdown, pas de texte avant ou apres."
        )
        raw = gen.generate_text(
            system=self._INSP_SYSTEM,
            user=prompt,
        )
        # Nettoyer les blocs markdown eventuels
        clean = raw.strip()
        if clean.startswith("```"):
            lines = clean.splitlines()
            clean = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        ideas = _json.loads(clean)
        if not isinstance(ideas, list):
            raise ValueError("LLM n'a pas retourne une liste")

        # Normaliser et valider chaque idee
        valid = []
        for item in ideas[:3]:
            if not isinstance(item, dict):
                continue
            valid.append({
                "title":             str(item.get("title", f"Projet {keyword}")),
                "description":       str(item.get("description", "")),
                "domain":            str(item.get("domain", keyword)),
                "tech_stack":        list(item.get("tech_stack", [])),
                "difficulty":        str(item.get("difficulty", "intermediaire")),
                "estimated_sprints": int(item.get("estimated_sprints", 8)),
                "tags":              list(item.get("tags", [])),
                "quality_score":     float(item.get("quality_score", 0.70)),
            })

        if not valid:
            raise ValueError("Aucune idee valide dans la reponse LLM")
        return valid

    @staticmethod
    def _inspiration_fallback(keyword: str):
        """3 templates statiques si LLM indisponible."""
        kw = keyword.lower()
        return [
            {
                "title":             f"Outil CLI pour {kw}",
                "description":       f"Un outil en ligne de commande interactif pour automatiser les taches liees a {kw}.",
                "domain":            kw,
                "tech_stack":        ["Python", "Click", "SQLite", "Rich"],
                "difficulty":        "debutant",
                "estimated_sprints": 5,
                "tags":              ["cli", "automatisation", kw],
                "quality_score":     0.70,
            },
            {
                "title":             f"Dashboard de suivi {kw}",
                "description":       f"Interface web pour visualiser et piloter les metriques associees a {kw} en temps reel.",
                "domain":            kw,
                "tech_stack":        ["Python", "FastAPI", "React", "SQLite"],
                "difficulty":        "intermediaire",
                "estimated_sprints": 10,
                "tags":              ["dashboard", "visualisation", kw],
                "quality_score":     0.72,
            },
            {
                "title":             f"Agent conversationnel {kw}",
                "description":       f"Chatbot local specialise dans le domaine {kw}, utilisant Ollama en mode offline.",
                "domain":            kw,
                "tech_stack":        ["Python", "Ollama", "ChromaDB", "FastAPI"],
                "difficulty":        "avance",
                "estimated_sprints": 14,
                "tags":              ["ia", "offline", kw],
                "quality_score":     0.75,
            },
        ]

    def _tool_project_compact_history(self, args: Dict) -> Dict:
        """
        Compaction de l'historique sliding-window (PROJ-09).

        Conserve les `keep` dernieres entrees de history.jsonl.
        Archive les entrees excedentaires dans history_archive/.
        Ecriture atomique T-14.
        """
        project_id = str(args.get("project_id", "")).strip()
        if not project_id:
            ctx = self._active_ctx()
            if ctx is None:
                return {
                    "compacted": False,
                    "reason":    "Aucun projet ouvert et project_id absent",
                }
            project_id = ctx.meta.id

        pm   = self._get_project_manager()
        meta = pm.get_project(project_id)
        if meta is None:
            return {"compacted": False, "reason": f"Projet introuvable : {project_id}"}

        keep = int(args.get("keep", 200))

        from core.project_manager import _LCCA_ROOT
        from core.project_history_compactor import ProjectHistoryCompactor
        project_dir = _LCCA_ROOT / "projects" / meta.slug

        compactor = ProjectHistoryCompactor()
        result    = compactor.compact(project_dir, keep=keep)

        log.info(
            "MCP project_compact_history : slug=%s compacted=%s kept=%d archived=%d",
            meta.slug, result.compacted, result.entries_kept, result.entries_archived,
        )

        d = result.to_dict()
        d["project_id"] = meta.id
        d["slug"]       = meta.slug
        return d
