// mcp-timeouts.ts — Source de vérité unique pour les timeouts MCP (REFACTO-UI-01)
// Règle : tout tool LLM ou réseau > 60s a sa propre entrée dans TOOL_TIMEOUTS.
// Importé par mcp-bridge.ts (main process) ET par ChatPanel.tsx (renderer).

export const TOOL_TIMEOUTS: Record<string, number> = {
  llm_chat:      360_000,  // chat CPU : OLLAMA_TIMEOUT(300s) + marge(60s)
  web_search:    240_000,  // 3×fetch(30s) + synthèse_ollama(90s) + marge(30s)
  generate_spec: 420_000,  // SPEC_TIMEOUT(360s) + marge(60s) — 7b + prompt ~2500 tokens
  validate_spec: 120_000,  // validation seule, pas de génération LLM
  si_observe:     10_000,  // SI-06 : observe/decide SelfImprove (lecture WAL + règles JSON)
  voice_start:     5_000,   // VOICE-07 : démarrage processus voice_service (spawn + WebSocket ready)
  tts_speak:      30_000,   // VOICE-07 : synthèse TTS (phrase complète, Kokoro CPU ~20s worst case)
};

export const DEFAULT_TIMEOUT_MS = 60_000; // tools rapides (AST, mémoire, sandbox léger)

/** Retourne le timeout (ms) pour un tool donné. */
export function timeoutForTool(toolName: string): number {
  return TOOL_TIMEOUTS[toolName] ?? DEFAULT_TIMEOUT_MS;
}
