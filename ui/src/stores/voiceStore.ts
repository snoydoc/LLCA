// ui/src/stores/voiceStore.ts
// VOICE-09 — Store Zustand : état voix + WebSocket STT/TTS + IPC Electron
//
// Architecture :
//   - voice:start  IPC  → lance voice_service.py  (STT WebSocket port 8765)
//   - tts:start    IPC  → lance tts_service.py    (TTS WebSocket port 8766)
//   - WebSocket 8765 reçoit les transcriptions { type, text, is_final }
//   - WebSocket 8766 reçoit les statuts TTS     { type } (speaking_start / speaking_end)
//
// Invariants :
//   - 0 dépendance à core/ (isolation Voice totale)
//   - Les WebSockets ne sont ouverts que si les services IPC sont running
//   - onTranscript : callback injecté par ChatPanel pour alimenter InputZone
//   - auto_submit = false → toujours pré-remplir l'InputZone, jamais soumettre directement

import { create } from 'zustand';

// ── Types messages WebSocket ────────────────────────────────────────────────
interface SttMessage {
  type: 'partial' | 'final' | 'error';
  text: string;
}

interface TtsMessage {
  type: 'speaking_start' | 'speaking_end' | 'error';
}

// ── State + actions ─────────────────────────────────────────────────────────
interface VoiceState {
  /** STT activé dans les settings */
  sttEnabled:    boolean;
  /** TTS activé dans les settings */
  ttsEnabled:    boolean;
  /** Micro en écoute active */
  isListening:   boolean;
  /** Synthèse TTS en cours */
  isSpeaking:    boolean;
  /** Transcription partielle (affichée en italique dans VoiceIndicator) */
  partialText:   string;
  /** Service STT running côté IPC (voice_service.py) */
  sttRunning:    boolean;
  /** Service TTS running côté IPC (tts_service.py) */
  ttsRunning:    boolean;
  /** Erreur dernière en date */
  lastError:     string | null;

  // ── Setters publics ──────────────────────────────────────────────────────
  setSttEnabled: (v: boolean) => void;
  setTtsEnabled: (v: boolean) => void;

  // ── Lifecycle services ───────────────────────────────────────────────────
  /** Démarre STT+TTS IPC et ouvre les WebSockets. callback = reçoit le texte final. */
  startServices:  (onTranscript: (text: string) => void) => Promise<void>;
  /** Arrête proprement les deux services. */
  stopServices:   () => Promise<void>;

  // ── Push-to-talk ─────────────────────────────────────────────────────────
  /** Toggle micro : envoie {type:"start_listen"} / {type:"stop_listen"} au STT WS. */
  toggleListening: () => void;

  // ── TTS ──────────────────────────────────────────────────────────────────
  /** Envoie une phrase au TTS WebSocket pour synthèse. */
  speakText:   (text: string) => void;
  /** Coupe la synthèse en cours (stop_speak). */
  stopSpeaking: () => void;

  // ── Interne ──────────────────────────────────────────────────────────────
  _sttWs:            WebSocket | null;
  _ttsWs:            WebSocket | null;
  _onTranscript:     ((text: string) => void) | null;
}

// ── Singletons WebSocket (hors du store pour éviter la sérialisation Zustand)
let _sttWs: WebSocket | null = null;
let _ttsWs: WebSocket | null = null;
let _onTranscriptCb: ((text: string) => void) | null = null;

// Délai de reconnexion WS
const WS_STT_URL = 'ws://127.0.0.1:8765';
const WS_TTS_URL = 'ws://127.0.0.1:8766';
// Délai d'attente après IPC start avant tentative WebSocket (ms)
const WS_CONNECT_DELAY_MS = 1800;

// ── Helpers internes ────────────────────────────────────────────────────────
function ipcVoice() {
  return (window as unknown as { lcca: { voice: { start: () => Promise<unknown>; stop: () => Promise<unknown>; status: () => Promise<{ running: boolean }> }; tts: { start: () => Promise<unknown>; stop: () => Promise<unknown>; status: () => Promise<{ running: boolean }> } } }).lcca;
}

function openSttWs(
  onPartial: (text: string) => void,
  onFinal:   (text: string) => void,
  onError:   (msg: string)  => void,
  onClose:   () => void,
): WebSocket {
  const ws = new WebSocket(WS_STT_URL);
  ws.onmessage = (ev) => {
    try {
      const msg: SttMessage = JSON.parse(ev.data as string);
      if (msg.type === 'partial') onPartial(msg.text);
      else if (msg.type === 'final') { onPartial(''); onFinal(msg.text); }
      else if (msg.type === 'error') onError(msg.text);
    } catch { /* ignore */ }
  };
  ws.onerror = () => onError('WebSocket STT erreur');
  ws.onclose = onClose;
  return ws;
}

function openTtsWs(
  onStart: () => void,
  onEnd:   () => void,
  onError: (msg: string) => void,
  onClose: () => void,
): WebSocket {
  const ws = new WebSocket(WS_TTS_URL);
  ws.onmessage = (ev) => {
    try {
      const msg: TtsMessage = JSON.parse(ev.data as string);
      if (msg.type === 'speaking_start') onStart();
      else if (msg.type === 'speaking_end') onEnd();
      else if (msg.type === 'error') onError('TTS erreur service');
    } catch { /* ignore */ }
  };
  ws.onerror = () => onError('WebSocket TTS erreur');
  ws.onclose = onClose;
  return ws;
}

// ── Store ────────────────────────────────────────────────────────────────────
export const useVoiceStore = create<VoiceState>()((set, get) => ({
  sttEnabled:    false,
  ttsEnabled:    false,
  isListening:   false,
  isSpeaking:    false,
  partialText:   '',
  sttRunning:    false,
  ttsRunning:    false,
  lastError:     null,

  // Champs internes (non sérialisés — valeurs réelles dans les singletons module-level)
  _sttWs:        null,
  _ttsWs:        null,
  _onTranscript: null,

  setSttEnabled: (v) => set({ sttEnabled: v }),
  setTtsEnabled: (v) => set({ ttsEnabled: v }),

  // ── Lifecycle ─────────────────────────────────────────────────────────────
  startServices: async (onTranscript) => {
    _onTranscriptCb = onTranscript;
    const { sttEnabled, ttsEnabled } = get();
    const lcca = ipcVoice();

    // Lancer le service STT si activé
    if (sttEnabled && !_sttWs) {
      try {
        await lcca.voice.start();
        set({ sttRunning: true });
        // Attendre que le process Python démarre son serveur WebSocket
        await new Promise(r => setTimeout(r, WS_CONNECT_DELAY_MS));
        _sttWs = openSttWs(
          (text)  => set({ partialText: text }),
          (text)  => { _onTranscriptCb?.(text); },
          (msg)   => set({ lastError: msg }),
          ()      => { _sttWs = null; set({ sttRunning: false, isListening: false }); },
        );
      } catch (err) {
        set({ lastError: `STT start: ${String(err)}` });
      }
    }

    // Lancer le service TTS si activé
    if (ttsEnabled && !_ttsWs) {
      try {
        await lcca.tts.start();
        set({ ttsRunning: true });
        await new Promise(r => setTimeout(r, WS_CONNECT_DELAY_MS));
        _ttsWs = openTtsWs(
          ()    => set({ isSpeaking: true }),
          ()    => set({ isSpeaking: false }),
          (msg) => set({ lastError: msg }),
          ()    => { _ttsWs = null; set({ ttsRunning: false, isSpeaking: false }); },
        );
      } catch (err) {
        set({ lastError: `TTS start: ${String(err)}` });
      }
    }
  },

  stopServices: async () => {
    const lcca = ipcVoice();
    try {
      if (_sttWs) { _sttWs.close(); _sttWs = null; }
      await lcca.voice.stop();
      set({ sttRunning: false, isListening: false, partialText: '' });
    } catch { /* ignore */ }
    try {
      if (_ttsWs) { _ttsWs.close(); _ttsWs = null; }
      await lcca.tts.stop();
      set({ ttsRunning: false, isSpeaking: false });
    } catch { /* ignore */ }
  },

  // ── Push-to-talk ──────────────────────────────────────────────────────────
  toggleListening: () => {
    const { isListening } = get();
    if (!_sttWs || _sttWs.readyState !== WebSocket.OPEN) return;
    if (isListening) {
      _sttWs.send(JSON.stringify({ type: 'stop_listen' }));
      set({ isListening: false, partialText: '' });
    } else {
      _sttWs.send(JSON.stringify({ type: 'start_listen' }));
      set({ isListening: true });
    }
  },

  // ── TTS ───────────────────────────────────────────────────────────────────
  speakText: (text) => {
    if (!_ttsWs || _ttsWs.readyState !== WebSocket.OPEN) return;
    _ttsWs.send(JSON.stringify({ type: 'speak', text }));
  },

  stopSpeaking: () => {
    if (!_ttsWs || _ttsWs.readyState !== WebSocket.OPEN) return;
    _ttsWs.send(JSON.stringify({ type: 'stop_speak' }));
    set({ isSpeaking: false });
  },
}));
