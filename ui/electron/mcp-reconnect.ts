// mcp-reconnect.ts — Logique de reconnexion automatique McpBridge (REFACTO-UI-01)
// Responsabilité unique : stratégie retry après crash du process MCP Python.

export interface ReconnectOptions {
  retryDelays: readonly number[];
  onRestart:   () => Promise<void>;
  onGiveUp:    () => void;
}

export class McpReconnect {
  private retryCount = 0;
  private stopped    = false;

  constructor(private readonly opts: ReconnectOptions) {}

  /** Réinitialise le compteur (appelé après une connexion réussie). */
  reset(): void {
    this.retryCount = 0;
  }

  /** Signal d'arrêt définitif — plus de tentatives. */
  stop(): void {
    this.stopped = true;
  }

  /**
   * Appelé quand le process MCP se ferme.
   * Planifie une reconnexion si la politique le permet.
   */
  onCrash(
    exitCode: number | null,
    clearPending: (err: Error) => void,
  ): void {
    clearPending(new Error('McpBridge: serveur fermé'));

    if (this.stopped) return;

    if (this.retryCount < this.opts.retryDelays.length) {
      const delay = this.opts.retryDelays[this.retryCount++];
      console.error(
        `[McpReconnect] crash (exit ${exitCode}), reconnexion dans ${delay}ms…`
      );
      setTimeout(() => {
        this.opts.onRestart().catch((err) => {
          console.error('[McpReconnect] reconnexion échouée:', err);
        });
      }, delay);
    } else {
      console.error('[McpReconnect] trop de tentatives, abandon.');
      this.opts.onGiveUp();
    }
  }
}
