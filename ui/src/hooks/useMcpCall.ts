// useMcpCall.ts — Hook appel MCP avec timeout (REFACTO-UI-01)
// Source de vérité unique pour les timeouts côté renderer.
// Les mêmes valeurs sont définies dans ui/electron/mcp-timeouts.ts (main process).
// Règle REFACTO-UI-01 : centraliser dans mcp-timeouts.ts et importer des deux côtés
// n'est pas possible car le main process (Node) et le renderer (browser) ont des
// contextes séparés — on duplique volontairement les valeurs ici avec un commentaire
// de synchronisation explicite.

import { McpError } from '../types/mcp';

// ── Timeouts (ms) — synchronisés avec ui/electron/mcp-timeouts.ts ─────────────
// ⚠ Si vous modifiez ces valeurs, mettez à jour mcp-timeouts.ts également.
export const CALL_TIMEOUT_MS: Record<string, number> = {
  llm_chat:      360_000,
  web_search:    240_000,
  generate_spec: 420_000,
  validate_spec: 120_000,
};
export const CALL_TIMEOUT_DEFAULT_MS = 60_000;

/** Signal d'annulation partageable entre le hook et le handler d'envoi. */
export interface CancelSignal { cancelled: boolean }

/**
 * Effectue un appel MCP avec timeout adaptatif.
 * Lance McpError si MCP non connecté, timeout dépassé, ou réponse vide/invalide.
 */
export async function callWithTimeout(
  tool: string,
  args: Record<string, unknown>,
  signal: CancelSignal,
): Promise<unknown> {
  const lcca = (window as any).lcca;
  if (!lcca?.mcpCall) throw new McpError(-32000, 'McpServer non connecté');

  const timeoutMs = CALL_TIMEOUT_MS[tool] ?? CALL_TIMEOUT_DEFAULT_MS;

  const timeoutPromise = new Promise<never>((_, reject) =>
    setTimeout(() => reject(new McpError(-32001, 'TIMEOUT')), timeoutMs)
  );

  const callPromise = (async () => {
    const raw = await lcca.mcpCall(tool, args);
    if (signal.cancelled) throw new McpError(-32000, 'Annulé');
    if (raw?.error) throw new McpError(raw.error.code ?? -32000, raw.error.message ?? 'Erreur MCP');
    const text = raw?.content?.[0]?.text;
    if (!text) throw new Error(`Réponse MCP vide (outil: ${tool}) — raw: ${JSON.stringify(raw)}`);
    try {
      return JSON.parse(text);
    } catch {
      throw new Error(`JSON.parse échoué (outil: ${tool}) — texte reçu: ${text.slice(0, 200)}`);
    }
  })();

  return Promise.race([callPromise, timeoutPromise]);
}
