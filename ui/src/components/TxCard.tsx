// TxCard.tsx — Carte transaction dans l'historique (Sprint UI-03)
import { formatRelativeTime, formatTxId } from '../utils/formatters';
import type { TxRecord } from '../types/chat';

interface TxCardProps {
  tx: TxRecord;
}

export function TxCard({ tx }: TxCardProps) {
  const statusIcon  = tx.status === 'committed'   ? '✅'
                    : tx.status === 'rolled_back' ? '↩'
                    :                               '⚠';

  const statusLabel = tx.status === 'committed'   ? 'Commité'
                    : tx.status === 'rolled_back' ? 'Annulé'
                    :                               'Partiel';

  const filesDisplay = tx.files.length === 0 ? '—'
    : tx.files.slice(0, 2).map(f => f.split(/[\\/]/).pop()).join(', ')
      + (tx.files.length > 2 ? ` +${tx.files.length - 2}` : '');

  return (
    <div
      className={`tx-card tx-card-${tx.status}`}
      title={`${tx.txId}\n${tx.files.join(', ')}`}
      aria-label={`Transaction ${formatTxId(tx.txId)} — ${statusLabel}`}
    >
      <span className="tx-card-status" aria-hidden="true">{statusIcon}</span>
      <span className="tx-card-id">{formatTxId(tx.txId)}</span>
      <span className="tx-card-file">{filesDisplay}</span>
      <span className="tx-card-time">{formatRelativeTime(tx.timestamp)}</span>
    </div>
  );
}
