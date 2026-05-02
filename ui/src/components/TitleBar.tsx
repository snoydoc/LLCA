// TitleBar.tsx — UI-05-ENH : gem animée + pill MCP + version badge + tps badge (V9-06) + educator badge (UI-08)
// PROJ-UI-05 : affichage projet actif + bouton retour
import { Minus, Square, X, Moon, Sun, FolderOpen, ChevronLeft } from 'lucide-react';
import { useContextStore }  from '../stores/contextStore';
import { useSettingsStore } from '../stores/settingsStore';
import { useProjectStore }  from '../stores/projectStore';

function TpsIndicator() {
  const tpsData = useContextStore(s => s.tpsData);
  if (!tpsData || tpsData.last === null) return null;
  const val = tpsData.last.toFixed(1);
  return (
    <div className="tps-badge" title={`Modèle : ${tpsData.model ?? '?'} · ${tpsData.count} mesure(s) · moy. ${tpsData.avg?.toFixed(1) ?? '?'} tok/s`} aria-label={`Vitesse LLM : ${val} tok/s`}>
      ⚡ {val} <span className="tps-unit">tok/s</span>
    </div>
  );
}

function EducatorBadge() {
  const educatorData = useContextStore(s => s.educatorData);
  // Ne pas afficher si non configuré ou jamais pollé
  if (!educatorData || educatorData.status === 'not_configured') return null;

  const isIdle    = educatorData.status === 'idle';
  const hasErrors = educatorData.errors > 0;
  const label     = isIdle
    ? '🎓 idle'
    : `🎓 ${educatorData.repos}r · ${educatorData.skills}s`;

  const tooltipParts = [
    `Statut : ${educatorData.status}`,
    isIdle ? null : `Repos : ${educatorData.repos}`,
    isIdle ? null : `Skills : ${educatorData.skills}`,
    educatorData.dry_run ? '(dry-run)' : null,
    hasErrors ? `⚠️ ${educatorData.errors} erreur(s)` : null,
  ].filter(Boolean).join(' · ');

  const cls = [
    'educator-badge',
    hasErrors  ? 'educator-badge--err'  : '',
    isIdle     ? 'educator-badge--idle' : 'educator-badge--ok',
  ].filter(Boolean).join(' ');

  return (
    <div className={cls} title={tooltipParts} aria-label={`Educator : ${tooltipParts}`}>
      {label}{hasErrors && <span className="educator-badge-err"> ⚠</span>}
    </div>
  );
}

export function TitleBar() {
  const { mcpStatus } = useContextStore();
  const { theme, setTheme } = useSettingsStore();
  const { activeProject, closeProject } = useProjectStore();

  const mcpLabel = {
    connected:    'MCP',
    connecting:   'MCP…',
    disconnected: 'MCP',
    error:        'MCP ✕',
  }[mcpStatus] ?? 'MCP';

  return (
    <div className="title-bar">
      {/* Gem + nom app */}
      <span className="title-bar-app-name">
        <div className="title-bar-gem" aria-hidden="true" />
        Adham
      </span>

      {/* PROJ-UI-05 : contexte projet actif */}
      {activeProject && (
        <>
          <span style={{ color: 'var(--border-strong)', fontSize: 11 }} aria-hidden="true">›</span>
          <div
            style={{
              display:    'flex',
              alignItems: 'center',
              gap:        5,
              padding:    '2px 8px',
              background: 'var(--accent-dim)',
              border:     '1px solid var(--b-acc)',
              borderRadius: 'var(--radius-full)',
              fontSize:   10.5,
              fontFamily: 'var(--font-mono)',
              fontWeight: 600,
              color:      'var(--accent)',
              maxWidth:   180,
              overflow:   'hidden',
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
            } as any}
            title={activeProject.description || activeProject.name}
          >
            <FolderOpen size={11} style={{ flexShrink: 0 }} />
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {activeProject.name}
            </span>
          </div>
          <button
            onClick={closeProject}
            title="Retour à la liste des projets"
            aria-label="Fermer le projet actif"
            style={{
              display:    'flex',
              alignItems: 'center',
              gap:        3,
              padding:    '2px 7px',
              background: 'transparent',
              border:     '1px solid var(--border)',
              borderRadius: 'var(--radius-full)',
              color:      'var(--text-muted)',
              fontSize:   10,
              fontFamily: 'var(--font-mono)',
              cursor:     'pointer',
              transition: 'all 0.15s',
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
            } as any}
            onMouseEnter={e => {
              e.currentTarget.style.color        = 'var(--text-primary)';
              e.currentTarget.style.borderColor  = 'var(--border-strong)';
            }}
            onMouseLeave={e => {
              e.currentTarget.style.color        = 'var(--text-muted)';
              e.currentTarget.style.borderColor  = 'var(--border)';
            }}
          >
            <ChevronLeft size={10} />
            Projets
          </button>
        </>
      )}

      {/* Pill MCP avec statut dot */}
      <div
        className="title-bar-mcp-pill"
        title={`McpServer : ${mcpStatus}`}
        aria-label={`Statut MCP : ${mcpStatus}`}
      >
        <span className={`status-dot status-${mcpStatus}`} />
        {mcpLabel}
      </div>

      {/* Badge version discret */}
      <span className="title-bar-version" aria-hidden="true">v8</span>

      {/* Badge tok/s — V9-06 */}
      <TpsIndicator />

      {/* Badge Educator — UI-08 */}
      <EducatorBadge />

      <div className="title-bar-spacer" />

      {/* Toggle thème avec classe améliorée */}
      <button
        className="title-bar-btn theme-toggle"
        onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        aria-label={`Basculer vers le thème ${theme === 'dark' ? 'clair' : 'sombre'}`}
        title={`Thème ${theme === 'dark' ? 'clair' : 'sombre'} (Ctrl+Shift+T)`}
      >
        {theme === 'dark' ? <Sun size={13} /> : <Moon size={13} />}
      </button>

      {/* Contrôles fenêtre */}
      <div className="title-bar-controls">
        <button
          className="title-bar-btn"
          aria-label="Réduire"
          onClick={() => (window as any).lcca.windowControl('minimize')}
        >
          <Minus size={11} />
        </button>
        <button
          className="title-bar-btn"
          aria-label="Agrandir"
          onClick={() => (window as any).lcca.windowControl('maximize')}
        >
          <Square size={11} />
        </button>
        <button
          className="title-bar-btn close"
          aria-label="Fermer"
          onClick={() => (window as any).lcca.windowControl('close')}
        >
          <X size={11} />
        </button>
      </div>
    </div>
  );
}
