// InspirationPanel.tsx — PROJ-UI-01 + PROJ-UI-03
// Stub V1 : saisie mot-clé + UI squelette.
// PROJ-UI-02 : Pipeline LLM (inspiration_generate MCP tool).
// PROJ-UI-03 : Skeleton cards animés + label génération en cours.

import { useState, useEffect, useRef } from 'react';

export interface IdeaCard {
  title:             string;
  description:       string;
  domain:            string;
  tech_stack:        string[];
  difficulty:        'débutant' | 'intermédiaire' | 'avancé';
  estimated_sprints: number;
  tags:              string[];
  quality_score:     number;
}

interface InspirationPanelProps {
  onClose:         () => void;
  /** Appelé quand l'utilisateur clique "+ Créer ce projet" sur une idée */
  onCreateFromIdea: (idea: IdeaCard) => void;
}

// ── Skeleton cards (PROJ-UI-03) ─────────────────────────────────────────────

function SkeletonCard({ delay }: { delay: number }) {
  const lineStyle = {
    animationDelay: `${delay}ms`,
  };
  return (
    <div className="insp-skeleton-card">
      {/* Titre + badge difficulté */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <div className="insp-skeleton-line insp-skeleton-title" style={lineStyle} />
        <div
          className="insp-skeleton-line"
          style={{ ...lineStyle, height: 18, width: 72, borderRadius: 20, flexShrink: 0 }}
        />
      </div>
      {/* Description 2 lignes */}
      <div className="insp-skeleton-line insp-skeleton-desc" style={lineStyle} />
      <div className="insp-skeleton-line insp-skeleton-desc-short" style={lineStyle} />
      {/* Meta */}
      <div className="insp-skeleton-line insp-skeleton-meta" style={lineStyle} />
      {/* Bouton */}
      <div className="insp-skeleton-line insp-skeleton-btn" style={lineStyle} />
    </div>
  );
}

function SkeletonList() {
  return (
    <>
      {/* Label "Génération en cours" avec 3 points pulsants */}
      <div className="insp-generating-label">
        <div className="insp-generating-dot" />
        <div className="insp-generating-dot" />
        <div className="insp-generating-dot" />
        <span style={{ marginLeft: 4 }}>Génération en cours…</span>
      </div>
      <div className="insp-skeleton-list">
        <SkeletonCard delay={0} />
        <SkeletonCard delay={160} />
        <SkeletonCard delay={320} />
      </div>
    </>
  );
}

// ── Helpers visuels ──────────────────────────────────────────────────────────

const DIFFICULTY_COLOR: Record<string, string> = {
  'débutant':      'var(--success)',
  'intermédiaire': 'var(--warning)',
  'avancé':        'var(--accent)',
};

function DifficultyBadge({ level }: { level: string }) {
  return (
    <span
      style={{
        fontSize:    10,
        fontFamily:  'var(--font-mono)',
        fontWeight:  600,
        padding:     '2px 7px',
        borderRadius: 'var(--radius-full)',
        border:      `1px solid ${DIFFICULTY_COLOR[level] ?? 'var(--border)'}`,
        color:       DIFFICULTY_COLOR[level] ?? 'var(--text-muted)',
        background:  'transparent',
        whiteSpace:  'nowrap',
        flexShrink:  0,
      }}
    >
      {level}
    </span>
  );
}

function IdeaCardView({
  idea,
  onCreate,
}: {
  idea: IdeaCard;
  onCreate: () => void;
}) {
  return (
    <div className="insp-card">
      {/* En-tête : titre + difficulté */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
        <span className="insp-card-title">{idea.title}</span>
        <DifficultyBadge level={idea.difficulty} />
      </div>

      {/* Description */}
      <p className="insp-card-desc">{idea.description}</p>

      {/* Stack + sprints */}
      <div className="insp-card-meta">
        <span className="insp-card-stack">
          {idea.tech_stack.join(' · ')}
        </span>
        <span className="insp-card-sprints">
          ~{idea.estimated_sprints} sprints
        </span>
      </div>

      {/* Tags */}
      {idea.tags.length > 0 && (
        <div className="insp-card-tags">
          {idea.tags.map(tag => (
            <span key={tag} className="insp-tag">#{tag}</span>
          ))}
        </div>
      )}

      {/* Action */}
      <button
        className="insp-card-btn"
        onClick={onCreate}
      >
        + Créer ce projet
      </button>
    </div>
  );
}

// ── Composant principal ──────────────────────────────────────────────────────

export function InspirationPanel({ onClose, onCreateFromIdea }: InspirationPanelProps) {
  const [keyword,   setKeyword]   = useState('');
  const [ideas,     setIdeas]     = useState<IdeaCard[]>([]);
  const [loading,   setLoading]   = useState(false);
  const [error,     setError]     = useState<string | null>(null);
  const [generated, setGenerated] = useState(false);
  const inputRef                  = useRef<HTMLInputElement>(null);

  // Focus auto à l'ouverture
  useEffect(() => { inputRef.current?.focus(); }, []);

  // Fermeture Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const handleGenerate = async () => {
    const kw = keyword.trim();
    if (!kw) return;
    setLoading(true);
    setError(null);
    setIdeas([]);

    try {
      // Appel MCP tool inspiration_generate (si disponible)
      const lcca = (window as unknown as { lcca: { mcpCall: (t: string, a: object) => Promise<unknown> } }).lcca;
      const result = await lcca.mcpCall('inspiration_generate', { keyword: kw, online: false });

      const payload = result as { ideas?: IdeaCard[]; error?: string };
      if (payload.error) throw new Error(payload.error);
      setIdeas(payload.ideas ?? []);
      setGenerated(true);
    } catch (err) {
      // Fallback : 3 templates statiques si le MCP tool est absent
      setIdeas(_fallbackIdeas(kw));
      setGenerated(true);
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = (idea: IdeaCard) => {
    onCreateFromIdea(idea);
    onClose();
  };

  return (
    /* Overlay */
    <div
      className="insp-overlay"
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      {/* Panel */}
      <div className="insp-panel">

        {/* ── En-tête ── */}
        <div className="insp-header">
          <span className="insp-title">💡 Mode Inspiration</span>
          <button className="insp-close" onClick={onClose} title="Fermer">✕</button>
        </div>

        {/* ── Saisie mot-clé ── */}
        <div className="insp-search-row">
          <input
            ref={inputRef}
            className="insp-input"
            value={keyword}
            onChange={e => { setKeyword(e.target.value); setGenerated(false); }}
            onKeyDown={e => { if (e.key === 'Enter') handleGenerate(); }}
            placeholder="ex: agent médical, outil CLI, dashboard analytics…"
            maxLength={100}
            disabled={loading}
          />
          <button
            className="insp-btn-generate"
            onClick={handleGenerate}
            disabled={loading || !keyword.trim()}
          >
            {loading ? <span style={{ letterSpacing: 1 }}>…</span> : '⬡ Générer'}
          </button>
        </div>

        {/* ── Mode : local (toujours offline en V1) ── */}
        <div className="insp-mode-badge">
          <span>⬡ Local · 100% offline</span>
        </div>

        {/* ── Skeleton loading (PROJ-UI-03) ── */}
        {loading && <SkeletonList />}

        {/* ── Erreur ── */}
        {!loading && error && (
          <div className="insp-error">{error}</div>
        )}

        {/* ── Résultats ── */}
        {!loading && generated && ideas.length === 0 && (
          <div className="insp-empty">
            Aucune idée générée — reformule le mot-clé.
          </div>
        )}

        {ideas.length > 0 && (
          <div className="insp-results">
            {ideas.map((idea, i) => (
              <IdeaCardView
                key={i}
                idea={idea}
                onCreate={() => handleCreate(idea)}
              />
            ))}
          </div>
        )}

        {/* ── État initial (avant génération) ── */}
        {!loading && !generated && !loading && (
          <div className="insp-placeholder">
            <div style={{ fontSize: 28, opacity: 0.25, marginBottom: 10 }}>💡</div>
            <span>Saisis un domaine ou un mot-clé pour générer des idées de projets.</span>
          </div>
        )}

        {/* ── Footer : note V1 ── */}
        <div className="insp-footer">
          V1 — pipeline LLM local (qwen2.5-coder:3b) · 3 idées max · fallback templates inclus
        </div>
      </div>
    </div>
  );
}

// ── Fallback templates si MCP tool absent ────────────────────────────────────

function _fallbackIdeas(keyword: string): IdeaCard[] {
  const kw = keyword.toLowerCase();
  return [
    {
      title:             `Outil CLI pour ${kw}`,
      description:       `Un outil en ligne de commande interactif pour automatiser les tâches liées à ${kw}.`,
      domain:            kw,
      tech_stack:        ['Python', 'Click', 'SQLite', 'Rich'],
      difficulty:        'débutant',
      estimated_sprints: 5,
      tags:              ['cli', 'automatisation', kw],
      quality_score:     0.70,
    },
    {
      title:             `Dashboard de suivi ${kw}`,
      description:       `Interface web pour visualiser et piloter les métriques associées à ${kw} en temps réel.`,
      domain:            kw,
      tech_stack:        ['Python', 'FastAPI', 'React', 'SQLite'],
      difficulty:        'intermédiaire',
      estimated_sprints: 10,
      tags:              ['dashboard', 'visualisation', kw],
      quality_score:     0.72,
    },
    {
      title:             `Agent conversationnel ${kw}`,
      description:       `Chatbot local spécialisé dans le domaine ${kw}, utilisant Ollama en mode offline.`,
      domain:            kw,
      tech_stack:        ['Python', 'Ollama', 'ChromaDB', 'FastAPI'],
      difficulty:        'avancé',
      estimated_sprints: 14,
      tags:              ['ia', 'offline', kw],
      quality_score:     0.75,
    },
  ];
}
