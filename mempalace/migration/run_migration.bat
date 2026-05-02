@echo off
setlocal enabledelayedexpansion

set BASE=D:\LLMCodeAgent
set VENV=%BASE%\venv
set PYTHON=%VENV%\Scripts\python.exe
set PIP=%VENV%\Scripts\pip.exe
set SCRIPT=%BASE%\mempalace\migration\migrate_palace.py
set PALACE=%BASE%\mempalace\palace
set REPORT=%BASE%\mempalace\migration\migration_report.json

cls
echo ============================================================
echo   LLCA -- Migration Palace Local (MIG-05)
echo ============================================================
echo.

:: -- 1. Verifier le venv ------------------------------------------
if not exist "%PYTHON%" (
    echo [ERREUR] venv introuvable : %VENV%
    echo          Creer le venv : python -m venv venv
    echo          Puis           : venv\Scripts\pip install chromadb
    pause
    exit /b 1
)
echo [OK] venv : %VENV%

:: -- 2. Verifier chromadb -----------------------------------------
"%PYTHON%" -c "import chromadb" >nul 2>&1
if not errorlevel 1 goto CHROMADB_OK

echo.
echo [WARN] chromadb absent du venv.
echo  Le palace ne peut pas etre peuple sans chromadb.
echo.
set /p INSTALL_NOW=Installer chromadb maintenant ? (o/n) : 
if /i not "!INSTALL_NOW!"=="o" goto ANNULER_CHROMA

echo.
echo Installation de chromadb...
"%PIP%" install chromadb
if errorlevel 1 (
    echo [ERREUR] Installation echouee. Verifier la connexion internet.
    pause
    exit /b 1
)
echo [OK] chromadb installe.
goto CHROMADB_OK

:ANNULER_CHROMA
echo.
echo [INFO] Migration annulee. Installer chromadb puis relancer.
pause
exit /b 0

:CHROMADB_OK
echo [OK] chromadb disponible.

:: -- 3. Verifier le script ----------------------------------------
if not exist "%SCRIPT%" (
    echo [ERREUR] Script introuvable : %SCRIPT%
    pause
    exit /b 1
)
echo [OK] Script : %SCRIPT%

:: -- 4. Etat actuel du palace -------------------------------------
echo.
echo ============================================================
echo   Etat actuel du palace local
echo ============================================================
if exist "%PALACE%\chroma.sqlite3" (
    echo [INFO] Palace ChromaDB existant detecte.
) else (
    echo [INFO] Palace vide -- premier peuplement.
)
echo   Chemin : %PALACE%
echo.

:: -- 5. Menu principal --------------------------------------------
echo ============================================================
echo   Choisir une action
echo ============================================================
echo.
echo   [1] Dry-run   -- Simuler sans ecrire dans ChromaDB
echo   [2] Migration -- Peupler le palace LLCA (REEL)
echo   [3] Quitter
echo.
set /p CHOIX=Votre choix (1/2/3) : 

if "!CHOIX!"=="1" goto DRY_RUN
if "!CHOIX!"=="2" goto MIGRATION_REELLE
if "!CHOIX!"=="3" goto FIN
echo [ERREUR] Choix invalide.
goto FIN

:: -- Dry-run ------------------------------------------------------
:DRY_RUN
echo.
echo ============================================================
echo   DRY-RUN -- Simulation (aucune ecriture ChromaDB)
echo ============================================================
echo.
cd /d "%BASE%"
"%PYTHON%" "%SCRIPT%" --dry-run
echo.
echo [OK] Dry-run termine. Aucune donnee ecrite.
echo      Relancer avec [2] pour la migration reelle.
goto RAPPORT

:: -- Migration reelle ---------------------------------------------
:MIGRATION_REELLE
echo.
echo ============================================================
echo   MIGRATION REELLE
echo ============================================================
echo.
echo  Sources a importer :
echo    - .claude-skills\001-master.md
echo    - .claude-skills\002-context.md
echo    - .claude-skills\003-antipatterns.md
echo    - export\drawers_llca\lccacodeagent_diary_sp03.json
echo    - export\drawers_llca\claude_diary_lcca_v7_2026-04-18.json
echo.
echo  Destination : %PALACE%
echo.
set /p CONFIRM=Confirmer la migration ? (oui/non) : 
if /i not "!CONFIRM!"=="oui" (
    echo [INFO] Migration annulee.
    goto FIN
)
echo.
echo  Lancement...
echo.
cd /d "%BASE%"
"%PYTHON%" "%SCRIPT%"
if errorlevel 1 (
    echo.
    echo [ERREUR] La migration a echoue. Consulter les logs ci-dessus.
    pause
    exit /b 1
)

:: -- Rapport ------------------------------------------------------
:RAPPORT
echo.
echo ============================================================
echo   Rapport de migration
echo ============================================================
if exist "%REPORT%" (
    echo  Fichier : %REPORT%
    echo.
    "%PYTHON%" -c "import json; r=json.load(open(r'%REPORT%',encoding='utf-8')); print('  Date     :', r.get('date','?')); print('  Importe  :', r.get('drawers_imported','?')); print('  Skipped  :', r.get('drawers_skipped','?')); print('  Erreurs  :', len(r.get('errors',[])))"
) else (
    echo  [INFO] Rapport non disponible.
)
echo.

:FIN
echo.
pause
endlocal
