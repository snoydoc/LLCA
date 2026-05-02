@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

set "PROJECT_ROOT=D:\LLMCodeAgent"
set "EDUCATOR_DIR=%PROJECT_ROOT%\Educator"
set "VENV_PYTHON=%PROJECT_ROOT%\venv\Scripts\python.exe"
set "RUNNER=%EDUCATOR_DIR%\educator_runner.py"

if not exist "%VENV_PYTHON%" (
    echo.
    echo  [ERREUR] Python venv introuvable : %VENV_PYTHON%
    pause
    exit /b 1
)

:MENU
cls
echo.
echo  ============================================================
echo   LCCA Educator - Apprentissage autonome
echo  ============================================================
echo.
echo    [1]  Continuer       - Ingestion complete (nuit)
echo    [2]  MAJ              - Verifier nouveautes (dry-run)
echo    [3]  Nouvelle source  - Ajouter un repo GitHub
echo    [4]  Voir sources     - Lister la whitelist
echo    [5]  Reset hashes     - Forcer re-ingestion (vider dedup)
echo    [6]  Toggle skip      - Activer/desactiver skip_license_check
echo    [Q]  Quitter
echo.
echo  ============================================================
echo.
set "CHOIX="
set /p "CHOIX=  Votre choix : "

if /i "!CHOIX!"=="1" goto MODE_ALL
if /i "!CHOIX!"=="2" goto MODE_UPDATE
if /i "!CHOIX!"=="3" goto NOUVELLE_SOURCE
if /i "!CHOIX!"=="4" goto VOIR_SOURCES
if /i "!CHOIX!"=="5" goto RESET_HASHES
if /i "!CHOIX!"=="6" goto TOGGLE_SKIP
if /i "!CHOIX!"=="Q" goto FIN

echo.
echo  Choix invalide. Recommencez.
timeout /t 2 >nul
goto MENU


:MODE_ALL
cls
echo.
echo  ============================================================
echo   MODE : INGESTION COMPLETE
echo  ============================================================
echo.
"%VENV_PYTHON%" "%RUNNER%" --mode all
echo.
echo  ============================================================
echo   Session terminee. Appuyez sur une touche.
echo  ============================================================
pause >nul
goto MENU


:MODE_UPDATE
cls
echo.
echo  ============================================================
echo   MODE : VERIFICATION MAJ (simulation)
echo  ============================================================
echo.
echo  Simulation sans ecriture en memoire.
echo.
"%VENV_PYTHON%" "%RUNNER%" --mode update
echo.
echo  ============================================================
echo   Verification terminee. Appuyez sur une touche.
echo  ============================================================
pause >nul
goto MENU


:NOUVELLE_SOURCE
cls
echo.
echo  ============================================================
echo   AJOUTER UNE NOUVELLE SOURCE
echo  ============================================================
echo.
echo  Format : owner/repo   ex: psf/black
echo.
set "REPO_INPUT="
set /p "REPO_INPUT=  owner/repo : "

if "!REPO_INPUT!"=="" (
    echo  [ERREUR] Entree vide.
    timeout /t 2 >nul
    goto NOUVELLE_SOURCE
)

set "OWNER_PART="
set "REPO_PART="
for /f "tokens=1,2 delims=/" %%A in ("!REPO_INPUT!") do (
    set "OWNER_PART=%%A"
    set "REPO_PART=%%B"
)

if "!REPO_PART!"=="" (
    echo  [ERREUR] Format invalide. Utilisez : owner/repo
    timeout /t 2 >nul
    goto NOUVELLE_SOURCE
)

echo.
set "DESC="
set /p "DESC=  Description courte (optionnel) : "
echo.
echo  skip_license_check : bypasse la verification de licence (PSF, NOASSERTION...)
set "SKIP_INPUT="
set /p "SKIP_INPUT=  Activer skip_license_check ? [O/N, defaut=N] : "
echo.

set "SKIP_FLAG="
if /i "!SKIP_INPUT!"=="O" set "SKIP_FLAG=--skip-license"

"%VENV_PYTHON%" "%RUNNER%" --add-source "!OWNER_PART!" "!REPO_PART!" "!DESC!" !SKIP_FLAG!

echo.
echo  ============================================================
pause >nul
goto MENU


:VOIR_SOURCES
cls
echo.
echo  ============================================================
echo   SOURCES CUSTOM ENREGISTREES
echo  ============================================================
echo.
"%VENV_PYTHON%" "%RUNNER%" --list-sources
echo.
echo  ============================================================
pause >nul
goto MENU


:RESET_HASHES
cls
echo.
echo  ============================================================
echo   RESET HASHES - Forcer re-ingestion
echo  ============================================================
echo.
"%VENV_PYTHON%" "%RUNNER%" --reset-hashes
echo.
echo  ============================================================
pause >nul
goto MENU


:TOGGLE_SKIP
cls
echo.
echo  ============================================================
echo   TOGGLE SKIP_LICENSE_CHECK
echo  ============================================================
echo.
echo  Active ou desactive skip_license_check sur un repo existant.
echo  Repos actuellement dans la whitelist : utilisez [4] pour voir la liste.
echo.
set "TOGGLE_INPUT="
set /p "TOGGLE_INPUT=  owner/repo : "

if "!TOGGLE_INPUT!"=="" (
    echo  [ERREUR] Entree vide.
    timeout /t 2 >nul
    goto TOGGLE_SKIP
)

set "OWN="
set "REP="
for /f "tokens=1,2 delims=/" %%A in ("!TOGGLE_INPUT!") do (
    set "OWN=%%A"
    set "REP=%%B"
)

if "!REP!"=="" (
    echo  [ERREUR] Format invalide. Utilisez : owner/repo
    timeout /t 2 >nul
    goto TOGGLE_SKIP
)

echo.
"%VENV_PYTHON%" "%RUNNER%" --toggle-skip "!OWN!" "!REP!"
echo.
echo  ============================================================
pause >nul
goto MENU


:FIN
cls
echo.
echo  LCCA Educator - Au revoir.
echo.
endlocal
exit /b 0
