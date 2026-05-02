import { useContextStore } from '../stores/contextStore';

export function McpStatusBar() {
  const { mcpStatus } = useContextStore();

  const label = {
    connected:    '● Connecté',
    connecting:   '◌ Connexion…',
    disconnected: '○ Déconnecté',
    error:        '✕ Erreur serveur',
  }[mcpStatus];

  const handleRestart = async () => {
    try {
      await (window as any).lcca.restartServer();
    } catch (err) {
      console.error('Restart failed:', err);
    }
  };

  return (
    <div className="mcp-status-bar">
      <span
        className={`status-dot status-${mcpStatus}`}
        aria-hidden="true"
      />
      <span style={{ fontSize: 'var(--font-size-xs)' }}>{label}</span>
      <button
        className="mcp-restart-btn"
        onClick={handleRestart}
        title="Relancer McpServer"
        aria-label="Relancer le serveur MCP"
      >
        ⟳ Relancer
      </button>
    </div>
  );
}
