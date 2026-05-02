# LCCA Voice — Pipeline voix local offline
*Version 1.0 — VOICE-11 — 2026-04-30*

Pipeline voix entièrement **local et offline** pour LCCA Desktop :
- **STT** (VoiceToLLCA) : parole → texte via faster-whisper small INT8
- **TTS** (LLCAToVoice) : réponse LCCA → synthèse vocale via Piper (ou Kokoro)

---

## Prérequis

| Composant | Version minimale | Remarque |
|---|---|---|
| Python | 3.11+ | Distinct du venv LCCA principal |
| Windows | 10 / 11 | Testé sur Lenovo P50 |
| GPU NVIDIA (optionnel) | CUDA 12 | Sans GPU : mode CPU (latence 3-5s STT) |
| Microphone | Tout périphérique Windows | USB recommandé pour moins de bruit |
| Espace disque | ~1 GB | Modèles STT + TTS |

> **Important :** Le pipeline Voice utilise un **venv Python séparé** (`Voice/venv/`).
> Ne pas installer dans le venv LCCA principal — risque de conflits de dépendances.

---

## Installation rapide

```bat
cd D:\LLMCodeAgent\Voice
install.bat
```

Choisir **[1] Installation complète**. Le script :
1. Crée `Voice/venv/` (venv isolé)
2. Installe les dépendances Python
3. Télécharge le modèle Whisper small (~460 MB)
4. Télécharge le modèle Piper fr_FR-mls-medium (~65 MB)

---

## Structure des fichiers

```
Voice/
├── install.bat              ← Script d'installation (ce fichier lance tout)
├── requirements.txt         ← Dépendances Python (venv Voice uniquement)
├── voice_config.toml        ← Configuration (ports, modèles, raccourcis)
│
├── voice_capture.py         ← VAD + buffer PCM (webrtcvad)
├── voice_transcriber.py     ← Wrapper faster-whisper (STT)
├── voice_service.py         ← Serveur WebSocket STT (port 8765)
│
├── tts_engine_piper.py      ← Wrapper Piper ONNX (TTS primaire)
├── tts_engine_kokoro.py     ← Wrapper Kokoro PyTorch (TTS optionnel)
├── tts_sentence.py          ← Découpe en phrases + streaming
├── tts_service.py           ← Serveur WebSocket TTS (port 8766)
│
├── voice_types.py           ← Dataclasses, enums, helpers VRAM
│
├── models/
│   ├── stt/                 ← Whisper small ctranslate2 (~460 MB)
│   └── tts/
│       ├── piper/           ← Fichiers .onnx Piper (~65 MB par voix)
│       └── kokoro/          ← Poids Kokoro-82M (optionnel, ~350 MB)
│
└── venv/                    ← Environnement Python isolé (créé par install.bat)
```

---

## Configuration

Éditez `Voice/voice_config.toml` pour personnaliser :

```toml
[stt]
model = "small"           # tiny (rapide) | small (défaut) | medium (précis)
language = "fr"           # fr | en
device = "auto"           # auto | cuda | cpu
compute_type = "int8"     # int8 = moins de VRAM, vitesse identique

[tts]
engine = "auto"           # auto | piper | kokoro
volume = 0.85             # Volume 0.0 - 1.0

[ui]
shortcut_push_to_talk = "Alt+V"
auto_submit = false       # true = envoi automatique après transcription
```

---

## Utilisation dans LCCA Desktop

1. Lancer LCCA Desktop normalement
2. Ouvrir **Paramètres → 🎤 Voix**
3. Activer **STT** (reconnaissance vocale) et/ou **TTS** (synthèse vocale)
4. Les services Python démarrent automatiquement

### Raccourcis

| Action | Raccourci |
|---|---|
| Activer/désactiver le micro | `Alt+V` |
| Couper la synthèse vocale en cours | `Alt+V` pendant la lecture |

### Indicateurs visuels

- **Anneau bleu animé** en haut à droite → microphone actif, écoute en cours
- **Onde verte pulsante** → synthèse vocale en cours
- **Texte grisé en italique** dans InputZone → transcription partielle (live)

---

## Moteurs TTS

### Piper (défaut — CPU, 0 VRAM)
Moteur léger basé sur ONNX Runtime. Latence < 50ms par phrase.
- Voix française : `fr_FR-mls-medium` (voix masculine, qualité correcte)
- Voix anglaise : `en_US-amy-medium`

### Kokoro (optionnel — meilleure qualité, ~500 MB VRAM)
Modèle neuronal 82M paramètres. Voix anglaise uniquement en V1.

Pour activer Kokoro :
1. Décommenter les lignes `kokoro` et `torch` dans `requirements.txt`
2. Relancer `install.bat → [2] Mise à jour des dépendances`
3. Régler `engine = "kokoro"` dans `voice_config.toml`

> Pré-requis Kokoro : `espeak-ng` installé système.
> Windows : `winget install espeak-ng`

---

## Budget VRAM (référence Lenovo P50 — Quadro M2000M 4 GB)

| Composant | VRAM (cuda) |
|---|---|
| Ollama qwen2.5-coder:3b | ~2.0 GB |
| Whisper small INT8 | ~0.5 GB |
| Piper TTS | 0 (CPU ONNX) |
| Kokoro TTS (optionnel) | ~0.5 GB |
| Marge système | ~1.0 GB |
| **Total avec Piper** | **~3.5 GB** ✅ |
| **Total avec Kokoro** | **~4.0 GB** ⚠️ limite |

Si la VRAM disponible est < 1.5 GB (Ollama déjà chargé) → bascule automatique en CPU.

---

## Dépannage

### Le micro ne s'active pas
- Vérifier que LCCA Desktop a les permissions microphone Windows
- Vérifier `Paramètres → Confidentialité → Microphone` dans Windows
- Tester dans `install.bat → [4] Vérification` (liste les micros détectés)

### Transcription en anglais alors que je parle français
- Régler `language = "fr"` dans `voice_config.toml`
- Le mode `auto` de Whisper est biaisé vers l'anglais sur les petits modèles

### Latence STT trop élevée (> 5s)
- Normal en mode CPU — le mode `auto` bascule sur CPU si VRAM insuffisante
- Essayer `model = "tiny"` pour réduire la latence (qualité légèrement dégradée)

### Port 8765 ou 8766 déjà occupé
- Changer les ports dans `voice_config.toml` :
  ```toml
  [stt]
  port = 8767
  [tts]
  port = 8768
  ```

### Service crash / badge rouge dans l'UI
- Redémarrer depuis **Paramètres → 🎤 Voix** (désactiver puis réactiver)
- Consulter les logs : LCCA Desktop → menu → Ouvrir les logs

---

## Isolation et sécurité

- `Voice/venv/` est **complètement séparé** du venv LCCA principal
- Les services Voice n'ont **aucun accès à `core/`** — isolation totale
- Communication Electron ↔ services : WebSocket local uniquement (ports 8765/8766)
- **0 envoi de données vers l'extérieur** — tout reste sur la machine locale
- Aucun nouveau tool MCP exposé

---

## Invariants techniques

- `VoiceCapture._vad_factory` : injectable pour tests sans webrtcvad
- `WhisperModel` : chargement lazy dans `VoiceTranscriber.load()`
- `_lock_instance = threading.Lock()` : attribut d'instance (pas de classe)
- `sounddevice.stop()` : appelé dans `finally` de toute lecture audio
- `VRAM_MIN_MB_FOR_CUDA = 1500` : seuil VRAM libre pour activer CUDA (STT + TTS)
- `auto_submit = false` invariant par défaut — l'utilisateur valide avant envoi

---

## Sprints implémentés

| Sprint | Fichier(s) | Statut |
|---|---|---|
| VOICE-00 | `voice_types.py` + `voice_config.toml` | ✅ DONE — 35 tests |
| VOICE-01 | `voice_capture.py` | ✅ DONE — 35 tests |
| VOICE-02 | `voice_transcriber.py` | ✅ DONE — 34 tests |
| VOICE-03 | `voice_service.py` | ✅ DONE — 31 tests |
| VOICE-04 | `tts_engine_piper.py` | ✅ DONE — 34 tests |
| VOICE-05 | `tts_engine_kokoro.py` | ✅ DONE — 37 tests |
| VOICE-06 | `tts_sentence.py` + `tts_service.py` | ✅ DONE — 56 tests |
| VOICE-07 | IPC Electron (main.ts + preload.ts) | ✅ DONE |
| VOICE-08 | `VoiceBar.tsx` + `VoiceIndicator.tsx` | ✅ DONE |
| VOICE-09 | `voiceStore.ts` + settings | ✅ DONE |
| VOICE-10 | `SettingsModal.tsx` toggles + `ChatPanel.tsx` Alt+V | ✅ DONE |
| VOICE-11 | `install.bat` + `requirements.txt` + `README_Voice.md` | ✅ DONE |
