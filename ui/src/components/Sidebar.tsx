// Sidebar.tsx — UI-DS-05 : sessions .sb-session avec numéro + barre active
// SI-06 : badge pending_count sur bouton Paramètres
import { useState, useEffect } from 'react';
import { Settings, HelpCircle, Plus } from 'lucide-react';
import { useChatStore } from '../stores/chatStore';

interface SidebarProps {
  onOpenSettings?: () => void;
  onOpenHelp?:     () => void;
}

/** Génère le label court d'une session : S1, S2... (ou initiale du titre) */
function sessionLabel(title: string | undefined, index: number): string {
  if (!title || title.trim() === '') return `S${index + 1}`;
  // Si le titre est court (≤ 2 chars) on l'utilise directement
  if (title.trim().length <= 2) return title.trim().toUpperCase();
  // Sinon : première lettre du titre en majuscule
  return title.trim()[0].toUpperCase();
}

export function Sidebar({ onOpenSettings, onOpenHelp }: SidebarProps) {
  const {
    sessions, activeSessionId,
    setActiveSession, createSession, deleteSession,
  } = useChatStore();

  // SI-06 : récupérer le nombre de suggestions en attente (polling 30s)
  const [pendingCount, setPendingCount] = useState(0);
  useEffect(() => {
    const fetchPending = async () => {
      try {
        const s = await (window as unknown as { lcca: { si: { getStatus: () => Promise<{ pending_count: number }> } } }).lcca.si.getStatus();
        setPendingCount(s.pending_count ?? 0);
      } catch { /* ignore */ }
    };
    fetchPending();
    const id = setInterval(fetchPending, 30_000);
    return () => clearInterval(id);
  }, []);

  const handleDelete = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (sessions.length <= 1) return;
    deleteSession(id);
  };

  return (
    <aside className="sidebar" aria-label="Barre latérale">
      {/* Bouton nouvelle session */}
      <button
        className="sidebar-icon-btn"
        onClick={createSession}
        title="Nouvelle session (Ctrl+N)"
        aria-label="Nouvelle session"
      >
        <Plus size={17} />
      </button>

      {/* Divider dégradé */}
      <div className="sidebar-divider" />

      {/* Sessions — badge .sb-session avec numéro */}
      <div className="sidebar-sessions" role="list" aria-label="Sessions">
        {sessions.slice(0, 10).map((session, idx) => (
          <div
            key={session.id}
            className="sidebar-session-item"
            role="listitem"
          >
            <button
              className={`sb-session${session.id === activeSessionId ? ' on' : ''}`}
              onClick={() => setActiveSession(session.id)}
              title={session.title || `Session ${idx + 1}`}
              aria-label={session.title || `Session ${idx + 1}`}
              aria-current={session.id === activeSessionId ? 'true' : undefined}
            >
              {sessionLabel(session.title, idx)}
            </button>
            {sessions.length > 1 && (
              <button
                className="sidebar-session-delete"
                onClick={e => handleDelete(e, session.id)}
                title="Supprimer la session"
                aria-label="Supprimer la session"
              >
                ×
              </button>
            )}
          </div>
        ))}
      </div>

      <div className="sidebar-spacer" />

      {/* Divider + boutons bas */}
      <div className="sidebar-bottom-divider" />

      <button
        className="sidebar-icon-btn"
        onClick={onOpenHelp}
        title="Aide (F1)"
        aria-label="Aide"
      >
        <HelpCircle size={15} />
      </button>
      <button
        className="sidebar-icon-btn"
        onClick={onOpenSettings}
        title="Paramètres (Ctrl+,)"
        aria-label="Paramètres"
        style={{ position: 'relative' }}
      >
        <Settings size={15} />
        {pendingCount > 0 && (
          <span style={{
            position: 'absolute',
            top: 2, right: 2,
            minWidth: 14, height: 14,
            padding: '0 3px',
            borderRadius: 'var(--radius-full)',
            background: 'var(--accent)',
            color: 'var(--bg-base)',
            fontSize: 9,
            fontFamily: 'var(--font-mono)',
            fontWeight: 700,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            lineHeight: 1,
            pointerEvents: 'none',
          }}>
            {pendingCount}
          </span>
        )}
      </button>
    </aside>
  );
}
