// ui/src/components/VoiceIndicator.tsx
// VOICE-08 -- Overlay visuel discret : anneau écoute + onde TTS
// Position : fixed, coin supérieur droit du ChatPanel (z-index élevé)
// Règle : 0 couleur hardcodée — tout via tokens themes.css

interface VoiceIndicatorProps {
  /** Écoute micro active → anneau bleu animé */
  isListening: boolean;
  /** Synthèse TTS en cours → onde verte pulsante */
  isSpeaking:  boolean;
  /** Transcription partielle en cours de saisie */
  partialText?: string;
}

export function VoiceIndicator({ isListening, isSpeaking, partialText }: VoiceIndicatorProps) {
  if (!isListening && !isSpeaking) return null;

  return (
    <div className="voice-indicator" aria-live="polite" aria-atomic="true">
      {/* Anneau écoute — bleu pulsant */}
      {isListening && (
        <div
          className="voice-indicator-ring voice-indicator-ring--listening"
          aria-label="Écoute active"
          title="Écoute active"
        >
          <span className="voice-indicator-icon">🎤</span>
          <span className="voice-indicator-ring-wave" aria-hidden="true" />
        </div>
      )}

      {/* Onde TTS — verte pulsante */}
      {isSpeaking && (
        <div
          className="voice-indicator-ring voice-indicator-ring--speaking"
          aria-label="Synthèse vocale en cours"
          title="Synthèse en cours"
        >
          <span className="voice-indicator-icon">🔊</span>
          <span className="voice-indicator-ring-wave" aria-hidden="true" />
        </div>
      )}

      {/* Transcription partielle — texte grisé en italique */}
      {isListening && partialText && (
        <p className="voice-indicator-partial">{partialText}</p>
      )}
    </div>
  );
}
