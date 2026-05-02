import { useRef, useEffect, KeyboardEvent } from 'react';
import { Send, X } from 'lucide-react';
import { VoiceBar } from './VoiceBar';

interface InputZoneProps {
  onSend:      (text: string) => void;
  isStreaming: boolean;
  value:       string;
  onChange:    (v: string) => void;
  onCancel?:   () => void;  // UI-04 : bouton Annuler pendant streaming
  // VOICE-08 : props voice optionnelles (non injectées = VoiceBar masquee)
  voiceSttEnabled?:  boolean;
  voiceTtsEnabled?:  boolean;
  voiceListening?:   boolean;
  voiceSpeaking?:    boolean;
  onVoiceToggleStt?: () => void;
  onVoiceToggleTts?: () => void;
  onVoiceStopTts?:   () => void;
}

export function InputZone({
  onSend, isStreaming, value, onChange, onCancel,
  voiceSttEnabled, voiceTtsEnabled, voiceListening, voiceSpeaking,
  onVoiceToggleStt, onVoiceToggleTts, onVoiceStopTts,
}: InputZoneProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }, [value]);

  // Focus au montage
  useEffect(() => { textareaRef.current?.focus(); }, []);

  const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
    // Escape annule le streaming en cours
    if (e.key === 'Escape' && isStreaming && onCancel) {
      e.preventDefault();
      onCancel();
    }
  };

  const handleSend = () => {
    const trimmed = value.trim();
    if (!trimmed || isStreaming) return;
    onSend(trimmed);
    onChange('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  };

  const canSend = value.trim().length > 0 && !isStreaming;

  return (
    <div className="input-zone">
      <textarea
        ref={textareaRef}
        className="input-textarea"
        value={value}
        onChange={e => onChange(e.target.value)}
        onKeyDown={handleKey}
        placeholder={
          isStreaming
            ? 'Génération en cours… (Échap pour annuler)'
            : 'Tapez une commande… (Entrée pour envoyer, Maj+Entrée pour nouvelle ligne)'
        }
        rows={1}
        disabled={isStreaming}
        aria-label="Zone de saisie"
      />

      {/* VOICE-08 : boutons micro + TTS (visibles si au moins un service activé) */}
      {(voiceSttEnabled || voiceTtsEnabled) && (
        <VoiceBar
          sttEnabled={!!voiceSttEnabled}
          ttsEnabled={!!voiceTtsEnabled}
          isListening={!!voiceListening}
          isSpeaking={!!voiceSpeaking}
          isStreaming={isStreaming}
          onToggleStt={onVoiceToggleStt ?? (() => {})}
          onToggleTts={onVoiceToggleTts ?? (() => {})}
          onStopTts={onVoiceStopTts ?? (() => {})}
        />
      )}

      {/* Bouton Annuler — visible uniquement pendant le streaming */}
      {isStreaming && onCancel ? (
        <button
          className="input-cancel-btn"
          onClick={onCancel}
          aria-label="Annuler la génération"
          title="Annuler (Échap)"
        >
          <X size={18} />
        </button>
      ) : (
        <button
          className={`input-send-btn ${canSend ? 'active' : ''}`}
          onClick={handleSend}
          disabled={!canSend}
          aria-label="Envoyer"
        >
          <Send size={18} />
        </button>
      )}
    </div>
  );
}
