// router.ts — Routing heuristique intent → MCP tool (Sprint UI-04 / REFACTO-UI-01)
// Responsabilités : routeIntent(), inferDomain(), extractCode()
// Les patterns NL sont dans intentPatterns.ts (source de vérité unique).

import { PATTERNS } from './intentPatterns';

export type RoutedIntent =
  | { tool: 'llm_chat';        args: { message: string; system?: string; history?: { role: 'user' | 'assistant'; content: string }[] } }
  | { tool: 'web_search';      args: { query: string; max_results?: number } }
  | { tool: 'generate_spec';   args: { intent: string; domain: string } }
  | { tool: 'validate_spec';   args: { body_md?: string; spec_id?: string } }
  | { tool: 'memory_search';   args: { query: string; n: number } }
  | { tool: 'project_search';  args: { query: string } }
  | { tool: 'sandbox_run';     args: { code: string } }
  | { tool: 'evaluate_quality'; args: { code: string } }
  | { tool: 'analyze_error';   args: { error_text: string; file?: string } }
  | { tool: 'edit_batch';      args: { files: unknown[] } };

// ─── Inférence de domaine ─────────────────────────────────────────────────────
export function inferDomain(text: string): string {
  const t = text.toLowerCase();
  if (/transaction|rollback|wal|acid|commit/.test(t))       return 'transaction';
  if (/ast|libcst|parse|tree|node/.test(t))                 return 'ast';
  if (/mcp|json-rpc|tool|server|ipc/.test(t))               return 'mcp';
  if (/sandbox|docker|subprocess|exec|run/.test(t))         return 'sandbox';
  if (/memory|chromadb|vector|embed|search/.test(t))        return 'memory';
  if (/spec|validator|rule|validation/.test(t))             return 'spec';
  if (/orchestrat|pipeline|intent|workflow/.test(t))        return 'orchestration';
  return 'global';
}

// ─── Extraction de bloc code ──────────────────────────────────────────────────
export function extractCode(text: string): string {
  const m = text.match(/```(?:python|py)?\n?([\s\S]+?)```/);
  if (m) return m[1].trim();
  return text.replace(/^(run:|exec:|@eval\s+)/i, '').trim();
}

// ─── Fonction principale ──────────────────────────────────────────────────────
export function routeIntent(text: string): RoutedIntent {
  const trimmed = text.trim();
  for (const p of PATTERNS) {
    if (p.test(trimmed)) return p.route(trimmed);
  }
  return { tool: 'memory_search', args: { query: trimmed, n: 5 } };
}
