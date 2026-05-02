# -*- coding: utf-8-sig -*-
"""
mcp_types.py — Constantes JSON-RPC 2.0 pour le serveur MCP LCCA (Sprint REFACTO-01).

Zéro logique, zéro import — peut être importé sans effets de bord.
Séparé de mcp_server.py pour éviter les imports circulaires et faciliter les tests.
"""
from __future__ import annotations

_JSONRPC              = "2.0"
_ERR_PARSE            = -32700
_ERR_INVALID_REQ      = -32600
_ERR_METHOD_NOT_FOUND = -32601
_ERR_INVALID_PARAMS   = -32602
_ERR_INTERNAL         = -32603
_ERR_SECURITY         = -32001
_ERR_TOOL_FAILED      = -32002
