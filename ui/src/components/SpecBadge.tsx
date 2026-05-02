// SpecBadge.tsx — UI-DS-03 : score pill avec classes sémantiques (pas de style inline)
// Les couleurs ok/warn/err viennent de --success / --warning / --error de themes.css
import { FileText, ExternalLink, Download } from 'lucide-react';
import type { SpecBadge as SpecBadgeType } from '../types/chat';

interface Props {
  badge:    SpecBadgeType;
  onView:   () => void;
  onExport: () => void;
}

/** Détermine la classe de couleur du score pill (> 0.8 = ok, > 0.5 = warn, < 0.5 = err) */
function scorePillClass(score: number): string {
  if (score >= 0.8) return 'score-pill score-pill--ok';
  if (score >= 0.5) return 'score-pill score-pill--warn';
  return 'score-pill score-pill--err';
}

export function SpecBadge({ badge, onView, onExport }: Props) {
  return (
    <div className="spec-badge">
      <FileText size={14} className="spec-badge-icon" aria-hidden="true" />
      <div className="spec-badge-info">
        <span className="spec-badge-title">📋 {badge.title}</span>
        <span className="spec-badge-meta">
          {badge.domain}
          {' · '}
          <span className={scorePillClass(badge.score)}>
            {badge.score.toFixed(2)}
          </span>
          {badge.validated && (
            <span className="spec-badge-validated" aria-label="Spec validée">
              {' · '}✅
            </span>
          )}
          {badge.autoStored && (
            <span
              className="spec-badge-stored"
              title="Mémorisée automatiquement dans lcca_specs (CTX-04)"
              aria-label="Spec mémorisée"
            >
              {' '}💾
            </span>
          )}
        </span>
      </div>
      <div className="spec-badge-actions">
        <button onClick={onView}   aria-label="Voir la spec">
          <ExternalLink size={12} /> Voir
        </button>
        <button onClick={onExport} aria-label="Exporter en Markdown">
          <Download size={12} /> .md
        </button>
      </div>
    </div>
  );
}
