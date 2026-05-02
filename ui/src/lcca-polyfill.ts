/**
 * lcca-polyfill.ts
 * Injecté dans main.tsx AVANT App.
 * Si window.lcca n'existe pas (mode browser sans Electron),
 * on crée un stub minimal pour que l'UI soit utilisable.
 */

const STUB_RESPONSES: Record<string, unknown> = {
  memory_search: {
    solutions: [],
    failures:  [],
    context:   [],
    specs:     [],
  },
  generate_spec: {
    spec_id: 'stub_000000',
    title: 'Stub spec (mode browser)',
    domain: 'global',
    version: '7.2.0',
    score: 0,
    validated: false,
    complexity_score: 0,
    violations: [{ rule: 'stub', severity: 'warning', fix_suggestion: 'Lancer Electron pour un vrai MCP' }],
  },
  project_search: { files: [], symbols: [] },
  sandbox_run:    { success: false, exit_code: -1, stdout: '', stderr: 'Mode browser — sandbox indisponible' },
  evaluate_quality: { total_score: 0 },
};

function makeStubLcca() {
  return {
    mcpCall: async (tool: string, _args: object) => {
      console.warn(`[lcca-stub] mcpCall("${tool}") — mode browser sans Electron`);
      await new Promise(r => setTimeout(r, 300)); // simuler latence
      const data = STUB_RESPONSES[tool] ?? {};
      return { content: [{ type: 'text', text: JSON.stringify(data) }] };
    },
    mcpStatus:           async () => ({ status: 'disconnected' }),
    restartServer:       async () => ({ status: 'disconnected' }),
    stopServer:          async () => {},
    onServerStatus:      (_cb: unknown) => () => {},
    readWorkspaceFile:   async (_p: string) => '',
    saveSessions:        async (_s: unknown) => {},
    loadSessions:        async () => ({ sessions: [] }),
    saveSessionMessages: async (_id: string, _m: unknown) => {},
    loadSessionMessages: async (_id: string) => ({ messages: [] }),
    saveSettings:        async (_s: unknown) => {},
    loadSettings:        async () => null,
    detectPython:        async () => null,
    browseDirectory:     async () => null,
    windowControl:       (_action: string) => {},
  };
}

// Injection uniquement si window.lcca absent (= pas dans Electron)
if (!(window as any).lcca) {
  (window as any).lcca = makeStubLcca();
  console.info('[lcca-polyfill] window.lcca stubé — mode browser. Lancez via Electron pour le vrai MCP.');
}
