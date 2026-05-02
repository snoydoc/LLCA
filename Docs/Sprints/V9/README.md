# LCCA V9 — Index des Sprints
<!-- AI-READY | LCCA V9 Sprints | 2026-04-20 -->

Sprints générés depuis `SPEC_FINAL_V9.md` (fusion Spec Draft + Review Final + Addendum Hardware).

## Ordre d'implémentation recommandé

| Sprint | Fichier | Priorité | Effort | Dépendances |
|--------|---------|----------|--------|-------------|
| V9-00 | `sprint-v9-00-config-hardware.md` | P0 | 0.5j | Aucune |
| V9-01-A | `sprint-v9-01a-keep-alive-quant.md` | P0 | 0.5j | V9-00 |
| V9-01-B | `sprint-v9-01b-trimodel-pool.md` | P0 | 1j | V9-01-A |
| V9-02-A | `sprint-v9-02a-fewshot-skillibrary.md` | P0 | 1j | V9-01-B |
| V9-02-B | `sprint-v9-02b-correction-loop.md` | P0 | 1j | V9-02-A |
| V9-02-CD | `sprint-v9-02cd-ast-json-mode.md` | P1 | 1j | V9-00 |
| V9-03-A | `sprint-v9-03a-repo-rag.md` | P1 | 1j | V9-01-B |
| V9-03-BCD | `sprint-v9-03bcd-web-hyde-doc.md` | P1 | 2j | V9-03-A |
| V9-04-A | `sprint-v9-04a-sft-collector.md` | P2 | 1.5j | V9-02-B |
| V9-04-D | `sprint-v9-04d-prompt-tuner.md` | P2 | 0.5j | V9-04-A |
| V9-05-A | `sprint-v9-05a-qa-agent.md` | P2 | 2j | V9-00 |
| V9-05-B | `sprint-v9-05b-doc-agent.md` | P2 | 1.5j | V9-05-A |
| V9-05-CD | `sprint-v9-05cd-hitl-analytics.md` | P3 | 2j | V9-05-A |
| V9-05-EF | `sprint-v9-05ef-episodic-tts.md` | P4 | 2j | V9-00 |

## Principes LCCA AI Coder (rappel)

- Lire skills 001-005 en début de session
- Max 3 fichiers par transaction
- SmartPatcher retourne str, jamais n'écrit disque
- safe_path() obligatoire avant toute opération disque MCP
- Spec non validée → jamais de code
- 🚨 filesystem:write_file ÉCRASE — lire avant modifier
