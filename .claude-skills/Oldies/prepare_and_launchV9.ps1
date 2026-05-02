# prepare_and_launchV9.ps1
# Sequence :
#   1. Arret agressif + GC
#   2. Variables GPU/CPU strict (NoDevFiles en mode CPU)
#   3. Demarrage Ollama
#   4. Pull modeles manquants
#   5. Diagnostic + verif VRAM=0 si CPU + unload
#   6. Menu interactif
#   7. Lancement benchmark V9
#
# Lancer en Administrateur
# ASCII pur - pas d accents

[CmdletBinding()]
param(
    [ValidateSet("GPU", "CPU", "Hybride", "")]
    [string]$Mode = "",

    [switch]$Interactive,
    [switch]$SkipPull,
    [switch]$SkipDiagnostic,
    [int]$RunsPerPrompt = 3,
    [switch]$WhatIf
)

$ErrorActionPreference = "Continue"

function Log {
    param([string]$M, [string]$C = "White")
    $validColors = [System.Enum]::GetNames([System.ConsoleColor])
    if ($C -notin $validColors) { $C = "White" }
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $M" -ForegroundColor $C
}
function Sep { Write-Host ("=" * 60) -ForegroundColor DarkGray }

function Show-ModeMenu {
    Clear-Host
    $W = 64
    Write-Host ("=" * $W) -ForegroundColor Cyan
    Write-Host "   PREPARE & LAUNCH V9 -- CHOIX DU MODE BENCHMARK" -ForegroundColor Cyan
    Write-Host ("=" * $W) -ForegroundColor Cyan
    Write-Host ""
    Write-Host "   [1] Mode GPU     - 6 modeles rapides  (VRAM 4GB)" -ForegroundColor Green
    Write-Host "      qwen2.5-coder:3b, gemma4:e2b, qwen3:4b," -ForegroundColor DarkGray
    Write-Host "      phi4-mini-reasoning, gemma3:4b, gemma4:e4b" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "   [2] Mode CPU     - 6 modeles lourds   (RAM 32GB)" -ForegroundColor Yellow
    Write-Host "      deepseek-r1:8b, qwen3:8b, qwen3:14b," -ForegroundColor DarkGray
    Write-Host "      deepseek-r1:14b, qwen3-coder:30b, qwen3:30b" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "   [3] Mode Hybride - 12 modeles complet  (GPU+CPU)" -ForegroundColor Magenta
    Write-Host "      Tous les modeles ci-dessus" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "   [I] Info         - Details materiel + duree estimee" -ForegroundColor Cyan
    Write-Host "   [Q] Quitter      - Annuler" -ForegroundColor Red
    Write-Host ""
    Write-Host ("=" * $W) -ForegroundColor Cyan

    do {
        $choice = Read-Host "   Choix du mode"
        switch ($choice.Trim().ToUpper()) {
            "1" { return "GPU" }
            "2" { return "CPU" }
            "3" { return "Hybride" }
            "I" { Show-SystemInfo; continue }
            "Q" { Log "Annulation par l utilisateur." "Yellow"; exit 0 }
            default { Write-Host "   Choix invalide. Tapez 1, 2, 3, I ou Q." -ForegroundColor Red }
        }
    } while ($true)
}

function Show-SystemInfo {
    Clear-Host
    $W = 64
    Write-Host ("=" * $W) -ForegroundColor Cyan
    Write-Host "   INFORMATIONS SYSTEME" -ForegroundColor Cyan
    Write-Host ("=" * $W) -ForegroundColor Cyan

    $Nsmi = "C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
    if (-not (Test-Path $Nsmi)) { $Nsmi = "nvidia-smi" }
    try {
        $raw = & $Nsmi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>$null
        $p = ($raw -split ",\s*")
        Write-Host "   GPU  : $($p[0].Trim())" -ForegroundColor Green
        Write-Host "   VRAM : $($p[1].Trim()) MB total" -ForegroundColor Green
        Write-Host "   Driver : $($p[2].Trim())" -ForegroundColor Green
    } catch {
        Write-Host "   GPU  : Non detecte" -ForegroundColor Red
    }

    try {
        $os = Get-CimInstance -ClassName Win32_OperatingSystem
        $ramTotal = [math]::Round($os.TotalVisibleMemorySize / 1024 / 1024, 1)
        $ramFree  = [math]::Round($os.FreePhysicalMemory / 1024 / 1024, 1)
        Write-Host "   RAM  : ${ramTotal} GB total | ${ramFree} GB libre" -ForegroundColor Green
    } catch {
        Write-Host "   RAM  : Info indisponible" -ForegroundColor Yellow
    }

    try {
        $cpu = Get-CimInstance -ClassName Win32_Processor | Select-Object -First 1
        Write-Host "   CPU  : $($cpu.Name.Trim()) | $($cpu.NumberOfCores) coeurs" -ForegroundColor Green
    } catch {
        Write-Host "   CPU  : Info indisponible" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "   DUREES ESTIMEES (3 runs x 3 prompts) :" -ForegroundColor White
    Write-Host "   Mode GPU     : ~45 min" -ForegroundColor Green
    Write-Host "   Mode CPU     : ~6-8 h" -ForegroundColor Yellow
    Write-Host "   Mode Hybride : ~7-9 h" -ForegroundColor Magenta
    Write-Host ""
    Write-Host "   Appuyez sur ENTREE pour revenir au menu..." -ForegroundColor Gray
    Read-Host | Out-Null
    Clear-Host
    Write-Host ("=" * $W) -ForegroundColor Cyan
    Write-Host "   PREPARE & LAUNCH V9 -- CHOIX DU MODE BENCHMARK" -ForegroundColor Cyan
    Write-Host ("=" * $W) -ForegroundColor Cyan
    Write-Host ""
    Write-Host "   [1] Mode GPU     - 6 modeles rapides  (VRAM 4GB)" -ForegroundColor Green
    Write-Host "   [2] Mode CPU     - 6 modeles lourds   (RAM 32GB)" -ForegroundColor Yellow
    Write-Host "   [3] Mode Hybride - 12 modeles complet  (GPU+CPU)" -ForegroundColor Magenta
    Write-Host ""
    Write-Host "   [I] Info         - Details materiel + duree estimee" -ForegroundColor Cyan
    Write-Host "   [Q] Quitter      - Annuler" -ForegroundColor Red
    Write-Host ""
    Write-Host ("=" * $W) -ForegroundColor Cyan
}

# ==========================================
#  RESOLUTION MODE
# ==========================================
if ([string]::IsNullOrWhiteSpace($Mode)) {
    if ($Interactive -or -not $Mode) {
        $Mode = Show-ModeMenu
    } else {
        $Mode = "Hybride"
    }
}

Sep
Log "  PREPARE AND LAUNCH V9 -- BENCHMARK OVERNIGHT" "Cyan"
Log "  Mode selectionne : $Mode" "Cyan"
if ($WhatIf) { Log "  [WHATIF] Mode simulation active" "Magenta" }
Log "  $(Get-Date -Format 'yyyy-MM-dd HH:mm')" "Gray"
Sep

# ==========================================
#  ETAPE 1 : Arret complet (V9 agressif)
# ==========================================
Log ""
Log "--- ETAPE 1 : Arret complet (V9 agressif) ---" "Cyan"

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
    Log "  Service ollama detecte ($($svc.Status)) -- arret..." "Yellow"
    Stop-Service -Name "ollama" -Force -ErrorAction SilentlyContinue
    Set-Service -Name "ollama" -StartupType Disabled -ErrorAction SilentlyContinue
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

Log "  [V9] Garbage Collection + attente liberation RAM..." "DarkGray"
[System.GC]::Collect()
[System.GC]::WaitForPendingFinalizers()
Start-Sleep -Seconds 2

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
    Log "  ERREUR : port 11434 toujours occupe." "Red"
    exit 1
}
Log "  Port 11434 libre." "Green"

# ==========================================
#  ETAPE 2 : Variables environnement (V9)
# ==========================================
Log ""
Log "--- ETAPE 2 : Variables environnement (V9) ---" "Cyan"

# Nettoyage prealable pour eviter conflits Machine/User
foreach ($v in @("OLLAMA_NUM_GPU","CUDA_VISIBLE_DEVICES","OLLAMA_NEW_ENGINE")) {
    [System.Environment]::SetEnvironmentVariable($v, $null, "Machine")
    [System.Environment]::SetEnvironmentVariable($v, $null, "User")
}

if ($Mode -eq "CPU") {
    Log "  [V9] Mode CPU -- forçage strict CPU" "Yellow"
    [System.Environment]::SetEnvironmentVariable("OLLAMA_NUM_GPU", "0", "User")
    [System.Environment]::SetEnvironmentVariable("OLLAMA_NUM_GPU", "0", "Process")
    # V9 FIX CRITIQUE : NoDevFiles masque le GPU à CUDA, empêche tout fallback silencieux
    [System.Environment]::SetEnvironmentVariable("CUDA_VISIBLE_DEVICES", "NoDevFiles", "User")
    [System.Environment]::SetEnvironmentVariable("CUDA_VISIBLE_DEVICES", "NoDevFiles", "Process")
    Log "  OLLAMA_NUM_GPU = 0" "Green"
    Log "  CUDA_VISIBLE_DEVICES = NoDevFiles" "Green"
} else {
    foreach ($kv in @(
        @("OLLAMA_NUM_GPU",       "99"),
        @("CUDA_VISIBLE_DEVICES", "0"),
        @("OLLAMA_NEW_ENGINE",    "1")
    )) {
        [System.Environment]::SetEnvironmentVariable($kv[0], $kv[1], "User")
        [System.Environment]::SetEnvironmentVariable($kv[0], $kv[1], "Process")
        Log "  $($kv[0]) = $($kv[1])" "Green"
    }
}

$modelsPath = [System.Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "User")
if (-not $modelsPath) { $modelsPath = "D:\Continue\Ollama\models" }
[System.Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $modelsPath, "User")
[System.Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $modelsPath, "Process")
Log "  OLLAMA_MODELS = $modelsPath" "DarkGray"

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
if (-not $ready) { Log "  ERREUR : Ollama ne repond pas." "Red"; exit 1 }
Log "  Ollama OK sur :11434" "Green"

Log "  Attente indexation modeles..." "DarkGray"
Start-Sleep -Seconds 15

for ($i = 0; $i -lt 10; $i++) {
    try {
        $checkTags = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get -TimeoutSec 10
        if ($checkTags.models -and $checkTags.models.Count -gt 0) {
            Log "  Index OK : $($checkTags.models.Count) modele(s)" "Green"
            break
        }
        Log "  Index vide, attente... ($i)" "Yellow"
    } catch {
        Log "  /api/tags non disponible... ($i)" "Yellow"
    }
    Start-Sleep -Seconds 5
}

# ==========================================
#  ETAPE 4 : Pull des modeles manquants
# ==========================================
if (-not $SkipPull) {
    Log ""
    Log "--- ETAPE 4 : Pull modeles manquants ---" "Cyan"

    $AllBenchModels = @(
        "qwen2.5-coder:3b", "gemma4:e2b", "qwen3:4b", "phi4-mini-reasoning",
        "gemma3:4b", "gemma4:e4b", "deepseek-r1:8b", "qwen3:8b",
        "qwen3:14b", "deepseek-r1:14b", "qwen3-coder:30b-a3b-q4_K_M", "qwen3:30b-a3b"
    )

    try {
        $tagsResponse = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get -TimeoutSec 15
        $installedNames = $tagsResponse.models | ForEach-Object { $_.name }
    } catch {
        $installedRaw = & ollama list 2>&1
        $installedNames = $installedRaw | Select-String "^\S+" | ForEach-Object {
            $_.Matches[0].Value.Trim()
        }
    }

    Log "  Modeles installes : $($installedNames.Count)" "Gray"
    foreach ($m in $installedNames) { Log "    [$m]" "DarkGray" }

    $ToPull = @()
    foreach ($m in $AllBenchModels) {
        $mNorm = if ($m -notmatch ":") { "$m`:latest" } else { $m }
        $found = $installedNames | Where-Object {
            $_.Trim().ToLower() -eq $m.ToLower() -or
            $_.Trim().ToLower() -eq $mNorm.ToLower()
        }
        if ($found) {
            Log "  [OK] $m" "DarkGray"
        } else {
            Log "  [MISSING] $m" "Yellow"
            $ToPull += $m
        }
    }

    if ($ToPull.Count -eq 0) {
        Log "  Tous les modeles sont installes." "Green"
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
                $verify = Invoke-RestMethod -Uri "http://localhost:11434/api/show" -Method Post `
                    -Body (@{ name = $m } | ConvertTo-Json) -ContentType "application/json" -TimeoutSec 15 `
                    -ErrorAction SilentlyContinue
                if ($verify.details) {
                    Log "  [PULL] OK : $m en $([math]::Round($sw.Elapsed.TotalMinutes,1)) min" "Green"
                    $pullOk = $true
                }
            } catch {
                $sw.Stop()
                Log "  [PULL] ECHEC $m : $_" "Red"
            }
            if (-not $pullOk) {
                Log "  [PULL] $m sera marque SKIP." "Yellow"
            }
            Start-Sleep -Seconds 3
        }
    }

    Log ""
    Log "  Etat final ollama list :" "Gray"
    & ollama list 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
} else {
    Log ""
    Log "--- ETAPE 4 : Pull SKIPPED ---" "DarkGray"
}

# ==========================================
#  ETAPE 5 : Diagnostic + verif VRAM V9
# ==========================================
if (-not $SkipDiagnostic) {
    Log ""
    Log "--- ETAPE 5 : Diagnostic qwen2.5-coder:3b (V9) ---" "Cyan"

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

    # V9 FIX : construction du body avec num_gpu=0 explicite en mode CPU
    $warmupBody = @{
        model   = $diagModel
        prompt  = "hi"
        stream  = $false
        options = @{ num_predict = 5 }
    }
    if ($Mode -eq "CPU") {
        $warmupBody.options.num_gpu = 0
    }

    $swW = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
            -Body ($warmupBody | ConvertTo-Json) `
            -ContentType "application/json" -TimeoutSec 120 | Out-Null
        $swW.Stop()
        Log "  Warmup OK en $([math]::Round($swW.Elapsed.TotalMilliseconds,0)) ms" "Green"
    } catch {
        $swW.Stop()
        Log "  Warmup ECHEC : $_" "Red"
    }

    $snapHot = (& $Nsmi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits 2>$null) -split ",\s*"
    $vramDelta = [int]$snapHot[0] - [int]$snapCold[0]
    Log "  GPU apres load : VRAM $([int]$snapHot[0])/$([int]$snapHot[1]) MB | $([int]$snapHot[2])% | delta +$vramDelta MB" "White"
    if    ($vramDelta -gt 500) { Log "  GPU actif (+$vramDelta MB)" "Green" }
    elseif($vramDelta -gt 0)   { Log "  GPU partiel (+$vramDelta MB)" "Yellow" }
    else                        { Log "  CPU pur (delta=0)" "DarkGray" }

    # V9 : Si mode CPU et VRAM toujours utilisee malgre NoDevFiles + num_gpu=0, c'est critique
    if ($Mode -eq "CPU" -and $vramDelta -gt 0) {
        Log "  [V9 CRITIQUE] Mode CPU mais VRAM utilisee ! Fallback GPU non bloque." "Red"
        Log "  Verifiez pilote CUDA / Ollama. Arret pour eviter mauvaises mesures." "Red"
        exit 1
    }

    # V9 : Unload du modele diagnostic pour ne pas fausser le premier run du benchmark
    try {
        Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
            -Body (@{ model = $diagModel; keep_alive = 0 } | ConvertTo-Json) `
            -ContentType "application/json" -TimeoutSec 30 | Out-Null
        Log "  Unload diagnostic OK (keep_alive=0)" "DarkGray"
    } catch {
        Log "  Unload diagnostic ignore" "DarkGray"
    }

    Log ""
    Log "  ollama ps :" "Gray"
    & ollama ps 2>&1 | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }
} else {
    Log ""
    Log "--- ETAPE 5 : Diagnostic SKIPPED ---" "DarkGray"
}

# ==========================================
#  ETAPE 6 : Lancement benchmark V9
# ==========================================
Log ""
Sep
Log "--- ETAPE 6 : LANCEMENT BENCHMARK V9 (Mode: $Mode) ---" "Cyan"
if ($WhatIf) { Log "--- [WHATIF] Simulation uniquement ---" "Magenta" }
Sep
Log ""
Log "  Mode        : $Mode" "White"
Log "  Runs/prompt : $RunsPerPrompt" "White"
if ($WhatIf) { Log "  WhatIf      : OUI" "Magenta" }
Log "  Resultats   : $PSScriptRoot\CPUVsGPU\results\" "Green"
Log ""

if (-not $WhatIf) {
    Log "  Appuyez sur ENTREE pour demarrer..." "Yellow"
    Read-Host | Out-Null
}

$benchScriptPath = [System.IO.Path]::Combine("$PSScriptRoot", "run_benchmarkV9.ps1")
if (-not ([System.IO.File]::Exists("$benchScriptPath"))) {
    $benchScriptPath = [System.IO.Path]::Combine("$PSScriptRoot", "run_overnightV9.ps1")
    if (-not ([System.IO.File]::Exists("$benchScriptPath"))) {
        Log "  ERREUR : Script benchmark introuvable." "Red"
        exit 1
    }
}

Log "  Script : $benchScriptPath" "Gray"
$whatIfFlag = if ($WhatIf) { "-WhatIf" } else { "" }
$invokeCommand = "& `"$benchScriptPath`" -Mode `"$Mode`" -RunsPerPrompt $RunsPerPrompt $whatIfFlag"
Log "  Commande : $invokeCommand" "DarkGray"
Start-Sleep -Seconds 2

Invoke-Expression -Command "$invokeCommand"