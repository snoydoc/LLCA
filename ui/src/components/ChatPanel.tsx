// ChatPanel.tsx — Sprint UI-08 : activeTool injecté dans le message assistant
// REFACTO-UI-01 : WelcomeScreen, DisconnectedBanner → composants séparés
//                 callWithTimeout → hooks/useMcpCall.ts
import { useRef, useEffect, useState, useCallback } from 'react';
import { useChatStore }       from '../stores/chatStore';
import { useSettingsStore }   from '../stores/settingsStore';
import { useContextStore }    from '../stores/contextStore';
import { useStreaming }       from '../hooks/useStreaming';
import { callWithTimeout }    from '../hooks/useMcpCall';
import { MessageBubble }      from './MessageBubble';
import { InputZone }          from './InputZone';
import { WelcomeScreen }      from './WelcomeScreen';
import { DisconnectedBanner } from './DisconnectedBanner';
import { SpecDetailModal }    from './SpecDetailModal';
import { McpError }           from '../types/mcp';
import { VoiceIndicator }     from './VoiceIndicator';
import { useVoiceStore }      from '../stores/voiceStore';
import { routeIntent }        from '../utils/router';
import { formatMcpResponse }  from '../utils/mcpFormatter';
import { extractTxBadge, extractSpecBadge } from '../utils/extractors';

// ── ChatPanel ────────────────────────────────────────────────────────────────
export function ChatPanel() {
  const {
    messages, streaming,
    appendMessage, appendStreamToken, finalizeStream,
    createSession, activeSessionId,
  } = useChatStore();

  const { streamingDelay } = useSettingsStore();
  const { mcpStatus, addTxRecord, setModifiedFiles, refreshSpecs, tpsData } = useContextStore();
  const { stream, cancel } = useStreaming(streamingDelay);

  const [inputValue,  setInputValue]  = useState('');
  const [isStreaming, setIsStreaming]  = useState(false);
  const [specModalId, setSpecModalId] = useState<string | null>(null);

  // VOICE-09 : état voix (STT + TTS)
  const {
    sttEnabled, ttsEnabled,
    isListening, isSpeaking, partialText,
    startServices, stopServices,
    toggleListening, speakText, stopSpeaking,
    setSttEnabled, setTtsEnabled,
  } = useVoiceStore();

  // Démarrer les services voice au montage si au moins un est activé
  useEffect(() => {
    if (!sttEnabled && !ttsEnabled) return;
    // onTranscript : texte final STT → injecter dans l'InputZone
    startServices((text) => setInputValue(prev => prev ? prev + ' ' + text : text));
    return () => {
      stopServices().catch(() => {});
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sttEnabled, ttsEnabled]);

  // VOICE-10 : raccourci clavier Alt+V → toggle écoute STT
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.altKey && e.key === 'v' && sttEnabled) {
        e.preventDefault();
        toggleListening();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [sttEnabled, toggleListening]);
  // BUGFIX : stocker le badge complet (avec body_md) pour le passer au modal
  const [specModalBadge, setSpecModalBadge] = useState<import('../types/chat').SpecBadge | undefined>(undefined);

  const openSpecModal = (specId: string, badge?: import('../types/chat').SpecBadge) => {
    setSpecModalId(specId);
    setSpecModalBadge(badge);
  };

  useEffect(() => {
    const handler = (e: Event) => {
      const { specId } = (e as CustomEvent<{ specId: string }>).detail;
      if (specId) openSpecModal(specId); // badge inconnu depuis event externe
    };
    window.addEventListener('lcca:open-spec', handler);
    return () => window.removeEventListener('lcca:open-spec', handler);
  }, []);

  const abortRef        = useRef<{ cancelled: boolean }>({ cancelled: false });
  const streamingMsgRef = useRef<string | null>(null);
  const bottomRef       = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!activeSessionId) createSession();
  }, [activeSessionId, createSession]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, streaming?.content]);

  const handleRetry = async () => {
    try { await (window as any).lcca?.restartServer?.(); } catch { /* ignore */ }
  };

  const handleCancel = useCallback(() => {
    abortRef.current.cancelled = true;
    cancel();
    setIsStreaming(false);
  }, [cancel]);

  // ── Handler envoi ──────────────────────────────────────────────────────────
  const handleSend = async (text: string) => {
    if (!text.trim() || isStreaming) return;

    abortRef.current = { cancelled: false };

    appendMessage({
      id: crypto.randomUUID(), role: 'user',
      content: text, createdAt: new Date().toISOString(),
    });
    setIsStreaming(true);

    // UI-08 : router AVANT de créer le message → activeTool disponible immédiatement
    const intent         = routeIntent(text);
    const assistantMsgId = crypto.randomUUID();

    appendMessage({
      id: assistantMsgId, role: 'assistant',
      content: '', createdAt: new Date().toISOString(),
      isStreaming: true,
      activeTool: intent.tool,   // ← UI-08 : affiché dans StreamingIndicator
      modelName:  tpsData?.model ?? undefined,  // ← UI-MODEL-01 : modèle actif
    });

    try {
      const isLlmChat = intent.tool === 'llm_chat';
      streamingMsgRef.current = assistantMsgId;

      const rawResult = await (async () => {
        const lcca = (window as any).lcca;
        if (!lcca?.mcpCall) throw new McpError(-32000, 'McpServer non connecté');
        if (isLlmChat) {
          // Construire l'historique conversationnel à partir des messages existants
          // (hors le message user qu'on vient d'ajouter et le message assistant vide)
          const history = messages
            .filter(m => (m.role === 'user' || m.role === 'assistant') && m.content.trim() !== '')
            .slice(-20)  // max 20 tours pour éviter context overflow
            .map(m => ({ role: m.role as 'user' | 'assistant', content: m.content }));
          intent.args = { ...intent.args, history };
        }
        return callWithTimeout(intent.tool, intent.args as Record<string, unknown>, abortRef.current);
      })();

      if (abortRef.current.cancelled) return;

      const responseText = formatMcpResponse(intent.tool, rawResult);
      const txBadge      = extractTxBadge(responseText);
      const specBadge    = extractSpecBadge(responseText);

      // BUGFIX [object Object] : propager body_md/violations/version depuis rawResult dans le badge
      // body_md est forcé en string (Python peut retourner un dict de sections)
      const rawBody = (rawResult as any)?.body_md;
      const safeBodyMd = typeof rawBody === 'string'
        ? rawBody
        : rawBody != null ? JSON.stringify(rawBody, null, 2) : undefined;
      const enrichedSpecBadge = specBadge && intent.tool === 'generate_spec'
        ? {
            ...specBadge,
            body_md:    safeBodyMd,
            violations: Array.isArray((rawResult as any)?.violations) ? (rawResult as any).violations : [],
            version:    typeof (rawResult as any)?.version === 'string' ? (rawResult as any).version : undefined,
          }
        : specBadge;

      await stream(responseText, assistantMsgId, appendStreamToken);
      if (!abortRef.current.cancelled) {
        // BUGFIX : finalizeStream avec badge enrichi contenant body_md
        finalizeStream(assistantMsgId, enrichedSpecBadge ?? undefined);
        // VOICE-09 : TTS de la réponse finale si activé (ne parle pas pendant streaming)
        if (ttsEnabled && responseText.trim()) {
          speakText(responseText);
        }
      }

      if (txBadge)          { addTxRecord(txBadge); setModifiedFiles(txBadge.files); }
      if (enrichedSpecBadge) refreshSpecs().catch(() => {});

    } catch (err) {
      cancel();
      if (!abortRef.current.cancelled) {
        finalizeStream(assistantMsgId);
        const raw = err as any;
        const msg = [
          `⚠ ${raw?.message ?? String(err)}`,
          raw?.code !== undefined ? `code: ${raw.code}` : null,
          raw?.stack ? `\n${raw.stack}` : null,
        ].filter(Boolean).join(' | ');
        appendMessage({
          id: crypto.randomUUID(), role: 'system',
          content: msg, createdAt: new Date().toISOString(),
        });
      }
    } finally {
      streamingMsgRef.current = null;
      setIsStreaming(false);
    }
  };

  const handleTxRollback = async (txId: string) => {
    appendMessage({
      id: crypto.randomUUID(), role: 'system',
      content: `Rollback ${txId} — fonctionnalité disponible avec MCP connecté.`,
      createdAt: new Date().toISOString(),
    });
  };

  // ── Rendu messages ─────────────────────────────────────────────────────────
  const renderedMessages = messages.map(msg => {
    // BUGFIX Thinking indicator :
    // isCurrentlyStreaming = vrai dès que le message est marqué isStreaming (pré-streaming,
    // avant le premier token) OU pendant le streaming de tokens.
    // Avant ce fix, la condition n'était vraie qu'après le premier token → le
    // StreamingIndicator mode "full" n'était jamais rendu pendant la phase d'attente MCP.
    const isCurrentlyStreaming =
      isStreaming && msg.role === 'assistant' &&
      (msg.isStreaming === true || streaming?.msgId === msg.id);
    const displayContent = isCurrentlyStreaming
      ? (streaming?.content ?? msg.content)
      : msg.content;

    const txBadge   = !isCurrentlyStreaming && msg.role === 'assistant'
      ? (msg.txBadge   ?? extractTxBadge(msg.content)   ?? undefined)
      : msg.txBadge;
    const specBadge = !isCurrentlyStreaming && msg.role === 'assistant'
      ? (msg.specBadge ?? extractSpecBadge(msg.content) ?? undefined)
      : msg.specBadge;

    return (
      <MessageBubble
        key={msg.id}
        message={{ ...msg, content: displayContent, txBadge, specBadge }}
        isStreaming={isCurrentlyStreaming}
        onSpecView={(sid) => openSpecModal(sid, specBadge ?? msg.specBadge)}
        onTxRollback={handleTxRollback}
        onQuote={(text) => setInputValue(prev => prev ? prev + '\n' + text : text)}
      />
    );
  });

  return (
    <main className="chat-panel" aria-label="Zone de chat">
      {mcpStatus !== 'connected' && mcpStatus !== 'connecting' && (
        <DisconnectedBanner onRetry={handleRetry} />
      )}

      <div
        className="chat-message-list"
        role="log"
        aria-live="polite"
        aria-label="Messages"
      >
        {messages.length === 0 ? <WelcomeScreen /> : renderedMessages}
        <div ref={bottomRef} />
      </div>

      <div className="chat-input-wrapper">
        <InputZone
          value={inputValue}
          onChange={setInputValue}
          onSend={handleSend}
          isStreaming={isStreaming}
          onCancel={isStreaming ? handleCancel : undefined}
          voiceSttEnabled={sttEnabled}
          voiceTtsEnabled={ttsEnabled}
          voiceListening={isListening}
          voiceSpeaking={isSpeaking}
          onVoiceToggleStt={toggleListening}
          onVoiceToggleTts={() => setTtsEnabled(!ttsEnabled)}
          onVoiceStopTts={stopSpeaking}
        />
        <p className="chat-input-hint">
          Entrée pour envoyer · Maj+Entrée pour saut de ligne · Ctrl+K pour la palette
        </p>
      </div>

      {specModalId && (
        <SpecDetailModal
          specId={specModalId}
          badge={specModalBadge}
          onClose={() => { setSpecModalId(null); setSpecModalBadge(undefined); }}
        />
      )}

      {/* VOICE-08/09 : overlay visuel écoute + TTS — props réelles VOICE-09 */}
      <VoiceIndicator
        isListening={isListening}
        isSpeaking={isSpeaking}
        partialText={partialText}
      />
    </main>
  );
}
