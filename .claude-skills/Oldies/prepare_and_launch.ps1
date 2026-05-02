# prepare_and_launch.ps1
# SCRIPT A LANCER AVANT DE DORMIR
# Sequence :
#   1. Arret benchmark + service Ollama + tray
#   2. Correction variables GPU
#   3. Demarrage Ollama mode GPU
#   4. Pull des modeles manquants
#   5. Diagnostic qwen2.5-coder:3b
#   6. Lancement benchmark overnight V4
#
# IMPORTANT : Lancer en Administrateur
# ASCII pur - pas d accents dans ce fichier

$ErrorActionPreference = "Continue"

function Log {
    param([string]$M, [string]$C = "White")
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $M" -ForegroundColor $C
}
function Sep { Write-Host ("=" * 60) -ForegroundColor DarkGray }

Sep
Log "  PREPARE AND LAUNCH V4 -- BENCHMARK GPU OVERNIGHT" "Cyan"
Log "  $(Get-Date -Format 'yyyy-MM-dd HH:mm')" "Gray"
Sep

# ==========================================
#  ETAPE 1 : Arret de tout
# ==========================================
Log ""
Log "--- ETAPE 1 : Arret ---" "Cyan"

$psProcs = Get-Process powershell, pwsh -ErrorAction SilentlyContinue |
    Where-Object { $_.Id -ne $PID }
if ($psProcs) {
    foreach ($p in $psProcs) {
        Log "  Kill PID $($p.Id)" "Yellow"
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 3
    Log "  PowerShell tiers arretes." "Green"
} else {
    Log "  Aucun autre PowerShell." "DarkGray"
}

$svc = Get-Service -Name "ollama" -ErrorAction SilentlyContinue
if ($svc) {
    Log "  Service ollama detecte ($($svc.Status)) -- arret + desactivation..." "Yellow"
    Stop-Service -Name "ollama" -Force -ErrorAction SilentlyContinue
    Set-Service  -Name "ollama" -StartupType Disabled -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    Log "  Service ollama arrete." "Green"
} else {
    Log "  Pas de service ollama." "DarkGray"
}

Get-Process | Where-Object { $_.ProcessName -match "ollama" -and $_.Id -ne $PID } |
    ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
taskkill /F /IM ollama.exe /T 2>$null | Out-Null
taskkill /F /IM "ollama app.exe" /T 2>$null | Out-Null
taskkill /F /IM ollama_llm_server.exe /T 2>$null | Out-Null
Start-Sleep -Seconds 5

$portBusy = $true
for ($p = 0; $p -lt 15; $p++) {
    $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 11434 -WarningAction SilentlyContinue
    if (-not $tcp.TcpTestSucceeded) { $portBusy = $false; break }
    Log "  Port 11434 occupe... ($p)" "Yellow"
    $owners = (Get-NetTCPConnection -LocalPort 11434 -ErrorAction SilentlyContinue).OwningProcess | Sort-Object -Unique
    foreach ($o in $owners) {
        if ($o -and $o -ne $PID) { Stop-Process -Id $o -Force -ErrorAction SilentlyContinue }
    }
    Start-Sleep -Seconds 3
}
if ($portBusy) {
    Log "  ERREUR : port 11434 toujours occupe. Lance : netstat -ano | findstr 11434" "Red"
    exit 1
}
Log "  Port 11434 libre." "Green"

# ==========================================
#  ETAPE 2 : Variables GPU
# ==========================================
Log ""
Log "--- ETAPE 2 : Variables GPU ---" "Cyan"

foreach ($kv in @(
    @("OLLAMA_NUM_GPU",       "99"),
    @("CUDA_VISIBLE_DEVICES", "0"),
    @("OLLAMA_NEW_ENGINE",    "1")
)) {
    [System.Environment]::SetEnvironmentVariable($kv[0], $null,    "Machine")
    [System.Environment]::SetEnvironmentVariable($kv[0], $null,    "User")
    [System.Environment]::SetEnvironmentVariable($kv[0], $kv[1],   "User")
    [System.Environment]::SetEnvironmentVariable($kv[0], $kv[1],   "Process")
    Log "  $($kv[0]) = $($kv[1])" "Green"
}

$modelsPath = [System.Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "User")
if (-not $modelsPath) { $modelsPath = "D:\Continue\Ollama\models" }
[System.Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $modelsPath, "User")
[System.Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $modelsPath, "Process")
Log "  OLLAMA_MODELS = $modelsPath" "DarkGray"

$suspects = Get-ChildItem -Path "$PSScriptRoot" -Recurse `
    -Include "*.py","*.toml","*.json","*.env","*.ps1","*.bat" -ErrorAction SilentlyContinue |
    Select-String -Pattern "OLLAMA_NUM_GPU|num_gpu|CUDA_VISIBLE" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -notmatch "prepare_and_launch|run_overnight|\.git" }
if ($suspects) {
    Log "  ATTENTION surcharges detectees :" "Yellow"
    foreach ($s in $suspects) { Log "    $($s.Path):$($s.LineNumber) $($s.Line.Trim())" "Yellow" }
} else {
    Log "  Aucune surcharge OLLAMA_NUM_GPU dans LCCA." "Green"
}

# ==========================================
#  ETAPE 3 : Demarrage Ollama
# ==========================================
Log ""
Log "--- ETAPE 3 : Demarrage Ollama ---" "Cyan"

Start-Process -FilePath "ollama" -ArgumentList "serve" -NoNewWindow
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    if ((Test-NetConnection -ComputerName 127.0.0.1 -Port 11434 -WarningAction SilentlyContinue).TcpTestSucceeded) {
        $ready = $true; break
    }
}
if (-not $ready) { Log "  ERREUR : Ollama ne repond pas. Abandon." "Red"; exit 1 }
Log "  Ollama OK sur :11434" "Green"
# Attendre que l'index des modeles soit charge (evite /api/tags vide au demarrage)
Log "  Attente indexation modeles..." "DarkGray"
Start-Sleep -Seconds 15

# Verifier que /api/tags repond et liste au moins un modele
for ($i = 0; $i -lt 10; $i++) {
    try {
        $checkTags = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get -TimeoutSec 10
        if ($checkTags.models -and $checkTags.models.Count -gt 0) {
            Log "  Index OK : $($checkTags.models.Count) modele(s) visibles" "Green"
            break
        }
        Log "  Index vide, attente... ($i)" "Yellow"
    } catch {
        Log "  /api/tags non disponible, attente... ($i)" "Yellow"
    }
    Start-Sleep -Seconds 5
}

# ==========================================
#  ETAPE 4 : Pull des modeles manquants
# ==========================================
Log ""
Log "--- ETAPE 4 : Pull modeles manquants ---" "Cyan"

# Liste complete des modeles du benchmark
$AllBenchModels = @(
    "qwen2.5-coder:3b",
    "gemma4:e2b",
    "qwen3:4b",
    "phi4-mini-reasoning",
    "gemma3:4b",
    "gemma4:e4b",
    "deepseek-r1:8b",
    "qwen3:8b",
    "qwen3:14b",
    "deepseek-r1:14b",
    "qwen3-coder:30b-a3b-q4_K_M",
    "qwen3:30b-a3b"
)

# Recuperer la liste des modeles installes via API (plus fiable que parser ollama list)
try {
    $tagsResponse = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get -TimeoutSec 15
    $installedNames = $tagsResponse.models | ForEach-Object { $_.name }
} catch {
    # Fallback : parser ollama list
    $installedRaw  = & ollama list 2>&1
    $installedNames = $installedRaw | Select-String "^\S+" | ForEach-Object {
        $_.Matches[0].Value.Trim()
    }
}

Log "  Modeles installes detectes : $($installedNames.Count)" "Gray"
foreach ($m in $installedNames) { Log "    [$m]" "DarkGray" }

$ToPull = @()
foreach ($m in $AllBenchModels) {
    # Normaliser : si pas de tag, ajouter :latest
    $mNorm       = if ($m -notmatch ":") { "$m`:latest" } else { $m }
    # Comparaison insensible casse + trim
    $found = $installedNames | Where-Object {
        $_.Trim().ToLower() -eq $m.ToLower() -or
        $_.Trim().ToLower() -eq $mNorm.ToLower()
    }
    if ($found) {
        Log "  [OK] $m -> trouve comme : $($found | Select-Object -First 1)" "DarkGray"
    } else {
        Log "  [MISSING] $m (normalise: $mNorm) -- sera pull" "Yellow"
        $ToPull += $m
    }
}

if ($ToPull.Count -eq 0) {
    Log "  Tous les modeles sont deja installes." "Green"
} else {
    Log "  $($ToPull.Count) modele(s) a telecharger :" "Yellow"
    foreach ($m in $ToPull) { Log "    - $m" "Yellow" }
    Log ""

    foreach ($m in $ToPull) {
        Log "  [PULL] $m ..." "Cyan"
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $pullOk = $false
        try {
            $lastManifest = $false
            & ollama pull $m 2>&1 | ForEach-Object {
                $line = "$_"
                if ($line -match "pulling manifest") {
                    if (-not $lastManifest) {
                        Write-Host "    pulling manifest..." -ForegroundColor DarkGray
                        $lastManifest = $true
                    }
                } else {
                    $lastManifest = $false
                    if ($line -match "pulling|verifying|success|error|writing") {
                        Write-Host "    $line" -ForegroundColor DarkGray
                    }
                }
            }
            $sw.Stop()
            # Verifier que le pull a reussi
            $verify = Invoke-RestMethod -Uri "http://localhost:11434/api/show" -Method Post `
                -Body (@{ name = $m } | ConvertTo-Json) -ContentType "application/json" -TimeoutSec 15 `
                -ErrorAction SilentlyContinue
            if ($verify.details) {
                Log "  [PULL] OK : $m ($($verify.details.parameter_size) $($verify.details.quantization_level)) en $([math]::Round($sw.Elapsed.TotalMinutes,1)) min" "Green"
                $pullOk = $true
            } else {
                Log "  [PULL] Verification echouee pour $m" "Yellow"
            }
        } catch {
            $sw.Stop()
            Log "  [PULL] ECHEC $m : $_" "Red"
        }
        if (-not $pullOk) {
            Log "  [PULL] $m sera marque SKIP dans le benchmark." "Yellow"
        }
        Start-Sleep -Seconds 3
    }
}

Log ""
Log "  Etat final ollama list :" "Gray"
& ollama list 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }

# ==========================================
#  ETAPE 5 : Diagnostic qwen2.5-coder:3b
# ==========================================
Log ""
Log "--- ETAPE 5 : Diagnostic qwen2.5-coder:3b ---" "Cyan"

$Nsmi = "C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
if (-not (Test-Path $Nsmi)) { $Nsmi = "nvidia-smi" }

$snapCold = (& $Nsmi --query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader,nounits 2>$null) -split ",\s*"
Log "  GPU a froid : VRAM $([int]$snapCold[0])/$([int]$snapCold[1]) MB | $([int]$snapCold[2])% | $([int]$snapCold[3])C" "Gray"

$diagModel = "qwen2.5-coder:3b"
try {
    $showR = Invoke-RestMethod -Uri "http://localhost:11434/api/show" -Method Post `
        -Body (@{ name = $diagModel } | ConvertTo-Json) -ContentType "application/json" -TimeoutSec 15
    Log "  family=$($showR.details.family) | size=$($showR.details.parameter_size) | quant=$($showR.details.quantization_level)" "White"
} catch {
    Log "  /api/show ECHEC : $_" "Red"
}

$swW = [System.Diagnostics.Stopwatch]::StartNew()
try {
    Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
        -Body (@{ model=$diagModel; prompt="hi"; stream=$false; options=@{num_predict=5} } | ConvertTo-Json) `
        -ContentType "application/json" -TimeoutSec 120 | Out-Null
    $swW.Stop()
    Log "  Warmup OK en $([math]::Round($swW.Elapsed.TotalMilliseconds,0)) ms" "Green"
} catch {
    Log "  Warmup ECHEC : $_" "Red"
}

$snapHot   = (& $Nsmi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits 2>$null) -split ",\s*"
$vramDelta = [int]$snapHot[0] - [int]$snapCold[0]
Log "  GPU apres load : VRAM $([int]$snapHot[0])/$([int]$snapHot[1]) MB | $([int]$snapHot[2])% | delta +$vramDelta MB" "White"
if    ($vramDelta -gt 500) { Log "  GPU actif (+$vramDelta MB)" "Green" }
elseif($vramDelta -gt 0)   { Log "  GPU partiel (+$vramDelta MB)" "Yellow" }
else                        { Log "  ATTENTION : delta=0 MB -- CPU pur !" "Red" }

Log ""
Log "  ollama ps :" "Gray"
& ollama ps 2>&1 | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }

# ==========================================
#  ETAPE 6 : Lancement benchmark
# ==========================================
Log ""
Sep
Log "--- ETAPE 6 : LANCEMENT BENCHMARK OVERNIGHT V7 (run_overnightV7.ps1) ---" "Cyan"
Sep
Log ""
Log "  CSV incremental sauve apres chaque run (V7+)." "Green"
Log "  Resultats : $PSScriptRoot\CPUVsGPU\results\" "Green"
Log "  Reponses  : $PSScriptRoot\CPUVsGPU\results\responses\" "Green"
Log ""
Start-Sleep -Seconds 3

& "$PSScriptRoot\run_overnightV8.ps1"
