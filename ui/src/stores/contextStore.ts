import { create } from 'zustand';
import type { McpStatusValue } from '../types/mcp';
import type { SpecSummary, TxRecord } from '../types/chat';
import { useChatStore } from './chatStore'; // BUGFIX : accès aux badges enrichis des messages

// UI-08 : données Educator issues de educator_status MCP
export interface EducatorData {
  status      : 'idle' | 'ok' | 'not_configured';
  dry_run     : boolean;
  repos       : number;
  skills      : number;
  errors      : number;
  lastPoll    : number; // timestamp ms
}

interface ContextState {
  mcpStatus:      McpStatusValue;
  llmStatus:      'available' | 'unavailable' | 'unknown';
  tpsData:        { avg: number | null; last: number | null; model: string | null; count: number } | null; // V9-06
  educatorData:   EducatorData | null; // UI-08
  workspaceFiles: string[];
  activeSpecs:    SpecSummary[];
  selectedSpec:   (SpecSummary & { violations?: unknown[] }) | null;
  recentTx:       TxRecord[];
  modifiedFiles:  string[];
  selectedFile:   string | null;

  setMcpStatus:     (s: McpStatusValue) => void;
  setLlmStatus:     (s: ContextState['llmStatus']) => void;
  setTpsData:       (d: ContextState['tpsData']) => void; // V9-06
  setEducatorData:  (d: EducatorData | null) => void; // UI-08
  setModifiedFiles: (files: string[]) => void;
  setSelectedFile:   (path: string | null) => void;
  addTxRecord:       (tx: TxRecord) => void;

  refreshWorkspace:    () => Promise<void>;
  refreshSpecs:        () => Promise<void>;
  selectSpec:          (specId: string) => Promise<void>;
  refreshTransactions: () => void;
  startPolling:        () => () => void;
}

function getLcca() {
  return (window as any).lcca ?? null;
}

async function mcpCall(tool: string, args: Record<string, unknown>): Promise<any> {
  const lcca = getLcca();
  if (!lcca?.mcpCall) throw new Error('window.lcca non disponible');
  return lcca.mcpCall(tool, args);
}

export const useContextStore = create<ContextState>()((set, _get) => ({
  mcpStatus:      'disconnected',
  llmStatus:      'unknown',
  tpsData:        null, // V9-06
  educatorData:   null, // UI-08
  workspaceFiles: [],
  activeSpecs:    [],
  selectedSpec:   null,
  recentTx:       [],
  modifiedFiles:  [],
  selectedFile:   null,

  setMcpStatus:     (s) => set({ mcpStatus: s }),
  setLlmStatus:     (s) => set({ llmStatus: s }),
  setTpsData:       (d) => set({ tpsData: d }), // V9-06
  setEducatorData:  (d) => set({ educatorData: d }), // UI-08
  setModifiedFiles: (files) => {
    set({ modifiedFiles: files });
    setTimeout(() => set({ modifiedFiles: [] }), 5 * 60 * 1000);
  },
  setSelectedFile: (path) => set({ selectedFile: path }),
  addTxRecord: (tx) => set(s => ({ recentTx: [tx, ...s.recentTx].slice(0, 10) })),

  refreshWorkspace: async () => {
    try {
      // FIX: query vide rejeté par project_search — utiliser '*' comme wildcard
      const raw = await mcpCall('project_search', { query: '*' });
      const result = JSON.parse(raw?.content?.[0]?.text ?? '{}');
      set({ workspaceFiles: result.files ?? [] });
    } catch { /* silencieux */ }
  },

  refreshSpecs: async () => {
    try {
      const raw = await mcpCall('memory_search', { query: 'spec', n: 10 });
      const result = JSON.parse(raw?.content?.[0]?.text ?? '{}');
      // FIX: la réponse memory_search est {lcca_solutions:[...], lcca_context:[...], ...}
      // pas {specs:[...]}. On aplatit toutes les collections.
      const allEntries: any[] = Object.values(result).flat();
      const entries: SpecSummary[] = allEntries
        .filter((e: any) => e?.metadata?.spec_id)
        .map((e: any) => ({
          specId:    e.metadata.spec_id ?? '',
          title:     (e.metadata?.title as string) ?? 'Sans titre',
          domain:    (e.metadata?.domain as string) ?? 'global',
          validated: Boolean(e.metadata?.validated),
          score:     Number(e.metadata?.score ?? 0),
          createdAt: (e.metadata?.created_at as string) ?? new Date().toISOString(),
        }));
      set({ activeSpecs: entries });
    } catch { /* silencieux */ }
  },

  selectSpec: async (specId) => {
    // BUGFIX : chercher d'abord le body_md dans les messages du chatStore
    // (le badge est enrichi au moment de generate_spec avec le corps complet)
    const chatMessages = useChatStore.getState().messages;
    const cachedBadge  = chatMessages
      .map(m => m.specBadge)
      .find(b => b?.specId === specId);

    if (cachedBadge?.body_md) {
      // body_md disponible en mémoire — pas besoin d'appel MCP
      set({
        selectedSpec: {
          specId,
          title:      cachedBadge.title,
          domain:     cachedBadge.domain,
          validated:  cachedBadge.validated,
          score:      cachedBadge.score,
          createdAt:  new Date().toISOString(),
          body_md:    cachedBadge.body_md,
          violations: (cachedBadge.violations as any[]) ?? [],
          version:    cachedBadge.version,
        },
      });
      return;
    }

    // Fallback : appel validate_spec si body_md absent du cache
    try {
      const raw = await mcpCall('validate_spec', { spec_id: specId });
      const result = JSON.parse(raw?.content?.[0]?.text ?? '{}');
      set({
        selectedSpec: {
          specId,
          title:      result.title ?? specId,
          domain:     result.domain ?? 'global',
          validated:  result.valid ?? false,
          score:      result.score ?? 0,
          createdAt:  new Date().toISOString(),
          body_md:    result.body_md ?? '',
          violations: result.violations ?? [],
          version:    result.version,
        },
      });
    } catch { /* silencieux */ }
  },

  refreshTransactions: () => {},

  startPolling: () => {
    // Polling MCP status (3s)
    const idMcp = setInterval(async () => {
      try {
        const lcca = getLcca();
        if (!lcca?.mcpStatus) return;
        const s = await lcca.mcpStatus() as { status: McpStatusValue };
        set({ mcpStatus: s.status ?? 'disconnected' });
      } catch {
        set({ mcpStatus: 'error' });
      }
    }, 3000);

    // Polling tpsData (10s) — V9-06
    const idTps = setInterval(async () => {
      try {
        const lcca = getLcca();
        if (!lcca?.readTps) return;
        const d = await lcca.readTps(20) as { avg: number | null; last: number | null; model: string | null; count: number };
        set({ tpsData: d });
      } catch { /* silencieux */ }
    }, 10_000);

    // Polling educatorData (30s) — UI-08
    const idEdu = setInterval(async () => {
      try {
        const raw = await mcpCall('educator_status', {});
        const r = JSON.parse(raw?.content?.[0]?.text ?? '{}');
        if (r.status) {
          set({
            educatorData: {
              status  : r.status,
              dry_run : Boolean(r.dry_run),
              repos   : Number(r.repos_processed ?? 0),
              skills  : Number(r.skills_ingested ?? 0),
              errors  : Array.isArray(r.errors) ? r.errors.length : 0,
              lastPoll: Date.now(),
            },
          });
        }
      } catch { /* silencieux : MCP pas encore connecté */ }
    }, 30_000);

    return () => {
      clearInterval(idMcp);
      clearInterval(idTps);
      clearInterval(idEdu);
    };
  },
}));
