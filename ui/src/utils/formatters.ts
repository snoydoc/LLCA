// formatters.ts — utilitaires d'affichage (Sprint UI-03)

export function formatRelativeTime(isoDate: string): string {
  const diff = Date.now() - new Date(isoDate).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60)    return `${s}s`;
  if (s < 3600)  return `${Math.floor(s / 60)}min`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  const days = Math.floor(s / 86400);
  if (days === 1) return 'hier';
  if (days < 7)  return `il y a ${days}j`;
  return new Date(isoDate).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
}

export function formatTxId(txId: string): string {
  // "tx_a3b4c5d6e7f8" → "a3b4c5d6"
  return txId.replace(/^tx_/, '').slice(0, 8);
}

export function formatScore(score: number): string {
  return score.toFixed(2);
}

export function scoreColor(score: number): string {
  if (score >= 0.8) return 'var(--success)';
  if (score >= 0.5) return 'var(--warning)';
  return 'var(--error)';
}
