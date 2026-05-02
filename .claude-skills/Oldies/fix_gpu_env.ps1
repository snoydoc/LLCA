# fix_gpu_env.ps1
# Corrige les variables d environnement qui bloquent le GPU Nvidia dans Ollama.
# IMPORTANT : Lance en tant qu Administrateur (clic droit --> Run as Administrator)
# ASCII pur - pas d accents dans ce fichier

$ErrorActionPreference = "Stop"

function Log { param([string]$M, [string]$C = "White") Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $M" -ForegroundColor $C }

Log "=== DIAGNOSTIC AVANT CORRECTION ===" "Cyan"

# Lire les valeurs actuelles (niveau Machine = systeme, niveau User = utilisateur)
$vars = @("OLLAMA_NUM_GPU","CUDA_VISIBLE_DEVICES","OLLAMA_NEW_ENGINE","OLLAMA_MODELS","OLLAMA_GPU_OVERHEAD")
foreach ($v in $vars) {
    $machine = [System.Environment]::GetEnvironmentVariable($v, "Machine")
    $user    = [System.Environment]::GetEnvironmentVariable($v, "User")
    if ($machine) { Log "  [MACHINE] $v = $machine" "Yellow" }
    if ($user)    { Log "  [USER]    $v = $user"    "Yellow" }
    if (-not $machine -and -not $user) { Log "  [--]      $v = non defini" "DarkGray" }
}

Log ""
Log "=== APPLICATION DES CORRECTIONS ===" "Cyan"

# -- CORRECTION 1 : OLLAMA_NUM_GPU
# 0 = CPU pur. On supprime pour laisser Ollama auto-detecter, puis on remet a 99
[System.Environment]::SetEnvironmentVariable("OLLAMA_NUM_GPU", $null, "Machine")
[System.Environment]::SetEnvironmentVariable("OLLAMA_NUM_GPU", $null, "User")
[System.Environment]::SetEnvironmentVariable("OLLAMA_NUM_GPU", "99",  "User")
Log "  OLLAMA_NUM_GPU    : 0 --> 99  (toutes les couches sur GPU)" "Green"

# -- CORRECTION 2 : CUDA_VISIBLE_DEVICES
# "NoDevFiles" = bloque la detection CUDA. On met "0" = premier GPU CUDA = Quadro M2000M
[System.Environment]::SetEnvironmentVariable("CUDA_VISIBLE_DEVICES", $null, "Machine")
[System.Environment]::SetEnvironmentVariable("CUDA_VISIBLE_DEVICES", $null, "User")
[System.Environment]::SetEnvironmentVariable("CUDA_VISIBLE_DEVICES", "0",   "User")
Log "  CUDA_VISIBLE_DEVICES : NoDevFiles --> 0  (Quadro M2000M = GPU CUDA 0)" "Green"

# -- CORRECTION 3 : OLLAMA_NEW_ENGINE
# 0 = ancien moteur. 1 = nouveau moteur (meilleure gestion GPU sur versions recentes)
[System.Environment]::SetEnvironmentVariable("OLLAMA_NEW_ENGINE", $null, "Machine")
[System.Environment]::SetEnvironmentVariable("OLLAMA_NEW_ENGINE", $null, "User")
[System.Environment]::SetEnvironmentVariable("OLLAMA_NEW_ENGINE", "1",   "User")
Log "  OLLAMA_NEW_ENGINE : 0 --> 1  (nouveau moteur actif)" "Green"

# -- OLLAMA_MODELS : on garde la valeur existante si presente
$existingModels = [System.Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "User")
if (-not $existingModels) {
    [System.Environment]::SetEnvironmentVariable("OLLAMA_MODELS", "D:\Continue\Ollama\models", "User")
    Log "  OLLAMA_MODELS     : defini --> D:\Continue\Ollama\models" "Green"
} else {
    Log "  OLLAMA_MODELS     : conserve --> $existingModels" "DarkGray"
}

Log ""
Log "=== VERIFICATION APRES CORRECTION ===" "Cyan"
foreach ($v in $vars) {
    $val = [System.Environment]::GetEnvironmentVariable($v, "User")
    if ($val) { Log "  [USER] $v = $val" "Green" }
    else      { Log "  [USER] $v = (non defini)" "DarkGray" }
}

Log ""
Log "=== ETAPES SUIVANTES ===" "Cyan"
Log ""
Log "  Les variables sont corrigees au niveau permanent (User)." "White"
Log "  MAIS : les processus en cours n en savent rien encore." "Yellow"
Log ""
Log "  Ce que tu dois faire maintenant :" "White"
Log "    1. Attends la FIN du benchmark en cours" "White"
Log "    2. Ferme TOUTES les fenetres PowerShell" "White"
Log "    3. Tue Ollama : taskkill /F /IM ollama.exe /T" "White"
Log "    4. Rouvre une nouvelle fenetre PowerShell" "White"
Log "    5. Lance : ollama serve" "White"
Log "    6. Dans une autre fenetre : ollama ps" "White"
Log "    7. Lance un modele : ollama run qwen3:4b" "White"
Log "    8. Verifie dans Task Manager --> GPU 1 (Nvidia) --> doit monter > 0%" "White"
Log ""
Log "  Si GPU toujours a 0% apres ces etapes :" "Yellow"
Log "    --> Lance diagnose_gpu.ps1 a nouveau et envoie les resultats" "Yellow"
Log ""
