// telemetryStore.ts — V9-09
// Store dédié à la télémétrie tok/s.
// Découplé de contextStore pour respecter SRP.
// Polling toutes les 10s (cohérent avec contextStore.tpsData).

import { create } from 'zustand';

export interface TpsPoint {
  ts:    number;        // timestamp unix ms
  value: number;        // tok/s
  model: string | null;
}

export interface TpsAggregate {
  avg:   number | null;
  last:  number | null;
  model: string | null;
  count: number;
}

interface TelemetryState {
  // Historique complet (N derniers points pour le graphe)
  history:    TpsPoint[];
  // Agrégat résumé (badge TitleBar)
  aggregate:  TpsAggregate | null;
  // Statut du store
  loading:    boolean;
  lastRefresh: number | null; // timestamp ms

  // Actions
  setHistory:    (h: TpsPoint[]) => void;
  setAggregate:  (a: TpsAggregate | null) => void;

  // Polling
  startPolling: () => () => void;
  refresh:      () => Promise<void>;
}

function getLcca() {
  return (window as any).lcca ?? null;
}

export const useTelemetryStore = create<TelemetryState>()((set, get) => ({
  history:     [],
  aggregate:   null,
  loading:     false,
  lastRefresh: null,

  setHistory:   (h) => set({ history: h }),
  setAggregate: (a) => set({ aggregate: a }),

  refresh: async () => {
    const lcca = getLcca();
    if (!lcca?.readTelemetryHistory) return;

    set({ loading: true });
    try {
      // Historique graphe (100 points)
      const hist = await lcca.readTelemetryHistory(100) as {
        points: TpsPoint[];
        model: string | null;
      };
      set({ history: hist.points ?? [], lastRefresh: Date.now() });

      // Agrégat badge (20 derniers points)
      const agg = await lcca.readTps?.(20) as TpsAggregate | null;
      if (agg) set({ aggregate: agg });
    } catch {
      // Silencieux — telemetry.jsonl peut ne pas encore exister
    } finally {
      set({ loading: false });
    }
  },

  startPolling: () => {
    // Chargement initial immédiat
    get().refresh();

    // Polling toutes les 10s
    const id = setInterval(() => { get().refresh(); }, 10_000);
    return () => clearInterval(id);
  },
}));
