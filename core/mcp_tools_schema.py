# -*- coding: utf-8-sig -*-
"""
mcp_tools_schema.py — Définitions JSON des 11 tools MCP LCCA (Sprint REFACTO-01).

Contient uniquement _TOOLS : List[Dict[str, Any]].
Zéro logique, importe uniquement SANDBOX_TIMEOUT depuis config.

Séparé de mcp_server.py pour réduire sa taille de 35.9 KB à < 12 KB.
Importé par mcp_server.py : from core.mcp_tools_schema import _TOOLS
"""
from __future__ import annotations

from typing import Any, Dict, List

try:
    from config import SANDBOX_TIMEOUT as _SANDBOX_TIMEOUT
except ImportError:
    _SANDBOX_TIMEOUT = 30


_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "memory_search",
        "description": (
            "Recherche sémantique dans la mémoire LCCA (5 collections : solutions, "
            "failures, context, patches, specs). Utiliser avant toute génération de code "
            "pour récupérer le contexte pertinent."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "n":     {"type": "integer", "default": 5},
                "wing":  {"type": "string",  "default": "lcca"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_store",
        "description": (
            "Stocke une entrée dans une collection LCCA. "
            "Collections : lcca_solutions, lcca_failures, lcca_context, lcca_patches, lcca_specs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "collection": {
                    "type": "string",
                    "enum": ["lcca_solutions", "lcca_failures", "lcca_context", "lcca_patches", "lcca_specs"],
                },
                "payload": {"type": "object"},
            },
            "required": ["collection", "payload"],
        },
    },
    {
        "name": "project_search",
        "description": "Recherche des symboles Python et fichiers dans le workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":     {"type": "string"},
                "file_path": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "edit_batch",
        "description": (
            "Applique un batch de modifications atomiques sur des fichiers Python "
            "(max 3 fichiers). patch_type: 'add_function' | 'modify_function' | 'add_import' | 'create'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path":       {"type": "string"},
                            "patch_type": {"type": "string"},
                            "code":       {"type": "string"},
                            "symbol":     {"type": "string"},
                            "action":     {"type": "string"},
                        },
                        "required": ["path"],
                    },
                },
            },
            "required": ["files"],
        },
    },
    {
        "name": "sandbox_run",
        "description": "Exécute du code Python en isolation (subprocess ou Docker).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code":    {"type": "string"},
                "timeout": {"type": "integer", "default": _SANDBOX_TIMEOUT},
            },
            "required": ["code"],
        },
    },
    {
        "name": "evaluate_quality",
        "description": "Évalue la qualité statique d'un code Python (score 0-100).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code":     {"type": "string"},
                "filename": {"type": "string", "default": "<generated>"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "analyze_error",
        "description": "Analyse une exception Python et retourne un diagnostic actionnable.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "error_type":    {"type": "string"},
                "error_message": {"type": "string"},
                "file_path":     {"type": "string"},
                "source":        {"type": "string"},
            },
            "required": ["error_type", "error_message", "file_path"],
        },
    },
    {
        "name": "generate_spec",
        "description": (
            "Génère une specification technique à partir d'un intent flou. "
            "Retourne spec_id, domain, version, title, abstract, complexity_score, validated, score, auto_stored. "
            "Si validée, la spec est automatiquement stockée dans lcca_specs (CTX-04)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "intent":  {"type": "string", "description": "Description de la tâche"},
                "domain":  {"type": "string", "description": "Domaine technique (ex: sandbox, mcp, ast)"},
                "context": {"type": "string", "description": "Contexte supplémentaire (optionnel)", "default": ""},
            },
            "required": ["intent", "domain"],
        },
    },
    {
        "name": "validate_spec",
        "description": (
            "Valide une spec existante (par spec_id ou body_md) contre les 15 règles V7.2. "
            "Retourne valid, score, violations."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "spec_id": {"type": "string", "description": "ID de la spec à valider (12 chars hex)"},
                "body_md": {"type": "string", "description": "Corps Markdown de la spec (si pas de spec_id)"},
                "rules":   {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Liste de règles à appliquer (défaut : toutes)",
                },
            },
        },
    },
    {
        "name": "web_search",
        "description": (
            "Effectue une recherche sur internet via DuckDuckGo, récupère les pages "
            "les plus pertinentes et synthétise une réponse via le LLM local. "
            "Utiliser pour : actualités, comparaisons de produits/services, informations "
            "récentes, documentation en ligne, recherche de projets existants."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Requête de recherche en langage naturel",
                },
                "max_results": {
                    "type": "integer",
                    "default": 5,
                    "description": "Nombre maximum de résultats DDG (défaut: 5)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_cache_stats",
        "description": (
            "Retourne les statistiques du cache de recherche web (nombre d'entrées, "
            "taille disque, chemin). Permet aussi d'invalider une entrée spécifique "
            "ou de vider toutes les entrées expirées."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["stats", "clear_expired", "invalidate"],
                    "default": "stats",
                    "description": "Action : stats (défaut), clear_expired ou invalidate",
                },
                "query": {
                    "type": "string",
                    "default": "",
                    "description": "Requête à invalider (requis si action=invalidate)",
                },
            },
        },
    },
    {
        "name": "educator_status",
        "description": (
            "Retourne le statut de la derniere curation EducatorAgent "
            "(repos traites, skills ingeres, erreurs). "
            "Retourne 'idle' si aucune curation n'a encore ete lancee."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    # ── Mode Projets (PROJ-04) ─────────────────────────────────────────────
    {
        "name": "project_list",
        "description": "Liste les projets LCCA V10 (actifs par defaut, + archived si include_archived=true).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_archived": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "project_create",
        "description": "Cree un nouveau projet LCCA V10 avec sa structure de dossiers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name":         {"type": "string", "description": "Nom du projet"},
                "description":  {"type": "string", "default": ""},
                "storage_mode": {"type": "string", "enum": ["shared", "isolated"], "default": "shared"},
                "tags":         {"type": "array", "items": {"type": "string"}, "default": []},
            },
            "required": ["name"],
        },
    },
    {
        "name": "project_open",
        "description": "Ouvre un projet (charge le contexte, acquiert le lock). Un seul projet ouvert a la fois.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID ou slug du projet"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "project_close",
        "description": "Ferme le projet actif : sauvegarde le checkpoint et libere le lock.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "project_archive",
        "description": "Archive un projet (status active -> archived). Le projet n'apparait plus dans project_list.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "project_switch",
        "description": "Ferme le projet courant (si ouvert) puis ouvre un autre projet en une seule operation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID ou slug du projet cible"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "project_get_context",
        "description": "Retourne le contexte du projet actif (meta, skills, specs, history_entries).",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "project_save_context",
        "description": "Force un checkpoint du projet actif (ecrit context_snapshot.json) sans le fermer.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "project_healthcheck",
        "description": "Verifie l'etat d'un projet : fichiers requis, dossiers, meta valide. project_id optionnel (utilise l'actif si absent).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "default": ""},
            },
        },
    },
    {
        "name": "project_compact_history",
        "description": "Compaction L0->L1 de l'historique (stub PROJ-09 — retourne stats sans modifier les donnees).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "default": ""},
            },
        },
    },
    # ────────────────────────────────────────────────────────────────────────
    {
        "name": "llm_chat",
        "description": (
            "Envoie un message en langage naturel au LLM local (Ollama qwen2.5-coder:7b). "
            "Utilisé pour les questions générales, l'analyse, les explications et "
            "tout intent qui n'est pas un outil MCP spécifique. "
            "Retourne une réponse textuelle libre du modèle."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Message de l'utilisateur en langage naturel",
                },
                "system": {
                    "type": "string",
                    "description": "Prompt système optionnel (défaut : assistant LCCA V7.2)",
                    "default": "",
                },
            },
            "required": ["message"],
        },
    },
    # PROJ-UI-02 — inspiration_generate
    {
        "name": "inspiration_generate",
        "description": (
            "Genere 3 idees de projets logiciels via le LLM local (qwen2.5-coder:3b). "
            "Retourne un tableau d'IdeaCard : title, description, domain, tech_stack, "
            "difficulty, estimated_sprints, tags, quality_score. "
            "Fallback templates statiques si Ollama indisponible."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Theme ou domaine (ex: 'agent medical', 'outil CLI')",
                },
                "online": {
                    "type": "boolean",
                    "description": "Tenter un modele online (non supporte en V1, ignore)",
                    "default": False,
                },
            },
            "required": ["keyword"],
        },
    },
]
