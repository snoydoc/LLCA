// TelemetryPanel.tsx — V9-09
// Panneau télémétrie tok/s : graphe sparkline SVG + métriques agrégées.
// Utilise telemetryStore (polling 10s, découplé du contextStore).
// S'intègre dans ContextPanel comme section additionnelle.

import { useEffect } from 'react';
import { useTelemetryStore, type TpsPoint } from '../stores/telemetryStore';

// ─── Sparkline SVG ────────────────────────────────────────────────────────────

interface SparklineProps {
  points:  TpsPoint[];
  width:   number;
  height:  number;
}

function Sparkline({ points, width, height }: SparklineProps) {
  if (points.length < 2) {
    return (
      <svg width={width} height={height} aria-hidden="true">
        <line x1={0} y1={height / 2} x2={width} y2={height / 2}
              stroke="var(--color-border)" strokeDasharray="4 4" strokeWidth={1} />
        <text x={width / 2} y={height / 2 + 4} textAnchor="middle"
              fontSize={10} fill="var(--color-text-dim)">
          En attente de données…
        </text>
      </svg>
    );
  }

  const values = points.map(p => p.value);
  const min    = Math.min(...values);
  const max    = Math.max(...values);
  const range  = max - min || 1;

  const pad = 4;
  const w   = width  - pad * 2;
  const h   = height - pad * 2;

  // Normalise les points en coordonnées SVG
  const coords = points.map((p, i) => {
    const x = pad + (i / (points.length - 1)) * w;
    const y = pad + h - ((p.value - min) / range) * h;
    return { x, y };
  });

  const pathD = coords
    .map((c, i) => `${i === 0 ? 'M' : 'L'} ${c.x.toFixed(1)} ${c.y.toFixed(1)}`)
    .join(' ');

  // Zone de remplissage (fill sous la courbe)
  const fillD = `${pathD} L ${coords[coords.length - 1].x.toFixed(1)} ${height - pad} L ${pad} ${height - pad} Z`;

  const lastPoint = coords[coords.length - 1];

  return (
    <svg width={width} height={height} aria-label="Graphe tok/s" role="img">
      {/* Grille horizontale légère */}
      {[0.25, 0.5, 0.75].map(ratio => {
        const y = pad + h - ratio * h;
        return (
          <line key={ratio} x1={pad} y1={y} x2={width - pad} y2={y}
                stroke="var(--color-border)" strokeOpacity={0.4} strokeWidth={0.5} />
        );
      })}

      {/* Zone remplie */}
      <path d={fillD} fill="var(--color-accent)" fillOpacity={0.08} />

      {/* Courbe principale */}
      <path d={pathD} fill="none" stroke="var(--color-accent)"
            strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />

      {/* Point courant */}
      <circle cx={lastPoint.x} cy={lastPoint.y} r={3}
              fill="var(--color-accent)" />
    </svg>
  );
}

// ─── Ligne métrique ───────────────────────────────────────────────────────────

function MetricRow({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="telemetry-metric-row">
      <span className="telemetry-metric-label">{label}</span>
      <span className="telemetry-metric-value">{value ?? '—'}</span>
    </div>
  );
}

// ─── TelemetryPanel ───────────────────────────────────────────────────────────

export function TelemetryPanel() {
  const { history, aggregate, loading, lastRefresh, startPolling, refresh } =
    useTelemetryStore();

  // Démarrage du polling au montage
  useEffect(() => {
    const stop = startPolling();
    return stop;
  }, []);

  const hasData = history.length > 0 || aggregate !== null;

  const lastRefreshLabel = lastRefresh
    ? new Date(lastRefresh).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : null;

  return (
    <section className="context-section telemetry-panel" aria-label="Télémétrie tok/s">
      {/* En-tête */}
      <div className="context-section-header">
        <h3>⚡ Télémétrie LLM</h3>
        <button
          className="context-refresh-btn"
          onClick={() => refresh().catch(() => {})}
          disabled={loading}
          aria-label="Rafraîchir la télémétrie"
          title="Rafraîchir"
        >
          {loading ? '…' : '⟳'}
        </button>
      </div>

      <div className="context-section-body">
        {/* Graphe sparkline */}
        <div className="telemetry-sparkline-wrap">
          <Sparkline points={history} width={220} height={64} />
        </div>

        {/* Métriques agrégées */}
        {aggregate && (
          <div className="telemetry-metrics">
            <MetricRow label="Dernier"  value={aggregate.last  != null ? `${aggregate.last} tok/s` : null} />
            <MetricRow label="Moyenne"  value={aggregate.avg   != null ? `${aggregate.avg} tok/s`  : null} />
            <MetricRow label="Mesures"  value={aggregate.count > 0 ? `${aggregate.count}` : null} />
            <MetricRow label="Modèle"   value={aggregate.model} />
          </div>
        )}

        {/* État vide */}
        {!hasData && !loading && (
          <p className="telemetry-empty">
            Aucune donnée — lance un appel LLM pour voir les métriques.
          </p>
        )}

        {/* Timestamp dernier refresh */}
        {lastRefreshLabel && (
          <p className="telemetry-ts" aria-label={`Dernière mise à jour : ${lastRefreshLabel}`}>
            Mis à jour : {lastRefreshLabel}
          </p>
        )}
      </div>
    </section>
  );
}
