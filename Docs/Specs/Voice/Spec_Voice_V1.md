# LCCA — Spec Voice V1
# VoiceToLLCA & LLCAToVoice — Pipeline voix local offline
# Version : 1.0 — 2026-04-25
# Statut : DRAFT — en attente de validation

---

## 0. CONTEXTE ET OBJECTIF

LCCA est aujourd'hui 100% textuel : l'utilisateur tape dans l'InputZone, lit dans le ChatPanel.
Cette spec définit l'ajout d'un pipeline voix **entièrement local, offline, sans API cloud**, qui couvre :

- **VoiceToLLCA** (STT) : l'utilisateur parle → le texte arrive dans l'InputZone ou est soumis directement.
- **LLCAToVoice** (TTS) : la réponse de l'assistant → synthèse vocale lue en streaming dans le haut-parleur.

Contrainte matérielle de référence : **Lenovo P50 — Quadro M2000M 4 GB VRAM, 24 GB RAM, Windows 10/11, Python 3.11, CUDA disponible**.

---

## 1. PÉRIMÈTRE

### Inclus dans V1
- STT : transcription parole → texte, français et anglais, temps réel ou quasi-temps réel
- TTS : texte → parole streamée par phrases, voix française et anglaise
- Toggle UI : activer/désactiver STT et TTS indépendamment
- Mode "push-to-talk" (appui bouton ou raccourci clavier)
- Mode "auto-submit" : la phrase transcrite est soumise automatiquement au pipeline LCCA
- Indicateur visuel d'écoute et de synthèse dans la UI Electron
- Isolation complète dans un venv dédié (pas de pollution du venv LCCA principal)

### Hors périmètre V1
- Wake word ("Hey LCCA")
- Clonage de voix
- Multi-locutor / diarisation
- Traduction automatique
- Synchronisation labiale
- Support AMD GPU (ROCm) ou Apple Silicon

---

## 2. ARCHITECTURE GÉNÉRALE

```
[Microphone]
    │  PCM 16kHz mono
    ▼
[VoiceService — process séparé, port 8765 WebSocket]
    │
    ├─► [VAD] — détection silence/parole (webrtcvad)
    │       │
    │       ▼
    │   [faster-whisper small.fr / int8 CPU ou cuda]
    │       │  transcription par chunk (LocalAgreement ou SimulStream)
    │       ▼
    │   [Texte partiel / final]
    │
    └─► WebSocket JSON → [Electron main.ts]
                              │
                              ▼
                        [preload.ts] → [InputZone / auto-submit]
                              │
                              ▼ (réponse LCCA en streaming tokens)
                        [LLCAToVoice] — sentence splitter
                              │  phrase complète (~1-2 sec)
                              ▼
                        [TTSService — process séparé, port 8766]
                              │
                              ├─► [Piper TTS / fr_FR-mls-medium.onnx]
                              │        ou
                              │   [Kokoro-82M CPU/GPU]
                              │
                              ▼
                        [audio PCM streamé] → sounddevice playback
```

**Principe clé :** VoiceService et TTSService sont des **processus Python indépendants**, lancés par Electron via `child_process.spawn`, communiquant par WebSocket ou stdout JSON-RPC. Ils n'importent RIEN de `core/` — isolation totale.

---

## 3. COMPOSANT STT — VoiceToLLCA

### 3.1 Stack retenue

| Composant | Bibliothèque | Justification |
|---|---|---|
| Capture audio | `sounddevice` + `numpy` | Pas de dépendance ffmpeg, cross-platform |
| VAD | `webrtcvad` (Google) | Ultra-léger, CPU only, aggressivité 2/3 |
| ASR | `faster-whisper` (CTranslate2) | 4x plus rapide que openai-whisper, INT8 supporte Quadro M2000M |
| Streaming policy | LocalAgreement (WhisperLiveKit / SimulStream) | Latence ~1.5-3s, bonne précision FR |
| Transport | WebSocket (`websockets`) | Compatible Electron IPC pattern existant |

### 3.2 Modèle retenu

**`faster-whisper small` — compute_type="int8" — device="cuda" (fallback cpu)**

Justification :
- `tiny` : trop imprécis en français, hallucinations fréquentes
- `small` : ~460 MB VRAM, ~1-2s de latence sur Quadro M2000M, WER français acceptable (~12%)
- `medium` : ~1.5 GB VRAM, trop proche des 2 GB réservés pour Ollama
- `large-v3` : 3 GB VRAM — incompatible avec cohabitation Ollama 3b
- INT8 quantization : réduit la VRAM de ~40%, vitesse +3-6x vs PyTorch original

Budget VRAM estimé avec Ollama qwen2.5-coder:3b actif :
```
Ollama 3b    : ~2.0 GB
Whisper small INT8 : ~0.5 GB
Kokoro TTS   : ~0.5 GB
Marge système : ~1.0 GB
TOTAL        : ~4.0 GB  ← limite Quadro M2000M
```

⚠️ Si le budget VRAM est dépassé, STT bascule automatiquement en `device="cpu"` (latence ~3-5s, qualité identique).

### 3.3 Pipeline VAD + chunk

```python
# Pseudo-code — voice_service.py
CHUNK_MS = 30          # webrtcvad attend 10, 20 ou 30ms
SAMPLE_RATE = 16000
SILENCE_THRESHOLD = 800  # ms silence → fin d'utterance

class VoiceCapture:
    def __init__(self, aggressiveness=2):
        self.vad = webrtcvad.Vad(aggressiveness)
        self.buffer = []
        self.silence_ms = 0

    def process_chunk(self, pcm_chunk):
        is_speech = self.vad.is_speech(pcm_chunk, SAMPLE_RATE)
        if is_speech:
            self.buffer.append(pcm_chunk)
            self.silence_ms = 0
        elif self.buffer:
            self.silence_ms += CHUNK_MS
            if self.silence_ms >= SILENCE_THRESHOLD:
                utterance = b"".join(self.buffer)
                self.buffer.clear()
                return utterance  # → transcription
        return None
```

### 3.4 Format WebSocket (STT → Electron)

```json
// Transcription partielle (live feedback)
{"type": "partial", "text": "bonjour est-ce que tu peux", "confidence": 0.82}

// Transcription finale (utterance complète)
{"type": "final", "text": "Bonjour, est-ce que tu peux m'expliquer comment fonctionne le garbage collector ?", "confidence": 0.91, "duration_ms": 3200}

// Statut service
{"type": "status", "state": "listening" | "processing" | "idle" | "error", "msg": ""}
```

### 3.5 Modes opératoires

**Push-to-talk (défaut V1)**
- Raccourci : `Alt+V` (configurable dans settings)
- Bouton micro dans la UI (voir section UI)
- VAD actif uniquement pendant l'appui — silence automatique dès relâchement

**Mode continu (optionnel, activable dans settings)**
- VAD actif en permanence
- Utterances envoyées au fil de l'eau
- Risque de bruit de fond → aggressivité VAD = 3

**Auto-submit**
- Si activé : chaque transcription finale est soumise directement (équivalent Entrée)
- Si désactivé : le texte arrive dans l'InputZone, l'utilisateur peut l'éditer avant envoi

---

## 4. COMPOSANT TTS — LLCAToVoice

### 4.1 Stack retenue

| Composant | Bibliothèque | Justification |
|---|---|---|
| TTS engine primaire | `piper-tts` (ONNX, CPU) | Ultra-léger, voix FR native, 0 VRAM requis, < 50ms latence |
| TTS engine secondaire | `kokoro` (PyTorch, CPU ou cuda) | Meilleure qualité, ~2 GB VRAM, 82M params, Apache 2.0 |
| Lecture audio | `sounddevice` | Même dep que STT, playback non-bloquant |
| Sentence splitting | regex + tokenisation simple | Découpe aux `.`, `!`, `?`, `\n` |

### 4.2 Stratégie de choix du moteur

```
Si VRAM disponible > 1.5 GB après Ollama + Whisper :
    → Kokoro (voix plus naturelle)
Sinon :
    → Piper (CPU, ~5ms/phrase, voix correcte)
```

Ce choix est fait au démarrage du TTSService et ne change pas pendant la session.

### 4.3 Piper — modèles voix

**Français :**
- `fr_FR-mls-medium` (~65 MB) — voix masculine, qualité correcte
- `fr_FR-gilles-low` (~28 MB) — option légère fallback
- `fr_FR-upmc-medium` (~65 MB) — voix alternative

**Anglais :**
- `en_US-amy-medium` (~65 MB) — voix féminine, qualité standard

Piper est CPU-only via ONNX Runtime → **0 VRAM consommé**. Latence mesurée : < 50ms par phrase de 10 mots.

### 4.4 Kokoro — modèles voix

**Anglais natif (V1) :**
- `af_heart` — voix féminine américaine (défaut)
- `am_adam` — voix masculine américaine

**Français via phonémisation workaround :**
Kokoro n'a pas de voix FR native dans la version 82M actuelle. Option : pré-phonémiser avec `espeak-ng` + injecter en mode phonème (qualité dégradée). → Recommandation V1 : Piper pour FR, Kokoro pour EN.

### 4.5 Pipeline streaming TTS

```python
# Pseudo-code — tts_service.py

def stream_tts(text_generator, engine):
    """
    text_generator : itérateur de tokens Ollama (generate_stream)
    Découpe en phrases, synthétise et joue au fil de l'eau.
    """
    buffer = ""
    for token in text_generator:
        buffer += token
        sentences = split_sentences(buffer)
        if len(sentences) > 1:
            # Au moins une phrase complète disponible
            complete = sentences[:-1]
            buffer = sentences[-1]  # garde le fragment en cours
            for sentence in complete:
                audio = engine.synthesize(sentence.strip())
                sounddevice.play(audio, samplerate=engine.sample_rate, blocking=True)
    # Flush du buffer restant
    if buffer.strip():
        audio = engine.synthesize(buffer.strip())
        sounddevice.play(audio, samplerate=engine.sample_rate, blocking=True)

def split_sentences(text):
    """Découpe aux fins de phrase, garde les fragments."""
    import re
    return re.split(r'(?<=[.!?])\s+', text)
```

**Latence end-to-end cible :**
- Premier token Ollama → première phrase complète (~8-15 tokens) → synthèse TTS → son : **< 1.5s**
- Avec Piper CPU : ~50ms synthesis → latence dominée par la génération Ollama

### 4.6 Interruption et contrôle

- **Interruption** : si l'utilisateur appuie sur le bouton Micro ou `Alt+V` pendant la synthèse → `sounddevice.stop()` immédiat + vider la queue de phrases en attente
- **Pause** : bouton pause UI → `sounddevice.stop()` sans vider la queue
- **Volume** : slider dans settings → `sounddevice` amplitude multiplier

---

## 5. PROCESSUS ET ISOLATION

### 5.1 Processus VoiceService

```
D:\LLMCodeAgent\Voice\
├── voice_service.py       Serveur WebSocket STT (port 8765)
├── voice_capture.py       VAD + buffer PCM
├── voice_transcriber.py   faster-whisper wrapper
├── voice_types.py         Dataclasses VoiceMessage, VoiceConfig
├── tts_service.py         Serveur WebSocket TTS (port 8766)
├── tts_engine_piper.py    Wrapper Piper ONNX
├── tts_engine_kokoro.py   Wrapper Kokoro PyTorch
├── tts_sentence.py        split_sentences(), flush logic
├── voice_config.toml      Configuration (modèles, ports, modes)
├── models/
│   ├── stt/               faster-whisper small ctranslate2
│   └── tts/               fichiers .onnx Piper + kokoro weights
├── venv/                  venv Python isolé (PAS le venv LCCA)
├── requirements.txt       faster-whisper webrtcvad sounddevice websockets piper-tts kokoro
└── install.bat            Setup automatique
```

### 5.2 Cycle de vie (géré par Electron)

```typescript
// main.ts — gestion des processus voice
let voiceProcess: ChildProcess | null = null;
let ttsProcess: ChildProcess | null = null;

ipcMain.handle("voice:start", async () => {
  voiceProcess = spawn(VOICE_PYTHON, [VOICE_SCRIPT], { stdio: "pipe" });
  // ... connect WebSocket to ws://localhost:8765
});

ipcMain.handle("voice:stop", async () => {
  voiceProcess?.kill("SIGTERM");
  voiceProcess = null;
});

ipcMain.handle("tts:speak", async (_, text: string) => {
  // Envoie texte au TTSService via WebSocket ou stdin JSON-RPC
});

ipcMain.handle("tts:stop", async () => {
  // Envoie {"type": "stop"} au TTSService
});
```

### 5.3 Règles d'isolation

- `Voice/venv/` distinct de `D:\LLMCodeAgent\venv\` — 0 dépendance croisée
- `voice_service.py` n'importe JAMAIS depuis `core/`
- Communication Electron ↔ VoiceService : **WebSocket uniquement** (pas de module Python partagé)
- Logs VoiceService : `stderr` uniquement (JSON-RPC sur stdout)
- Le MCP Server LCCA ne sait pas que Voice existe — 0 nouveau tool MCP en V1

---

## 6. INTERFACE UTILISATEUR (Electron/React)

### 6.1 Composants nouveaux

**`VoiceBar.tsx`** — barre d'outils vocaux (positionnée dans InputZone, à droite)
```
[ 🎤 ] [ 🔊 ] [ ⏸ ]
  STT    TTS   Pause
```

- Bouton `🎤` : toggle STT push-to-talk / continu — rouge pulsant = écoute active
- Bouton `🔊` : toggle TTS on/off — indique si la synthèse est active
- Bouton `⏸` : pause/reprendre la synthèse en cours (visible uniquement pendant TTS actif)

**`VoiceIndicator.tsx`** — overlay visuel discret
- Anneau animé bleu = écoute
- Onde verte pulsante = synthèse en cours
- Positionné en haut à droite du ChatPanel (position fixed, z-index élevé)

**`VoiceSettings.tsx`** — section dans SettingsModal
- Choix du microphone (liste `sounddevice.query_devices()`)
- Modèle STT : tiny / small / medium (avec indication VRAM)
- Moteur TTS : Piper / Kokoro / Auto
- Voix TTS : liste dépendante du moteur
- Raccourci push-to-talk : input clavier reconfigurable
- Toggle auto-submit
- Slider volume TTS

### 6.2 Stores

**`voiceStore.ts`** — état vocal global
```typescript
interface VoiceState {
  sttEnabled: boolean;
  ttsEnabled: boolean;
  isListening: boolean;
  isSpeaking: boolean;
  partialTranscript: string;
  voiceServiceReady: boolean;
  ttsServiceReady: boolean;
  selectedMic: string;
  ttsEngine: "piper" | "kokoro" | "auto";
  ttsVoice: string;
  ttsVolume: number; // 0.0 - 1.0
  pushToTalk: boolean;
  autoSubmit: boolean;
}
```

**Polling** : `voice:getStatus` toutes les 5s pour vérifier santé des processus.

### 6.3 Intégration ChatPanel / InputZone

- Quand `partialTranscript` change → injecter dans InputZone (texte grisé, non éditable)
- Sur `final` → remplacer par texte éditable ; si `autoSubmit` → déclencher submit
- Pendant TTS actif → désactiver le bouton submit principal (évite double envoi)
- Tokens streaming Ollama → envoyés au TTSService phrase par phrase via `tts:streamChunk`

---

## 7. CONFIGURATION — voice_config.toml

```toml
[stt]
enabled = true
mode = "push_to_talk"       # push_to_talk | continuous
model = "small"             # tiny | small | medium
language = "fr"             # fr | en | auto
device = "auto"             # auto | cuda | cpu
compute_type = "int8"       # int8 | float16 | float32
port = 8765
vad_aggressiveness = 2      # 0-3

[tts]
enabled = true
engine = "auto"             # auto | piper | kokoro
port = 8766
volume = 0.85

[tts.piper]
model_fr = "fr_FR-mls-medium"
model_en = "en_US-amy-medium"
models_dir = "models/tts/piper"

[tts.kokoro]
lang = "a"                  # a=american-en, b=british-en
voice = "af_heart"
models_dir = "models/tts/kokoro"

[ui]
shortcut_push_to_talk = "Alt+V"
auto_submit = false
show_partial_transcript = true
```

---

## 8. INSTALLATION

### 8.1 Prérequis système

- Python 3.11 (compatible venv LCCA)
- `espeak-ng` installé système (requis par Kokoro et Piper pour phonémisation)
  - Windows : `winget install espeak-ng` ou téléchargement depuis GitHub release
- NVIDIA CUDA 12 + cuDNN 9 (si compute_type=float16 ou cuda device)
  - Note : `faster-whisper` avec `int8` + `device=cuda` nécessite cuDNN 9
  - Purfview's whisper-standalone-win fournit les DLL CUDA pour Windows sans installation système

### 8.2 install.bat (skeleton)

```bat
@echo off
echo [VOICE] Installation du pipeline voix LCCA...

set VOICE_DIR=%~dp0
set VENV=%VOICE_DIR%venv

python -m venv "%VENV%"
call "%VENV%\Scripts\activate.bat"

pip install --upgrade pip
pip install faster-whisper webrtcvad-wheels sounddevice websockets numpy
pip install piper-tts
pip install kokoro>=0.9.4

echo [STT] Telechargement du modele Whisper small...
python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8', download_root='models/stt')"

echo [TTS] Telechargement du modele Piper fr_FR-mls-medium...
python -c "from piper.voice import PiperVoice; PiperVoice.load('fr_FR-mls-medium', download_dir='models/tts/piper')"

echo [OK] Installation terminee.
pause
```

### 8.3 Taille des modèles estimée

| Modèle | Taille disque | VRAM (inference) |
|---|---|---|
| faster-whisper small INT8 | ~460 MB | ~500 MB (cuda) / 0 (cpu) |
| Piper fr_FR-mls-medium | ~65 MB | 0 (CPU ONNX) |
| Piper en_US-amy-medium | ~65 MB | 0 (CPU ONNX) |
| Kokoro-82M | ~350 MB | ~500 MB (cuda) / 0 (cpu) |
| **TOTAL** | **~940 MB** | **~1 GB max (cuda)** |

---

## 9. SPRINTS PROPOSÉS

| Sprint | Fichier(s) | Contenu | Tests |
|---|---|---|---|
| VOICE-00 | `Voice/voice_types.py` + `voice_config.toml` | Dataclasses + config loader | 8 tests |
| VOICE-01 | `Voice/voice_capture.py` | VAD + buffer PCM + webrtcvad | 10 tests |
| VOICE-02 | `Voice/voice_transcriber.py` | faster-whisper wrapper, device auto-detect, INT8 | 10 tests |
| VOICE-03 | `Voice/voice_service.py` | Serveur WebSocket STT, protocole JSON | 12 tests |
| VOICE-04 | `Voice/tts_engine_piper.py` | Piper ONNX wrapper, lazy load, synthesize() | 8 tests |
| VOICE-05 | `Voice/tts_engine_kokoro.py` | Kokoro wrapper, fallback CPU | 8 tests |
| VOICE-06 | `Voice/tts_sentence.py` + `tts_service.py` | Sentence splitter + serveur WebSocket TTS | 10 tests |
| VOICE-07 | `electron/` — 4 fichiers IPC | main.ts + preload.ts + mcp-timeouts.ts handlers | 0 tests (UI) |
| VOICE-08 | `ui/src/components/VoiceBar.tsx` + `VoiceIndicator.tsx` | Composants UI visuels | 0 tests (UI) |
| VOICE-09 | `ui/src/stores/voiceStore.ts` + `VoiceSettings.tsx` | Store + settings | 0 tests (UI) |
| VOICE-10 | Intégration ChatPanel + InputZone + stream TTS | Pipeline complet end-to-end | 5 tests intég. |
| VOICE-11 | `Voice/install.bat` + README_Voice.md | Packaging, docs | 0 |

**Total estimé : ~71 tests unitaires + 5 tests intégration**

---

## 10. CONTRAINTES ET INVARIANTS

### Performance
- STT latence cible : < 2s entre fin de parole et texte dans InputZone (mode cuda)
- TTS latence cible : < 1.5s entre premier token Ollama et premier son
- CPU fallback accepté : STT < 5s, TTS < 200ms/phrase (Piper CPU)

### Mémoire
- Budget VRAM total Voice (STT + TTS) : ≤ 1.0 GB — sinon bascule CPU automatique
- Détection VRAM libre : `torch.cuda.mem_get_info()` au démarrage VoiceService
- Si VRAM libre < 1.5 GB → forcer device="cpu" pour STT ET TTS

### Fiabilité
- Si VoiceService crash → Electron reçoit `close` sur WebSocket → badge rouge dans UI → relance manuelle
- TTSService : si synthèse lève une exception → logger stderr + continuer sans son (silencieux)
- `sounddevice.stop()` appelé dans `finally` de toute function de lecture
- WebSocket reconnection : retry 3 fois / 2s avant de déclarer le service mort

### Isolation
- `Voice/venv/` : **ne jamais `pip install` dans le venv LCCA principal**
- `voice_service.py` : pas d'import `core.*`
- 0 nouveau tool MCP exposé en V1
- `auto_push = false` invariant maintenu (rien lié à git dans Voice)

### Tests
- `pytest.skip()` si sounddevice sans périphérique audio (CI sans micro)
- Mocks `sounddevice.play` dans tous les tests TTS (pas de son en CI)
- Mocks `webrtcvad.Vad.is_speech` pour les tests VAD
- faster-whisper mocké via `patch("Voice.voice_transcriber.WhisperModel")`

---

## 11. RISQUES ET MITIGATIONS

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| VRAM insuffisante avec Ollama actif | Haute | Moyen | Détection auto + bascule CPU |
| cuDNN 9 absent sur Windows (faster-whisper cuda) | Moyenne | Moyen | Purfview standalone DLL ou fallback CPU |
| webrtcvad-wheels non compatible Python 3.11 Win64 | Faible | Haut | Fallback : SileroVAD (torch) ou energy-based VAD |
| Kokoro espeak-ng absent (Windows) | Moyenne | Faible | Piper prend le relais en TTS |
| Latence STT inacceptable en CPU | Haute | Moyen | Mode push-to-talk uniquement — l'utilisateur valide avant envoi |
| Piper fr_FR voix robotique | Faible | Faible | Proposer 3 voix FR au choix dans settings |
| WebSocket port 8765/8766 occupé | Très faible | Faible | Port configurable dans voice_config.toml |

---

## 12. QUESTIONS OUVERTES (pour validation)

1. **Langue détection auto vs fixe** : veux-tu que Whisper détecte automatiquement la langue (FR/EN) ou que tu fixes la langue dans les settings ? L'auto-détection de Whisper est biaisée vers l'anglais sur les petits modèles.

2. **Push-to-talk obligatoire en V1 ?** Le mode continu avec VAD introduit des faux positifs (bruit de fond, voix du TTS entendue par le micro). Recommandation : push-to-talk par défaut, continu opt-in.

3. **TTS pendant la génération ou après ?** Streamer phrase par phrase pendant la génération (latence plus faible, meilleure expérience) ou attendre la réponse complète (plus simple, V1 plus robuste) ?

4. **Raccourci clavier global ou local ?** `Alt+V` global (fonctionne même si la fenêtre n'est pas focus) nécessite `iohook` ou équivalent Electron — complexité additionnelle. Recommandation V1 : local uniquement.

5. **Voix TTS en français** : Piper `fr_FR-mls-medium` est la voix FR la plus naturelle disponible en local. Kokoro n'a pas de voix FR native (82M). Valider ce choix ou préférer attendre une version Kokoro-FR ?

6. **venv séparé ou même venv LCCA ?** Les dépendances Voice (torch, faster-whisper, sounddevice) peuvent créer des conflits avec les dépendances LCCA. Un venv séparé est plus propre mais ajoute un overhead d'installation. À confirmer.

---

## 13. RÉFÉRENCES

- faster-whisper : https://github.com/SYSTRAN/faster-whisper (CTranslate2, Apache 2.0)
- WhisperLiveKit : https://github.com/QuentinFuxa/WhisperLiveKit (LocalAgreement + SimulStream)
- Piper TTS : https://github.com/rhasspy/piper (MIT, ONNX, voix FR disponibles)
- Kokoro-82M : https://huggingface.co/hexgrad/Kokoro-82M (Apache 2.0, 82M params)
- webrtcvad : https://github.com/wiseman/py-webrtcvad (VAD Google, MIT)
- RealtimeTTS : https://pypi.org/project/realtimetts/ (wrapper multi-engine, référence patterns)
- Benchmark Whisper FR : github.com/openai/whisper/discussions/530
- Purfview standalone Windows DLL : github.com/Purfview/whisper-standalone-win

---

*Spec rédigée le 2026-04-25 — en attente validation AI + utilisateur avant sprint VOICE-00.*
