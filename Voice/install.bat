@echo off
setlocal EnableDelayedExpansion
chcp 65001 > nul

:: ============================================================================
:: Voice/install.bat — Installation du pipeline voix LCCA (VOICE-11)
:: Cree le venv Voice/venv/, installe les dependances, telecharge les modeles.
:: Doit etre execute depuis le dossier Voice\ (ou double-clic).
:: ============================================================================

set VOICE_DIR=%~dp0
set VENV=%VOICE_DIR%venv
set PYTHON_CMD=python

:: ── Verification Python ────────────────────────────────────────────────────
echo.
echo [VOICE] Verification de Python...
%PYTHON_CMD% --version > nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python introuvable dans le PATH.
    echo         Installez Python 3.11+ depuis https://www.python.org
    goto :fin_erreur
)

for /f "tokens=2" %%v in ('%PYTHON_CMD% --version 2^>^&1') do set PY_VER=%%v
echo [OK] Python %PY_VER% detecte.

:: ── Verification version minimale (3.11) ──────────────────────────────────
%PYTHON_CMD% -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" > nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python 3.11+ requis. Version detectee : %PY_VER%
    goto :fin_erreur
)

:: ── Menu principal ─────────────────────────────────────────────────────────
echo.
echo ============================================================
echo   LCCA Voice — Installation du pipeline voix local
echo ============================================================
echo.
echo  [1] Installation complete (venv + dependances + modeles)
echo  [2] Mise a jour des dependances uniquement
echo  [3] Telecharger les modeles uniquement
echo  [4] Verification de l'installation
echo  [5] Quitter
echo.
set /p CHOIX="Votre choix [1-5] : "

if "%CHOIX%"=="1" goto :install_complet
if "%CHOIX%"=="2" goto :install_deps
if "%CHOIX%"=="3" goto :download_modeles
if "%CHOIX%"=="4" goto :verification
if "%CHOIX%"=="5" goto :fin_ok
echo [ERREUR] Choix invalide.
goto :fin_erreur

:: ── Installation complete ─────────────────────────────────────────────────
:install_complet
echo.
echo [VOICE] Creation du venv isole Voice\venv\...
if exist "%VENV%" (
    echo [INFO] Le venv existe deja — suppression et recreation.
    rmdir /s /q "%VENV%"
)
%PYTHON_CMD% -m venv "%VENV%"
if errorlevel 1 (
    echo [ERREUR] Impossible de creer le venv.
    goto :fin_erreur
)
echo [OK] Venv cree.

:install_deps
echo.
echo [VOICE] Activation du venv...
call "%VENV%\Scripts\activate.bat"

echo [VOICE] Mise a jour de pip...
python -m pip install --upgrade pip --quiet

echo [VOICE] Installation des dependances (requirements.txt)...
pip install -r "%VOICE_DIR%requirements.txt"
if errorlevel 1 (
    echo [ERREUR] Une dependance n'a pas pu s'installer.
    echo         Verifiez la connexion internet et relancez.
    goto :fin_erreur
)
echo [OK] Dependances installees.

if "%CHOIX%"=="2" goto :fin_ok

:download_modeles
echo.
echo [VOICE] Creation des dossiers modeles...
if not exist "%VOICE_DIR%models\stt" mkdir "%VOICE_DIR%models\stt"
if not exist "%VOICE_DIR%models\tts\piper" mkdir "%VOICE_DIR%models\tts\piper"
if not exist "%VOICE_DIR%models\tts\kokoro" mkdir "%VOICE_DIR%models\tts\kokoro"

:: Active le venv si pas encore actif (cas choix=3)
if "%CHOIX%"=="3" call "%VENV%\Scripts\activate.bat"

echo.
echo [STT] Telechargement du modele Whisper small (INT8, ~460 MB)...
echo       Destination : %VOICE_DIR%models\stt\
python -c "from faster_whisper import WhisperModel; print('[STT] Chargement/verification...'); m = WhisperModel('small', device='cpu', compute_type='int8', download_root=r'%VOICE_DIR%models\stt'); print('[OK] Modele STT pret.')"
if errorlevel 1 (
    echo [WARN] Echec du telechargement STT. Verifiez la connexion.
    echo        Le modele sera telecharge automatiquement au premier lancement.
)

echo.
echo [TTS] Telechargement du modele Piper fr_FR-mls-medium (~65 MB)...
echo       Destination : %VOICE_DIR%models\tts\piper\
python -c "
import sys, os
sys.path.insert(0, r'%VOICE_DIR%')
os.makedirs(r'%VOICE_DIR%models\tts\piper', exist_ok=True)
try:
    from piper.download import ensure_voice_exists, get_voices
    voices = get_voices(r'%VOICE_DIR%models\tts\piper', update_voices=True)
    ensure_voice_exists('fr_FR-mls-medium', [r'%VOICE_DIR%models\tts\piper'], r'%VOICE_DIR%models\tts\piper', voices)
    print('[OK] Modele TTS piper fr_FR-mls-medium pret.')
except Exception as e:
    print(f'[WARN] Telechargement Piper: {e}')
    print('       Le modele sera telecharge au premier lancement.')
"

echo.
echo [INFO] Modele Kokoro non installe par defaut (optionnel, VRAM requis).
echo        Pour l'activer : decommenter kokoro dans requirements.txt et relancer [2].

:: ── Verification ─────────────────────────────────────────────────────────
:verification
echo.
echo [VOICE] Verification de l'installation...
call "%VENV%\Scripts\activate.bat" 2> nul

echo.
echo --- Imports Python ---
python -c "import faster_whisper; print('[OK] faster-whisper', faster_whisper.__version__)"
if errorlevel 1 echo [MANQUANT] faster-whisper

python -c "import webrtcvad; print('[OK] webrtcvad')"
if errorlevel 1 echo [MANQUANT] webrtcvad

python -c "import sounddevice; print('[OK] sounddevice', sounddevice.__version__)"
if errorlevel 1 echo [MANQUANT] sounddevice

python -c "import websockets; print('[OK] websockets')"
if errorlevel 1 echo [MANQUANT] websockets

python -c "import numpy; print('[OK] numpy', numpy.__version__)"
if errorlevel 1 echo [MANQUANT] numpy

python -c "import piper; print('[OK] piper-tts')"
if errorlevel 1 echo [MANQUANT] piper-tts

echo.
echo --- Modeles ---
if exist "%VOICE_DIR%models\stt\models--Systran--faster-whisper-small" (
    echo [OK] STT Whisper small
) else (
    echo [ABSENT] STT Whisper small — sera telecharge au premier lancement
)

if exist "%VOICE_DIR%models\tts\piper\fr_FR-mls-medium.onnx" (
    echo [OK] TTS Piper fr_FR-mls-medium
) else (
    echo [ABSENT] TTS Piper fr_FR-mls-medium — sera telecharge au premier lancement
)

echo.
echo --- CUDA ---
python -c "import torch; print('[OK] CUDA disponible — VRAM:', round(torch.cuda.get_device_properties(0).total_memory/1024**3,1), 'GB')" 2> nul
if errorlevel 1 echo [INFO] CUDA non disponible ou torch absent — STT/TTS fonctionneront en mode CPU

echo.
echo --- Microphones detectes ---
python -c "import sounddevice as sd; devs = [d for d in sd.query_devices() if d['max_input_channels'] > 0]; [print(f'  [{i}] {d[\"name\"]}') for i,d in enumerate(devs)] if devs else print('  Aucun microphone detecte')"

if "%CHOIX%"=="4" goto :fin_ok

:fin_ok
echo.
echo ============================================================
echo   Installation terminee.
echo   Demarrez LCCA Desktop et activez la voix dans Parametres.
echo ============================================================
echo.
pause
exit /b 0

:fin_erreur
echo.
echo ============================================================
echo   Installation echouee. Consultez les messages ci-dessus.
echo ============================================================
echo.
pause
exit /b 1
