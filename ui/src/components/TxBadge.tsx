import { useState, useEffect } from 'react';
import { CheckCircle, RotateCcw, AlertTriangle } from 'lucide-react';
import type { TxBadge as TxBadgeType } from '../types/chat';

interface Props {
  badge:       TxBadgeType;
  onRollback?: (txId: string) => Promise<void>;
}

export function TxBadge({ badge, onRollback }: Props) {
  const [showRollback, setShowRollback] = useState(badge.status === 'committed');
  const [confirming,   setConfirming]   = useState(false);
  const [rolling,      setRolling]      = useState(false);

  // Masquer le bouton rollback après 30s
  useEffect(() => {
    if (badge.status !== 'committed') return;
    const t = setTimeout(() => setShowRollback(false), 30_000);
    return () => clearTimeout(t);
  }, [badge.status]);

  const statusIcon =
    badge.status === 'committed'   ? <CheckCircle  size={13} /> :
    badge.status === 'rolled_back' ? <RotateCcw    size={13} /> :
                                     <AlertTriangle size={13} />;

  const statusColor =
    badge.status === 'committed'   ? 'var(--success)' :
    badge.status === 'rolled_back' ? 'var(--warning)' :
                                     'var(--error)';

  const filesDisplay =
    badge.files.slice(0, 2).join(', ') +
    (badge.files.length > 2 ? ` +${badge.files.length - 2}` : '');

  const handleRollback = async () => {
    if (!confirming) { setConfirming(true); return; }
    setRolling(true);
    try {
      await onRollback?.(badge.txId);
    } finally {
      setRolling(false);
      setConfirming(false);
      setShowRollback(false);
    }
  };

  return (
    <div className="tx-badge" style={{ borderColor: statusColor }}>
      <span className="tx-badge-icon" style={{ color: statusColor }}>{statusIcon}</span>
      <span className="tx-badge-id">{badge.txId.slice(0, 12)}</span>
      {filesDisplay && <span className="tx-badge-files">{filesDisplay}</span>}
      {showRollback && onRollback && (
        <button
          className="tx-badge-rollback"
          onClick={handleRollback}
          disabled={rolling}
          aria-label={confirming ? 'Confirmer le rollback' : 'Annuler la transaction'}
        >
          {rolling ? '…' : confirming ? 'Confirmer ↩' : '↩ Annuler'}
        </button>
      )}
    </div>
  );
}
