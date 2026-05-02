// ProjectWelcomeScreen.tsx — PROJ-05 + PROJ-UI-01
// Écran d'accueil Mode Projets : liste + création + bloc Bonjour + InspirationPanel

import { useEffect, useState } from 'react';
import { useProjectStore, ProjectMeta } from '../stores/projectStore';
import { ProjectCard } from './ProjectCard';
import { ProjectCreationModal } from './ProjectCreationModal';
import { InspirationPanel, IdeaCard } from './InspirationPanel';

interface ProjectWelcomeScreenProps {
  /** Appelé quand un projet est ouvert — permet au parent de basculer l'UI */
  onProjectOpen: (project: ProjectMeta) => void;
}

export function ProjectWelcomeScreen({ onProjectOpen }: ProjectWelcomeScreenProps) {
  const {
    projects, loading, error,
    load, openProject, createProject, archiveProject,
  } = useProjectStore();

  const [showModal,        setShowModal]        = useState(false);
  const [creating,         setCreating]         = useState(false);
  const [createErr,        setCreateErr]        = useState<string | null>(null);
  const [showInspPanel,    setShowInspPanel]    = useState(false);
  const [userName,         setUserName]         = useState<string | null>(null);
  const [ideaName,         setIdeaName]         = useState('');
  const [ideaDescription,  setIdeaDescription]  = useState('');
  const [ideaTags,         setIdeaTags]         = useState<string[]>([]);

  // Charger la liste au montage + lire le contexte utilisateur
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const lcca = (window as unknown as { lcca: { userContext: { read: () => Promise<{ ok: boolean; data: Record<string, unknown> | null }> } } }).lcca;
    lcca.userContext.read().then(res => {
      if (res?.ok && res.data) {
        const identity = res.data['identity'] as Record<string, string> | undefined;
        const name = identity?.['name'];
        if (name) setUserName(name);
      }
    }).catch(() => { /* mode dégradé silencieux */ });
  }, []);

  const handleOpen = async (id: string) => {
    await openProject(id);
    const project = useProjectStore.getState().projects.find(p => p.id === id);
    if (project) onProjectOpen(project);
  };

  const handleCreate = async (name: string, description: string, tags: string[] = [], storageMode: string = 'shared') => {
    setCreating(true);
    setCreateErr(null);
    const created = await createProject(name, description, tags, storageMode);
    setCreating(false);
    if (created) {
      setShowModal(false);
      // Ouvrir immédiatement le projet fraîchement créé
      await handleOpen(created.id);
    } else {
      setCreateErr(useProjectStore.getState().error ?? 'Erreur inconnue');
    }
  };

  const handleArchive = async (id: string) => {
    await archiveProject(id);
  };

  const handleCreateFromIdea = async (idea: IdeaCard) => {
    setIdeaName(idea.title);
    setIdeaDescription(idea.description);
    setIdeaTags(idea.tags ?? []);
    setShowInspPanel(false);
    setShowModal(true);
  };

  const activeProjects   = projects.filter(p => p.status === 'active');
  const archivedProjects = projects.filter(p => p.status === 'archived');

  return (
    <div
      style={{
        display:        'flex',
        flexDirection:  'column',
        alignItems:     'center',
        padding:        '40px 24px',
        height:         '100%',
        overflowY:      'auto',
        gap:            32,
        position:       'relative',
      }}
    >
      {/* ── Bloc Bonjour + bouton Inspiration (PROJ-UI-01) ── */}
      <div className="proj-welcome-greeting">
        <div className="proj-welcome-greeting-text">
          <span className="proj-welcome-greeting-hello">
            Bonjour{userName ? <>, <em>{userName}</em></> : null} 👋
          </span>
          <p className="proj-welcome-greeting-sub">
            {userName
              ? `Bienvenue, ${userName}. Ouvre un projet ou génère de nouvelles idées.`
              : 'Ouvre un projet ou génère de nouvelles idées avec l'IA.'}
          </p>
        </div>
        <button
          className="proj-welcome-inspiration-btn"
          onClick={() => setShowInspPanel(true)}
        >
          💡 Générer des idées
        </button>
      </div>

      {/* ── En-tête ── */}
      <div style={{ textAlign: 'center', maxWidth: 540 }}>
        {/* Icône décorative */}
        <div
          style={{
            width:        56,
            height:       56,
            borderRadius: '50%',
            background:   'var(--accent-dim)',
            border:       '1px solid var(--b-acc)',
            display:      'flex',
            alignItems:   'center',
            justifyContent: 'center',
            margin:       '0 auto 16px',
            fontSize:     24,
          }}
        >
          ◈
        </div>

        <h2
          style={{
            margin:     0,
            fontSize:   22,
            fontWeight: 700,
            color:      'var(--text-primary)',
          }}
        >
          Vos projets
        </h2>
        <p style={{ margin: '8px 0 0', color: 'var(--text-secondary)', fontSize: 13 }}>
          Chaque projet isole son contexte, ses specs et son historique.
        </p>
      </div>

      {/* ── Zone principale ── */}
      <div style={{ width: '100%', maxWidth: 640 }}>

        {/* Bouton Nouveau projet */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
          <button
            onClick={() => setShowModal(true)}
            style={{
              display:     'flex',
              alignItems:  'center',
              gap:         6,
              padding:     '8px 16px',
              background:  'var(--accent)',
              border:      'none',
              borderRadius: 7,
              color:       'var(--text-inverse)',
              fontSize:    13,
              fontWeight:  700,
              cursor:      'pointer',
              boxShadow:   'var(--glow-accent)',
              transition:  'opacity 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.opacity = '0.88'; }}
            onMouseLeave={e => { e.currentTarget.style.opacity = '1'; }}
          >
            <span>＋</span> Nouveau projet
          </button>
        </div>

        {/* ── État chargement ── */}
        {loading && (
          <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '40px 0', fontSize: 13 }}>
            Chargement…
          </div>
        )}

        {/* ── Erreur IPC ── */}
        {error && !loading && (
          <div
            style={{
              padding:     '10px 14px',
              background:  'var(--error-dim)',
              border:      '1px solid var(--error)',
              borderRadius: 6,
              color:       'var(--error)',
              fontSize:    12,
              marginBottom: 16,
            }}
          >
            {error}
          </div>
        )}

        {/* ── Projets actifs ── */}
        {!loading && activeProjects.length === 0 && (
          <div
            style={{
              textAlign:    'center',
              padding:      '48px 24px',
              border:       '1px dashed var(--border)',
              borderRadius: 10,
              color:        'var(--text-muted)',
              fontSize:     13,
            }}
          >
            <div style={{ fontSize: 28, marginBottom: 12, opacity: 0.4 }}>◫</div>
            Aucun projet actif.{' '}
            <button
              onClick={() => setShowModal(true)}
              style={{
                background:  'none',
                border:      'none',
                color:       'var(--accent)',
                cursor:      'pointer',
                fontWeight:  600,
                padding:     0,
                fontSize:    13,
              }}
            >
              Créer le premier
            </button>
          </div>
        )}

        {activeProjects.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {activeProjects.map(p => (
              <ProjectCard
                key={p.id}
                project={p}
                onOpen={handleOpen}
                onArchive={handleArchive}
              />
            ))}
          </div>
        )}

        {/* ── Projets archivés (pliés par défaut) ── */}
        {archivedProjects.length > 0 && (
          <details style={{ marginTop: 28 }}>
            <summary
              style={{
                fontSize:  12,
                color:     'var(--text-muted)',
                cursor:    'pointer',
                userSelect: 'none',
                padding:   '6px 0',
                listStyle: 'none',
                display:   'flex',
                alignItems: 'center',
                gap:        6,
              }}
            >
              <span>▸</span>
              {archivedProjects.length} projet{archivedProjects.length > 1 ? 's' : ''} archivé{archivedProjects.length > 1 ? 's' : ''}
            </summary>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 10 }}>
              {archivedProjects.map(p => (
                <ProjectCard
                  key={p.id}
                  project={p}
                  onOpen={handleOpen}
                  onArchive={handleArchive}
                />
              ))}
            </div>
          </details>
        )}
      </div>

      {/* ── Modal création ── */}
      {showModal && (
        <ProjectCreationModal
          onConfirm={handleCreate}
          onClose={() => { setShowModal(false); setCreateErr(null); setIdeaName(''); setIdeaDescription(''); setIdeaTags([]); }}
          loading={creating}
          initialName={ideaName}
          initialDescription={ideaDescription}
          initialTags={ideaTags}
          onOpenInspiration={() => { setShowModal(false); setShowInspPanel(true); }}
        />
      )}

      {/* ── InspirationPanel ── */}
      {showInspPanel && (
        <InspirationPanel
          onClose={() => setShowInspPanel(false)}
          onCreateFromIdea={handleCreateFromIdea}
        />
      )}

      {/* Erreur de création (hors modal) */}
      {createErr && !showModal && (
        <div
          style={{
            position:    'fixed',
            bottom:      24,
            left:        '50%',
            transform:   'translateX(-50%)',
            background:  'var(--error-dim)',
            border:      '1px solid var(--error)',
            color:       'var(--error)',
            padding:     '8px 16px',
            borderRadius: 6,
            fontSize:    12,
            zIndex:      1100,
          }}
        >
          {createErr}
        </div>
      )}
    </div>
  );
}
