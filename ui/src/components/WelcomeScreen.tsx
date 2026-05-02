// WelcomeScreen.tsx — Écran d'accueil ChatPanel (UI-05-ENH + PROJ-05)
// PROJ-05 : si des projets existent → branching vers ProjectWelcomeScreen
import { useEffect, useState } from 'react';
import { useSettingsStore } from '../stores/settingsStore';
import { ProjectWelcomeScreen } from './ProjectWelcomeScreen';
import { ProjectMeta } from '../stores/projectStore';

const CHIPS = [
  { prefix: '@', label: 'spec', hint: 'Générer une spec' },
  { prefix: '@', label: 'eval', hint: 'Évaluer du code' },
  { prefix: '@', label: 'web',  hint: 'Recherche internet' },
  { prefix: '@', label: 'file', hint: 'Ouvrir un fichier' },
  { prefix: null, label: 'Ctrl+K', hint: 'Palette de commandes' },
];

interface WelcomeScreenProps {
  /** Appelé quand un projet est ouvert depuis ProjectWelcomeScreen */
  onProjectOpen?: (project: ProjectMeta) => void;
}

export function WelcomeScreen({ onProjectOpen }: WelcomeScreenProps = {}) {
  const { theme } = useSettingsStore();

  // PROJ-05 : détection projets existants
  const [hasProjects, setHasProjects] = useState<boolean | null>(null); // null = en cours de vérification

  useEffect(() => {
    (async () => {
      try {
        const list = await (window as unknown as { lcca: { projects: { list: () => Promise<unknown[]> } } })
          .lcca.projects.list();
        setHasProjects(Array.isArray(list) && list.length > 0);
      } catch {
        // IPC non disponible (ex: test standalone) → afficher l'écran classique
        setHasProjects(false);
      }
    })();
  }, []);

  // En cours de détection : rien (évite le flash)
  if (hasProjects === null) return null;

  // ── Branching : mode projets ──────────────────────────────────────────────
  if (hasProjects) {
    return (
      <ProjectWelcomeScreen
        onProjectOpen={onProjectOpen ?? (() => {})}
      />
    );
  }

  // ── Écran classique (pas de projets encore) ───────────────────────────────
  return (
    <div className="chat-welcome" style={{ position: 'relative', overflow: 'hidden' }}>
      {/* Grille de fond atmosphérique */}
      <div className="chat-welcome-grid" aria-hidden="true" />
      {/* Glow ambre central */}
      <div className="chat-welcome-glow" aria-hidden="true" />

      {/* Gem animée en remplacement de l'image */}
      <div
        className="chat-welcome-gem"
        aria-hidden="true"
        style={{ position: 'relative', zIndex: 1 }}
      />

      {/* Titre */}
      <div style={{ textAlign: 'center', position: 'relative', zIndex: 1 }}>
        <h2 className="chat-welcome-title">
          Bonjour,{' '}
          <strong>Adham</strong>{' '}
          est prêt.
        </h2>
        <p className="chat-welcome-subtitle" style={{ marginTop: 8 }}>
          Agent de codage local V8 — 100% offline · qwen2.5-coder:7b
        </p>
      </div>

      {/* Chips de commandes */}
      <div className="chat-welcome-hints" style={{ position: 'relative', zIndex: 1 }}>
        {CHIPS.map(chip => (
          <span
            key={chip.label}
            className="hint-chip"
            title={chip.hint}
            style={{ cursor: 'default' }}
          >
            {chip.prefix && (
              <span className="hint-chip-prefix">{chip.prefix}</span>
            )}
            {chip.label}
          </span>
        ))}
      </div>

      {/* Badge version MCP */}
      <div className="chat-welcome-version" style={{ position: 'relative', zIndex: 1 }}>
        <div className="chat-welcome-version-dot" aria-hidden="true" />
        MCP v8.0.0-alpha · 12 outils actifs
      </div>
    </div>
  );
}
