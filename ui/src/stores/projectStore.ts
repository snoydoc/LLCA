// projectStore.ts — PROJ-05 : état des projets LCCA
// Zustand store : liste projets + projet actif + actions IPC

import { create } from 'zustand';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface ProjectMeta {
  id:           string;
  name:         string;
  slug:         string;
  description:  string;
  status:       'active' | 'archived';
  created_at:   string;    // ISO8601
  last_opened:  string;    // ISO8601
  storage_mode: string;    // 'shared' | 'isolated'
  tags:         string[];  // PROJ-UI-05
}

// ─── Interface IPC ────────────────────────────────────────────────────────────
// Accès via window.lcca.projects.* (exposé dans preload.ts par PROJ-05)

declare global {
  interface Window {
    lcca: {
      projects: {
        list:    ()                                        => Promise<ProjectMeta[]>;
        open:    (id: string)                             => Promise<{ ok: boolean; error?: string }>;
        create:  (name: string, description: string, tags?: string[], storageMode?: string) => Promise<{ ok: boolean; project?: ProjectMeta; error?: string }>;
        archive: (id: string)                             => Promise<{ ok: boolean; error?: string }>;
      };
      // autres namespaces existants — non répétés ici pour éviter les conflits
      [key: string]: unknown;
    };
  }
}

// ─── Store ────────────────────────────────────────────────────────────────────

interface ProjectStore {
  projects:      ProjectMeta[];
  activeProject: ProjectMeta | null;
  loading:       boolean;
  error:         string | null;

  /** Charger la liste des projets actifs depuis le main process */
  load:          () => Promise<void>;

  /** Ouvrir un projet (le marquer comme actif + mettre à jour last_opened) */
  openProject:   (id: string) => Promise<void>;

  /** Créer un nouveau projet et recharger la liste */
  createProject: (name: string, description: string, tags?: string[], storageMode?: string) => Promise<ProjectMeta | null>;

  /** Archiver un projet et recharger la liste */
  archiveProject: (id: string) => Promise<void>;

  /** Réinitialiser le projet actif (retour à l'écran d'accueil) */
  closeProject:  () => void;
}

export const useProjectStore = create<ProjectStore>((set, get) => ({
  projects:      [],
  activeProject: null,
  loading:       false,
  error:         null,

  load: async () => {
    set({ loading: true, error: null });
    try {
      const list = await window.lcca.projects.list();
      set({ projects: list, loading: false });
    } catch (err) {
      set({ error: String(err), loading: false });
    }
  },

  openProject: async (id: string) => {
    set({ loading: true, error: null });
    try {
      const result = await window.lcca.projects.open(id);
      if (!result.ok) {
        set({ error: result.error ?? 'Erreur ouverture projet', loading: false });
        return;
      }
      // Retrouver le meta dans la liste chargée
      const meta = get().projects.find(p => p.id === id) ?? null;
      set({ activeProject: meta, loading: false });
    } catch (err) {
      set({ error: String(err), loading: false });
    }
  },

  createProject: async (name: string, description: string, tags: string[] = [], storageMode: string = 'shared') => {
    set({ loading: true, error: null });
    try {
      const result = await window.lcca.projects.create(name, description, tags, storageMode);
      if (!result.ok || !result.project) {
        set({ error: result.error ?? 'Erreur création projet', loading: false });
        return null;
      }
      await get().load();
      return result.project;
    } catch (err) {
      set({ error: String(err), loading: false });
      return null;
    }
  },

  archiveProject: async (id: string) => {
    set({ loading: true, error: null });
    try {
      const result = await window.lcca.projects.archive(id);
      if (!result.ok) {
        set({ error: result.error ?? 'Erreur archivage', loading: false });
        return;
      }
      // Si le projet archivé était actif, le fermer
      if (get().activeProject?.id === id) {
        set({ activeProject: null });
      }
      await get().load();
    } catch (err) {
      set({ error: String(err), loading: false });
    }
  },

  closeProject: () => {
    set({ activeProject: null });
  },
}));
