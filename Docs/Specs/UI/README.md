# Specs UI — LCCA Desktop Interface
<!-- AI-READY | Index specs UI | Version 1.0.0 | 2026-04-18 -->

## Fichiers

| Fichier | Contenu |
|---------|---------|
| `spec-ui-01-vision.md` | Vision produit, UX goals, principes de design |
| `spec-ui-02-architecture.md` | Architecture technique, stack, modules, intégration MCP |
| `spec-ui-03-composants.md` | Composants détaillés, comportements, états, API internes |

## Roadmap sprints UI

| Sprint UI | Contenu | Dépendances LCCA |
|-----------|---------|------------------|
| UI-01 | Shell Electron + layout 3 panneaux + chat basique | McpServer V7.2 |
| UI-02 | Historique sessions + formatage Markdown + code highlighting | — |
| UI-03 | Panneau contexte (fichiers/specs/mémoire) | SpecEntry, MemoryEngine |
| UI-04 | Terminal intégré + streaming réponses | SandboxEngine |
| UI-05 | Settings + thèmes + raccourcis clavier | config.py |

## Contraintes globales

- **100% offline** — aucune dépendance cloud (comme tout LCCA)
- **Stack** : Electron + React + TypeScript (CSS Variables pour thèmes)
- **Communication** : IPC Electron vers McpServer stdio (JSON-RPC 2.0)
- **OS cible** : Windows 11 (D:\LLMCodeAgent), compatible macOS/Linux
- **Performance** : démarrage < 3s, réponse UI < 50ms (hors LLM)
