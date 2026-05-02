// DisconnectedBanner.tsx — Banner d'erreur connexion MCP (REFACTO-UI-01)
interface DisconnectedBannerProps {
  onRetry: () => void;
}

export function DisconnectedBanner({ onRetry }: DisconnectedBannerProps) {
  return (
    <div className="error-banner" role="alert">
      <span aria-hidden="true">⚠</span>
      <span style={{ flex: 1 }}>
        McpServer non connecté — vérifiez que le venv Python est actif.
      </span>
      <button className="error-banner-btn" onClick={onRetry}>Réessayer</button>
    </div>
  );
}
