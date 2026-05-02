import { create } from 'zustand';
import type { Session, Message, TxBadge, SpecBadge } from '../types/chat';

// ─── Streaming partiel (bulle en cours) ──────────────────────────────────────
interface StreamingState {
  msgId:   string;
  content: string;
}

interface ChatState {
  sessions:        Session[];
  activeSessionId: string | null;
  messages:        Message[];
  streaming:       StreamingState | null;

  // Actions sessions
  createSession:     ()                                  => string;
  setActiveSession:  (id: string)                        => void;
  deleteSession:     (id: string)                        => void;
  renameSession:     (id: string, title: string)         => void;

  // Actions messages
  appendMessage:     (msg: Message)                      => void;
  appendStreamToken: (msgId: string, token: string)      => void;
  finalizeStream:    (msgId: string, specBadge?: SpecBadge) => void;  // BUGFIX : badge avec body_md
  clearMessages:     ()                                  => void;

  // Persistence
  persistSessions:   ()                                  => Promise<void>;
  loadSessions:      ()                                  => Promise<void>;
  persistMessages:   ()                                  => Promise<void>;
  loadMessages:      (sessionId: string)                 => Promise<void>;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
let _persistTimer: ReturnType<typeof setTimeout> | null = null;
function debouncedPersist(fn: () => Promise<void>, ms = 500) {
  if (_persistTimer) clearTimeout(_persistTimer);
  _persistTimer = setTimeout(() => fn().catch(console.error), ms);
}

function autoTitle(messages: Message[]): string {
  const first = messages.find(m => m.role === 'user');
  if (!first) return 'Nouvelle session';
  return first.content.slice(0, 30) + (first.content.length > 30 ? '…' : '');
}

// ─── Store ────────────────────────────────────────────────────────────────────
export const useChatStore = create<ChatState>()((set, get) => ({
  sessions:        [],
  activeSessionId: null,
  messages:        [],
  streaming:       null,

  createSession: () => {
    const id  = crypto.randomUUID();
    const now = new Date().toISOString();
    const session: Session = { id, title: 'Nouvelle session', createdAt: now, updatedAt: now };
    set(s => ({ sessions: [session, ...s.sessions], activeSessionId: id, messages: [] }));
    debouncedPersist(() => get().persistSessions());
    return id;
  },

  setActiveSession: (id) => {
    set({ activeSessionId: id, messages: [], streaming: null });
    get().loadMessages(id).catch(console.error);
  },

  deleteSession: (id) => {
    set(s => {
      const sessions = s.sessions.filter(s => s.id !== id);
      const activeSessionId = s.activeSessionId === id
        ? (sessions[0]?.id ?? null)
        : s.activeSessionId;
      return { sessions, activeSessionId, messages: activeSessionId ? s.messages : [] };
    });
    debouncedPersist(() => get().persistSessions());
  },

  renameSession: (id, title) => {
    set(s => ({
      sessions: s.sessions.map(s =>
        s.id === id ? { ...s, title, updatedAt: new Date().toISOString() } : s
      ),
    }));
    debouncedPersist(() => get().persistSessions());
  },

  appendMessage: (msg) => {
    set(s => {
      const messages = [...s.messages, msg];
      // Auto-titre de la session si c'est le premier message user
      const sessions = s.sessions.map(sess =>
        sess.id === s.activeSessionId
          ? { ...sess, title: autoTitle(messages), updatedAt: new Date().toISOString() }
          : sess
      );
      return { messages, sessions };
    });
    debouncedPersist(() => get().persistMessages());
    debouncedPersist(() => get().persistSessions());
  },

  appendStreamToken: (msgId, token) => {
    set(s => {
      if (!s.streaming || s.streaming.msgId !== msgId) {
        return { streaming: { msgId, content: token } };
      }
      return { streaming: { msgId, content: s.streaming.content + token } };
    });
  },

  finalizeStream: (msgId, specBadge) => {
    const { streaming } = get();
    if (!streaming || streaming.msgId !== msgId) return;
    const finalContent = streaming.content;
    set(s => ({
      messages: s.messages.map(m =>
        m.id === msgId
          ? { ...m, content: finalContent, isStreaming: false,
              // BUGFIX : attacher le badge enrichi (avec body_md) au message finalisé
              ...(specBadge ? { specBadge } : {}) }
          : m
      ),
      streaming: null,
    }));
    debouncedPersist(() => get().persistMessages());
  },

  clearMessages: () => {
    set({ messages: [], streaming: null });
  },

  // ── Persistence ─────────────────────────────────────────────────────────────
  persistSessions: async () => {
    const { sessions } = get();
    await (window as any).lcca.saveSessions(sessions);
  },

  loadSessions: async () => {
    const data = await (window as any).lcca.loadSessions();
    const sessions: Session[] = data?.sessions ?? [];
    set({ sessions, activeSessionId: sessions[0]?.id ?? null });
    if (sessions[0]) {
      await get().loadMessages(sessions[0].id);
    }
  },

  persistMessages: async () => {
    const { activeSessionId, messages } = get();
    if (!activeSessionId) return;
    await (window as any).lcca.saveSessionMessages(activeSessionId, messages);
  },

  loadMessages: async (sessionId) => {
    const data = await (window as any).lcca.loadSessionMessages(sessionId);
    const messages: Message[] = data?.messages ?? [];
    set({ messages, streaming: null });
  },
}));
