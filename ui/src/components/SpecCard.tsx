// SpecCard.tsx — Carte résumé spec clickable (Sprint UI-03)
import { formatRelativeTime, scoreColor } from '../utils/formatters';
import type { SpecSummary } from '../types/chat';

interface SpecCardProps {
  spec:    SpecSummary;
  onClick: () => void;
}

export function SpecCard({ spec, onClick }: SpecCardProps) {
  const title = spec.title.length > 28
    ? spec.title.slice(0, 28) + '…'
    : spec.title;

  return (
    <div
      className="spec-card"
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={e => e.key === 'Enter' && onClick()}
      aria-label={`Spec : ${spec.title}`}
    >
      <div className="spec-card-header">
        <span
          className={`spec-card-status ${spec.validated ? 'valid' : 'invalid'}`}
          aria-label={spec.validated ? 'Validée' : 'Non validée'}
        >
          {spec.validated ? '✅' : '⚠'}
        </span>
        <span className="spec-card-title">{title}</span>
      </div>
      <div className="spec-card-meta">
        <span className="spec-card-domain">{spec.domain}</span>
        <span className="spec-card-score" style={{ color: scoreColor(spec.score) }}>
          {spec.score.toFixed(2)}
        </span>
        <span className="spec-card-date">{formatRelativeTime(spec.createdAt)}</span>
      </div>
    </div>
  );
}
