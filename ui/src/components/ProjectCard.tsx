// ProjectCard.tsx — PROJ-05 : carte projet dans l'écran d'accueil
// Affiche nom, description, date, statut — boutons Reprendre + Archiver

import { ProjectMeta } from '../stores/projectStore';

interface ProjectCardProps {
  project:    ProjectMeta;
  onOpen:     (id: string) => void;
  onArchive:  (id: string) => void;
}

/** Formate une date ISO en "il y a X jours / heures / minutes" */
function relativeTime(isoDate: string): string {
  const diff = Date.now() - new Date(isoDate).getTime();
  const min  = Math.floor(diff / 60_000);
  if (min < 1)   return 'à l\'instant';
  if (min < 60)  return `il y a ${min} min`;
  const hrs = Math.floor(min / 60);
  if (hrs < 24)  return `il y a ${hrs} h`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `il y a ${days} j`;
  return new Date(isoDate).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
}

export function ProjectCard({ project, onOpen, onArchive }: ProjectCardProps) {
  const isArchived = project.status === 'archived';

  return (
    <div
      className="proj-card"
      data-archived={isArchived ? 'true' : undefined}
      style={{
        display:       'flex',
        flexDirection: 'column',
        gap:           8,
        padding:       '14px 16px',
        background:    'var(--bg-surface)',
        border:        '1px solid var(--border)',
        borderRadius:  8,
        transition:    'border-color 0.15s, background 0.15s',
        opacity:       isArchived ? 0.55 : 1,
      }}
    >
      {/* En-tête : nom + badge statut */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span
          style={{
            flex:       1,
            fontWeight: 600,
            fontSize:   14,
            color:      'var(--text-primary)',
            overflow:   'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {project.name}
        </span>

        {isArchived && (
          <span
            style={{
              fontSize:    10,
              padding:     '2px 6px',
              borderRadius: 4,
              background:  'var(--bg-elevated)',
              color:       'var(--text-muted)',
              fontFamily:  'monospace',
              letterSpacing: '0.05em',
              flexShrink:  0,
            }}
          >
            archivé
          </span>
        )}
      </div>

      {/* Description (tronquée à 2 lignes) */}
      {project.description && (
        <p
          style={{
            margin:     0,
            fontSize:   12,
            color:      'var(--text-secondary)',
            lineHeight: 1.5,
            display:    '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
            overflow:   'hidden',
          }}
        >
          {project.description}
        </p>
      )}

      {/* Méta : slug + dernière ouverture */}
      <div
        style={{
          display:    'flex',
          alignItems: 'center',
          gap:        8,
          fontSize:   11,
          color:      'var(--text-muted)',
          fontFamily: 'monospace',
        }}
      >
        <span style={{ opacity: 0.7 }}>{project.slug}</span>
        <span style={{ opacity: 0.4 }}>·</span>
        <span>{relativeTime(project.last_opened)}</span>
      </div>

      {/* Tags */}
      {project.tags?.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {project.tags.map(tag => (
            <span
              key={tag}
              style={{
                fontSize:    10,
                fontFamily:  'var(--font-mono)',
                color:       'var(--accent)',
                background:  'var(--accent-dim)',
                border:      '1px solid rgba(245,158,11,0.2)',
                borderRadius: 20,
                padding:     '1px 7px',
                whiteSpace:  'nowrap',
              }}
            >
              #{tag}
            </span>
          ))}
        </div>
      )}

      {/* Actions */}
      {!isArchived && (
        <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
          {/* Bouton principal : Reprendre */}
          <button
            onClick={() => onOpen(project.id)}
            style={{
              flex:          1,
              padding:       '6px 0',
              background:    'var(--accent-dim)',
              border:        '1px solid var(--b-acc)',
              borderRadius:  6,
              color:         'var(--accent)',
              fontSize:      12,
              fontWeight:    600,
              cursor:        'pointer',
              transition:    'background 0.15s',
            }}
            onMouseEnter={e => (e.currentTarget.style.background = 'rgba(245,158,11,0.22)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'var(--accent-dim)')}
          >
            ▶ Reprendre
          </button>

          {/* Bouton secondaire : Archiver */}
          <button
            onClick={() => {
              if (window.confirm(`Archiver "${project.name}" ?`)) onArchive(project.id);
            }}
            title="Archiver ce projet"
            style={{
              padding:    '6px 10px',
              background: 'transparent',
              border:     '1px solid var(--border)',
              borderRadius: 6,
              color:      'var(--text-muted)',
              fontSize:   12,
              cursor:     'pointer',
              transition: 'color 0.15s, border-color 0.15s',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.color        = 'var(--error)';
              e.currentTarget.style.borderColor  = 'var(--error)';
            }}
            onMouseLeave={e => {
              e.currentTarget.style.color        = 'var(--text-muted)';
              e.currentTarget.style.borderColor  = 'var(--border)';
            }}
          >
            ⊖
          </button>
        </div>
      )}
    </div>
  );
}
