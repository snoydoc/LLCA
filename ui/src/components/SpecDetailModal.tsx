// SpecDetailModal.tsx — Modal body_md + violations (Sprint UI-03)
import { useEffect, useState, useRef } from 'react';
import { useContextStore } from '../stores/contextStore';
import { MarkdownRenderer } from './MarkdownRenderer';
import { scoreColor } from '../utils/formatters';
import type { SpecBadge } from '../types/chat';

interface SpecDetailModalProps {
  specId:  string;
  badge?:  SpecBadge;   // BUGFIX : badge enrichi passé directement depuis MessageBubble
  onClose: () => void;
}

export function SpecDetailModal({ specId, badge, onClose }: SpecDetailModalProps) {
  const { selectedSpec, selectSpec } = useContextStore();
  const [loading, setLoading] = useState(true);
  const dialogRef = useRef<HTMLDivElement>(null);

  // Charger la spec au montage
  // BUGFIX : si le badge enrichi est passé en prop (body_md disponible), on l'utilise directement
  // sans appel MCP. Sinon fallback sur selectSpec (contextStore + validate_spec).
  useEffect(() => {
    if (badge?.body_md) {
      // Corps disponible immédiatement — pas de chargement nécessaire
      setLoading(false);
      return;
    }
    setLoading(true);
    selectSpec(specId).finally(() => setLoading(false));
  }, [specId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Résoudre les données à afficher : badge prop en priorité, sinon selectedSpec du store
  const displaySpec = badge?.body_md
    ? {
        specId,
        title:      badge.title,
        domain:     badge.domain,
        validated:  badge.validated,
        score:      badge.score,
        createdAt:  new Date().toISOString(),
        body_md:    badge.body_md,
        violations: (badge.violations as any[]) ?? [],
        version:    badge.version,
      }
    : selectedSpec;

  // Focus trap : Tab reste dans la modal
  useEffect(() => {
    const el = dialogRef.current;
    if (!el) return;
    const focusable = el.querySelectorAll<HTMLElement>(
      'button, [href], input, [tabindex]:not([tabindex="-1"])'
    );
    const first = focusable[0];
    const last  = focusable[focusable.length - 1];
    first?.focus();

    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') { onClose(); return; }
      if (e.key !== 'Tab') return;
      if (e.shiftKey) { if (document.activeElement === first) { e.preventDefault(); last?.focus(); } }
      else            { if (document.activeElement === last)  { e.preventDefault(); first?.focus(); } }
    }
    el.addEventListener('keydown', onKey);
    return () => el.removeEventListener('keydown', onKey);
  }, [loading, onClose]);

  const handleExport = () => {
    if (!displaySpec?.body_md) return;
    const blob = new Blob([displaySpec.body_md], { type: 'text/markdown' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url;
    a.download = `spec-${specId}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const violations = (displaySpec?.violations ?? []) as Array<{
    rule?: string; severity?: string; fix_suggestion?: string;
  }>;

  return (
    <div
      className="modal-overlay"
      onClick={e => e.target === e.currentTarget && onClose()}
      aria-modal="true"
    >
      <div
        className="modal-content spec-detail-modal"
        role="dialog"
        aria-label={`Spec ${specId}`}
        ref={dialogRef}
      >
        {/* Header */}
        <div className="modal-header">
          <h2>📋 {loading ? specId : (displaySpec?.title ?? specId)}</h2>
          <button onClick={onClose} aria-label="Fermer" className="modal-close-btn">×</button>
        </div>

        {/* Loading */}
        {loading && (
          <div className="modal-loading" aria-live="polite">Chargement de la spec…</div>
        )}

        {/* Contenu */}
        {!loading && displaySpec && (
          <>
            {/* Méta */}
            <div className="spec-detail-meta">
              <span>ID : <code>{specId}</code></span>
              <span>· {displaySpec.domain}</span>
              {displaySpec.version && <span>· v{displaySpec.version}</span>}
              <span style={{ color: scoreColor(displaySpec.score) }}>
                · score {displaySpec.score.toFixed(2)}
              </span>
              {displaySpec.validated
                ? <span style={{ color: 'var(--success)' }}>· ✅ Validée</span>
                : <span style={{ color: 'var(--warning)' }}>· ⚠ Non validée</span>
              }
            </div>

            {/* Corps Markdown */}
            <div className="spec-detail-body">
              {displaySpec.body_md
                ? <MarkdownRenderer content={displaySpec.body_md} />
                : <p className="context-empty">Corps de la spec non disponible.</p>
              }
            </div>

            {/* Violations */}
            {violations.length > 0 && (
              <div className="spec-detail-violations">
                <h3>Violations ({violations.length})</h3>
                {violations.map((v, i) => (
                  <div key={i} className={`violation violation-${v.severity ?? 'warning'}`}>
                    <span className="violation-rule">
                      [{(v.severity ?? 'warning').toUpperCase()}] {v.rule ?? '?'}
                    </span>
                    <span className="violation-fix"> — {v.fix_suggestion ?? ''}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Footer */}
            <div className="modal-footer">
              <button onClick={handleExport} className="btn-secondary">
                ⬇ Exporter .md
              </button>
              <button onClick={onClose} className="btn-primary">
                Fermer
              </button>
            </div>
          </>
        )}

        {/* Spec introuvable */}
        {!loading && !displaySpec && (
          <div className="modal-error">
            Spec <code>{specId}</code> introuvable ou erreur MCP.
            <div className="modal-footer">
              <button onClick={onClose} className="btn-primary">Fermer</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
