// ui/src/components/VoiceBar.tsx
// VOICE-08 -- Barre d'outils vocaux (STT + TTS) intégrée dans InputZone
// Règle : 0 couleur hardcodée — tout via tokens themes.css
// Règle UI : toute nouvelle méthode IPC = 3 fichiers (main.ts + preload.ts + composant) ✅ VOICE-07

import { Mic, MicOff, Volume2, VolumeX, Square } from 'lucide-react';

interface VoiceBarProps {
  /** STT activé dans les settings */
  sttEnabled:    boolean;
  /** TTS activé dans les settings */
  ttsEnabled:    boolean;
  /** Écoute micro active */
  isListening:   boolean;
  /** Synthèse vocale en cours */
  isSpeaking:    boolean;
  /** Streaming Ollama en cours (désactive submit) */
  isStreaming:   boolean;
  /** Callback toggle STT push-to-talk */
  onToggleStt:   () => void;
  /** Callback toggle TTS on/off */
  onToggleTts:   () => void;
  /** Callback stop synthèse en cours */
  onStopTts:     () => void;
}

export function VoiceBar({
  sttEnabled,
  ttsEnabled,
  isListening,
  isSpeaking,
  isStreaming,
  onToggleStt,
  onToggleTts,
  onStopTts,
}: VoiceBarProps) {
  // Pendant le streaming Ollama, le bouton micro est grisé
  const micDisabled = isStreaming;

  return (
    <div className="voice-bar" aria-label="Contrôles voix">
      {/* Bouton micro — STT push-to-talk */}
      {sttEnabled && (
        <button
          className={`voice-btn voice-btn-mic ${isListening ? 'voice-btn--active' : ''}`}
          onClick={onToggleStt}
          disabled={micDisabled}
          aria-label={isListening ? 'Arrêter l\'écoute' : 'Activer le micro (Alt+V)'}
          title={isListening ? 'Arrêter l\'écoute' : 'Micro (Alt+V)'}
        >
          {isListening ? <MicOff size={15} /> : <Mic size={15} />}
          {isListening && <span className="voice-btn-pulse" aria-hidden="true" />}
        </button>
      )}

      {/* Bouton TTS — toggle on/off */}
      {ttsEnabled && !isSpeaking && (
        <button
          className="voice-btn voice-btn-tts"
          onClick={onToggleTts}
          aria-label="Activer/désactiver la synthèse vocale"
          title="Synthèse vocale"
        >
          <Volume2 size={15} />
        </button>
      )}

      {/* Bouton stop TTS — visible uniquement pendant la synthèse */}
      {isSpeaking && (
        <button
          className="voice-btn voice-btn-stop voice-btn--speaking"
          onClick={onStopTts}
          aria-label="Arrêter la synthèse vocale"
          title="Arrêter le TTS"
        >
          <Square size={13} />
        </button>
      )}
    </div>
  );
}
