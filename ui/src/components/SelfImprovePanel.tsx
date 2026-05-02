// SelfImprovePanel.tsx — SI-06 : panneau SelfImprove dans les Paramètres
// Polling 30s | window.lcca.si.* | 0 couleur hardcodée (themes.css uniquement)
import { useState, useEffect } from 'react';

// ─── Types ────────────────────────────────────────────────────────────────────

interface SIStatus {
  coupling_mode:       number;
  auto_fix_enabled:    boolean;
  observer_active:     boolean;
  orchestrator_active: boolean;
  last_obs_ts:         number | null;
  pending_count:       number;
}

interface SIAction {
  timestamp: string;
  rule_id:   string;
  action:    string;
  status:    string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatTs(ts: number | null): string {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function statusColor(status: string): string {
  if (status === 'success') return 'var(--success)';
  if (status === 'failed')  return 'var(--error)';
  return 'var(--info)';
}

function statusBg(status: string): string {
  if (status === 'success') return 'var(--success-dim)';
  if (status === 'failed')  return 'var(--error-dim)';
  return 'var(--info-dim)';
}

// ─── Section : Mode de couplage ───────────────────────────────────────────────

const MODES = [
  { id: 1, label: 'Lecture seule', ram: '~50 MB',  desc: 'Observer + dry-run uniquement' },
  { id: 2, label: 'Semi-couplé',   ram: '~150 MB', desc: 'Observer + Orchestrator (défaut)' },
  { id: 3, label: 'Pipeline',      ram: '~300 MB', desc: 'Pipeline complet via A2ABus' },
];

function ModeSection({
  status,
  onCommand,
}: {
  status: SIStatus | null;
  onCommand: (cmd: string) => void;
}) {
  const active = status?.coupling_mode ?? 2;

  return (
    <section style={{ marginBottom: 14 }}>
      <div style={{
        fontSize: 'var(--font-size-xs)',
        fontWeight: 600,
        letterSpacing: 'var(--letter-spacing-wide)',
        textTransform: 'uppercase',
        color: 'var(--text-muted)',
        marginBottom: 6,
      }}>
        Mode de couplage
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {MODES.map(m => {
          const isActive = m.id === active;
          return (
            <button
              key={m.id}
              onClick={() => onCommand(`mode ${m.id}`)}
              title={m.desc}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '5px 8px',
                borderRadius: 'var(--radius-sm)',
                border: `1px solid ${isActive ? 'var(--b-acc)' : 'var(--b1)'}`,
                background: isActive ? 'var(--accent-dim)' : 'var(--bg-surface)',
                color: isActive ? 'var(--accent)' : 'var(--text-secondary)',
                cursor: 'pointer',
                textAlign: 'left',
                transition: 'var(--transition-fast)',
              }}
            >
              <span style={{
                fontSize: 'var(--font-size-xs)',
                fontWeight: isActive ? 600 : 400,
                minWidth: 80,
              }}>
                {m.label}
              </span>
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                color: isActive ? 'var(--accent)' : 'var(--text-muted)',
              }}>
                {m.ram}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

// ─── Section : État système ───────────────────────────────────────────────────

function StatusRow({ label, active }: { label: string; active: boolean | undefined }) {
  const ok = active === true;
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '3px 0',
    }}>
      <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--text-secondary)' }}>
        {label}
      </span>
      <span style={{
        fontSize: 10,
        fontWeight: 600,
        padding: '1px 6px',
        borderRadius: 'var(--radius-xs)',
        background: ok ? 'var(--success-dim)' : 'var(--info-dim)',
        color: ok ? 'var(--success)' : 'var(--info)',
        border: `1px solid ${ok ? 'rgba(52,211,153,0.2)' : 'rgba(96,165,250,0.2)'}`,
      }}>
        {ok ? 'actif' : 'off'}
      </span>
    </div>
  );
}

function SystemStateSection({
  status,
  onCommand,
}: {
  status: SIStatus | null;
  onCommand: (cmd: string) => void;
}) {
  return (
    <section style={{ marginBottom: 14 }}>
      <div style={{
        fontSize: 'var(--font-size-xs)',
        fontWeight: 600,
        letterSpacing: 'var(--letter-spacing-wide)',
        textTransform: 'uppercase',
        color: 'var(--text-muted)',
        marginBottom: 6,
      }}>
        État système
      </div>
      <div style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-sm)',
        padding: '6px 8px',
        marginBottom: 6,
      }}>
        <StatusRow label="Observer"     active={status?.observer_active} />
        <StatusRow label="Orchestrator" active={status?.orchestrator_active} />
        <StatusRow label="Auto-Fix"     active={status?.auto_fix_enabled} />
        <div style={{
          marginTop: 4,
          paddingTop: 4,
          borderTop: '1px solid var(--border)',
          fontFamily: 'var(--font-mono)',
          fontSize: 9.5,
          color: 'var(--text-muted)',
        }}>
          Dernière obs : {formatTs(status?.last_obs_ts ?? null)}
        </div>
      </div>
      <button
        onClick={() => onCommand('observe')}
        style={{
          width: '100%',
          padding: '5px 0',
          borderRadius: 'var(--radius-sm)',
          border: '1px solid var(--b1)',
          background: 'var(--bg-elevated)',
          color: 'var(--text-secondary)',
          fontSize: 'var(--font-size-xs)',
          cursor: 'pointer',
          transition: 'var(--transition-fast)',
        }}
        onMouseEnter={e => {
          (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--b-acc)';
          (e.currentTarget as HTMLButtonElement).style.color = 'var(--accent)';
        }}
        onMouseLeave={e => {
          (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--b1)';
          (e.currentTarget as HTMLButtonElement).style.color = 'var(--text-secondary)';
        }}
      >
        ▶ Observer maintenant
      </button>
    </section>
  );
}

// ─── Section : Mini-log ───────────────────────────────────────────────────────

function MiniLogSection({
  history,
  onShowAll,
}: {
  history: SIAction[];
  onShowAll: () => void;
}) {
  return (
    <section>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 6,
      }}>
        <span style={{
          fontSize: 'var(--font-size-xs)',
          fontWeight: 600,
          letterSpacing: 'var(--letter-spacing-wide)',
          textTransform: 'uppercase',
          color: 'var(--text-muted)',
        }}>
          Dernières actions
        </span>
        <button
          onClick={onShowAll}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--accent)',
            fontSize: 10,
            cursor: 'pointer',
            padding: 0,
          }}
        >
          Voir tout
        </button>
      </div>

      {history.length === 0
        ? (
          <p style={{
            fontSize: 'var(--font-size-xs)',
            color: 'var(--text-muted)',
            fontStyle: 'italic',
            margin: 0,
          }}>
            Aucune action enregistrée
          </p>
        )
        : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            {history.map((a, i) => (
              <div key={i} style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                background: 'var(--bg-surface)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-xs)',
                padding: '3px 6px',
              }}>
                <span style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 9,
                  color: 'var(--text-muted)',
                  minWidth: 50,
                  flexShrink: 0,
                }}>
                  {a.timestamp.slice(11, 19) || a.timestamp}
                </span>
                <span style={{
                  fontSize: 10,
                  color: 'var(--text-secondary)',
                  flex: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}>
                  {a.rule_id || a.action}
                </span>
                <span style={{
                  fontSize: 9,
                  fontWeight: 600,
                  padding: '1px 5px',
                  borderRadius: 'var(--radius-xs)',
                  background: statusBg(a.status),
                  color: statusColor(a.status),
                  flexShrink: 0,
                }}>
                  {a.status || '—'}
                </span>
              </div>
            ))}
          </div>
        )
      }
    </section>
  );
}

// ─── Modal : log complet ──────────────────────────────────────────────────────

function FullLogModal({
  history,
  onClose,
}: {
  history: SIAction[];
  onClose: () => void;
}) {
  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(0,0,0,0.6)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: 'var(--bg-primary)',
          border: '1px solid var(--border-strong)',
          borderRadius: 'var(--radius-md)',
          padding: 16,
          width: 480,
          maxHeight: '70vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: 'var(--shadow-lg)',
        }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 10,
        }}>
          <span style={{ fontWeight: 600, fontSize: 'var(--font-size-sm)', color: 'var(--text-primary)' }}>
            Historique actions.log
          </span>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 16 }}
          >
            ×
          </button>
        </div>
        <div style={{ overflowY: 'auto', flex: 1 }}>
          {history.length === 0
            ? <p style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-xs)' }}>Aucune entrée</p>
            : history.map((a, i) => (
              <div key={i} style={{
                display: 'grid',
                gridTemplateColumns: '110px 1fr 70px',
                gap: 8,
                padding: '4px 0',
                borderBottom: '1px solid var(--border)',
                fontSize: 'var(--font-size-xs)',
              }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--text-muted)' }}>
                  {a.timestamp}
                </span>
                <span style={{ color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {a.rule_id} — {a.action}
                </span>
                <span style={{
                  fontSize: 9,
                  fontWeight: 600,
                  padding: '1px 5px',
                  borderRadius: 'var(--radius-xs)',
                  background: statusBg(a.status),
                  color: statusColor(a.status),
                  textAlign: 'center',
                }}>
                  {a.status || '—'}
                </span>
              </div>
            ))
          }
        </div>
      </div>
    </div>
  );
}

// ─── SelfImprovePanel ─────────────────────────────────────────────────────────

export function SelfImprovePanel() {
  const [status,      setStatus]      = useState<SIStatus | null>(null);
  const [history,     setHistory]     = useState<SIAction[]>([]);
  const [running,     setRunning]     = useState(false);
  const [showAllLog,  setShowAllLog]  = useState(false);
  const [fullHistory, setFullHistory] = useState<SIAction[]>([]);

  const load = async () => {
    try {
      const [s, h] = await Promise.all([
        (window as unknown as { lcca: { si: { getStatus: () => Promise<SIStatus> } } }).lcca.si.getStatus(),
        (window as unknown as { lcca: { si: { getHistory: (n: number) => Promise<SIAction[]> } } }).lcca.si.getHistory(5),
      ]);
      setStatus(s);
      setHistory(h);
    } catch { /* ignore */ }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, []);

  const handleCommand = async (cmd: string) => {
    setRunning(true);
    try {
      await (window as unknown as { lcca: { si: { runCommand: (c: string) => Promise<unknown> } } }).lcca.si.runCommand(cmd);
      await load(); // rafraîchir statut après exécution
    } catch { /* ignore */ }
    setRunning(false);
  };

  const handleShowAll = async () => {
    try {
      const h = await (window as unknown as { lcca: { si: { getHistory: (n: number) => Promise<SIAction[]> } } }).lcca.si.getHistory(200);
      setFullHistory(h);
    } catch { setFullHistory(history); }
    setShowAllLog(true);
  };

  return (
    <div style={{ padding: '12px 14px', position: 'relative' }}>
      {/* Indicateur de traitement en cours */}
      {running && (
        <div style={{
          position: 'absolute', top: 8, right: 14,
          fontSize: 9,
          color: 'var(--accent)',
          fontFamily: 'var(--font-mono)',
          animation: 'pulse 1s infinite',
        }}>
          ···
        </div>
      )}

      <ModeSection      status={status} onCommand={handleCommand} />
      <SystemStateSection status={status} onCommand={handleCommand} />
      <MiniLogSection   history={history} onShowAll={handleShowAll} />

      {showAllLog && (
        <FullLogModal
          history={fullHistory}
          onClose={() => setShowAllLog(false)}
        />
      )}
    </div>
  );
}
