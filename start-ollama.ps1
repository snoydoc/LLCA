# start-ollama.ps1 - Lance Ollama pour LCCA (Lenovo P50 / Quadro M2000M 4 GB)
# V2 : menu 3 modes (CPU / GPU / Hybride) inspire de run_benchmarkV9_2.ps1
#
# Modes :
#   GPU     - OLLAMA_NUM_GPU=99  CUDA_VISIBLE_DEVICES=0   (defaut LCCA, ~11 tok/s)
#   CPU     - OLLAMA_NUM_GPU=0   CUDA_VISIBLE_DEVICES=NoDevFiles  (gros modeles 14B+)
#   Hybride - OLLAMA_NUM_GPU=1   CUDA_VISIBLE_DEVICES=0   (VRAM partielle + RAM overflow)
#
# Usage :
#   .\start-ollama.ps1                            -> menu interactif complet
#   .\start-ollama.ps1 -Mode GPU                  -> mode direct sans menu mode
#   .\start-ollama.ps1 -Mode CPU -Model qwen3:14b -> tout en argument
#   .\start-ollama.ps1 -Mode GPU -Model default   -> qwen3:8b (defaut)

param(
    [ValidateSet("GPU", "CPU", "Hybride", "")]
    [string]$Mode  = "",
    [string]$Model = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "SilentlyContinue"

# ==========================================
#  CATALOGUE DES MODELES
# ==========================================
$ModelCatalog = @(
    [PSCustomObject]@{ Name = "qwen3:8b";                    Tier = "GPU";     Label = "qwen3:8b                 GPU  ~5.5 GB VRAM  | coding + thinking | defaut" }
    [PSCustomObject]@{ Name = "qwen2.5-coder:3b";            Tier = "GPU";     Label = "qwen2.5-coder:3b         GPU  ~2.0 GB VRAM  | ultra-rapide ~11 tok/s" }
    [PSCustomObject]@{ Name = "gemma4:e2b";                  Tier = "GPU";     Label = "gemma4:e2b               GPU  ~1.5 GB VRAM  | challenger 3b (~10 tok/s)" }
    [PSCustomObject]@{ Name = "phi4-mini-reasoning:latest";  Tier = "GPU";     Label = "phi4-mini-reasoning      GPU  ~3.0 GB VRAM  | reasoning stable" }
    [PSCustomObject]@{ Name = "qwen3:4b";                    Tier = "GPU";     Label = "qwen3:4b                 GPU  ~2.7 GB VRAM  | bon candidat prod" }
    [PSCustomObject]@{ Name = "qwen3:14b";                   Tier = "CPU";     Label = "qwen3:14b                CPU  ~9 GB  RAM    | qualite++" }
    [PSCustomObject]@{ Name = "deepseek-r1:8b";              Tier = "CPU";     Label = "deepseek-r1:8b           CPU  ~5.5 GB RAM   | reasoning chain-of-thought" }
    [PSCustomObject]@{ Name = "deepseek-r1:14b";             Tier = "CPU";     Label = "deepseek-r1:14b          CPU  ~9 GB  RAM    | debug + reasoning" }
    [PSCustomObject]@{ Name = "qwen3-coder:30b-a3b-q4_K_M"; Tier = "CPU";     Label = "qwen3-coder:30b-a3b      CPU  ~18 GB RAM   | coding overnight" }
    [PSCustomObject]@{ Name = "qwen3:30b-a3b";               Tier = "Hybride"; Label = "qwen3:30b-a3b            HYB  ~18 GB RAM   | MoE 3B actifs" }
)
$DefaultModel = "qwen3:8b"

# ==========================================
#  UTILITAIRES
# ==========================================
function Write-Header {
    param([string]$Text, [System.ConsoleColor]$Color = "Cyan")
    $W = 54
    Write-Host ("=" * $W) -ForegroundColor $Color
    Write-Host ("  " + $Text) -ForegroundColor $Color
    Write-Host ("=" * $W) -ForegroundColor $Color
}

function Get-LocalModels {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 3 -ErrorAction Stop
        $json = $resp.Content | ConvertFrom-Json
        return @($json.models | ForEach-Object { $_.name })
    } catch {
        return @()
    }
}

# ==========================================
#  MENU MODE
# ==========================================
function Show-ModeMenu {
    Clear-Host
    Write-Header "LCCA - Ollama / Mode de lancement"
    Write-Host ""
    Write-Host "  [1] GPU     - VRAM CUDA (Quadro M2000M 4 GB)" -ForegroundColor White
    Write-Host "              Rapide, modeles <= 4-5 GB VRAM" -ForegroundColor DarkGray
    Write-Host "              OLLAMA_NUM_GPU=99  CUDA=0" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  [2] CPU     - RAM systeme uniquement" -ForegroundColor White
    Write-Host "              Gros modeles 8B-30B, pas de VRAM" -ForegroundColor DarkGray
    Write-Host "              OLLAMA_NUM_GPU=0   CUDA=NoDevFiles" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  [3] Hybride - VRAM partielle + RAM overflow" -ForegroundColor White
    Write-Host "              MoE / modeles > 4 GB avec layers CPU" -ForegroundColor DarkGray
    Write-Host "              OLLAMA_NUM_GPU=1   CUDA=0" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  [Q] Quitter" -ForegroundColor DarkGray
    Write-Host ""

    do {
        $c = Read-Host "  Choix"
        switch ($c.Trim().ToUpper()) {
            "1" { return "GPU" }
            "2" { return "CPU" }
            "3" { return "Hybride" }
            "Q" { exit 0 }
            default { Write-Host "  Choix invalide." -ForegroundColor Red }
        }
    } while ($true)
}

# ==========================================
#  MENU MODELE
# ==========================================
function Show-ModelMenu {
    param([string]$Mode)
    Write-Host ""
    Write-Header "LCCA - Selection du modele  [Mode : $Mode]"

    $localModels = Get-LocalModels
    if ($localModels.Count -gt 0) {
        Write-Host "  [Ollama actif -- modeles locaux detectes]" -ForegroundColor DarkGray
    } else {
        Write-Host "  [Ollama inactif ou aucun modele local]" -ForegroundColor DarkGray
    }
    Write-Host ""

    # Filtrer les entrees selon le mode (afficher tous, mais marquer le tier)
    $catalog = $script:ModelCatalog
    for ($i = 0; $i -lt $catalog.Count; $i++) {
        $entry   = $catalog[$i]
        $present = if ($localModels -contains $entry.Name) { "[OK]   " } else { "[pull] " }
        $tierTag = switch ($entry.Tier) {
            "GPU"     { "GPU    " }
            "CPU"     { "CPU    " }
            "Hybride" { "HYB    " }
        }
        $color = if ($localModels -contains $entry.Name) {
            switch ($entry.Tier) {
                "GPU"     { "Green" }
                "CPU"     { "Yellow" }
                "Hybride" { "Cyan" }
            }
        } else { "DarkGray" }
        Write-Host ("  [{0,2}] {1} {2}" -f ($i + 1), $present, $entry.Label) -ForegroundColor $color
    }

    Write-Host ""
    Write-Host "  [ A] Saisir un nom de modele manuellement" -ForegroundColor Yellow
    Write-Host ""

    do {
        $c = Read-Host "  Choix (1-$($catalog.Count) / A)"
        if ($c -match "^[Aa]$") {
            $name = Read-Host "  Nom du modele"
            if ([string]::IsNullOrWhiteSpace($name)) {
                Write-Host "  Aucun modele saisi. Defaut : $DefaultModel" -ForegroundColor Yellow
                return $DefaultModel
            }
            return $name.Trim()
        } elseif ($c -match "^\d+$" -and [int]$c -ge 1 -and [int]$c -le $catalog.Count) {
            return $catalog[[int]$c - 1].Name
        } else {
            Write-Host "  Choix invalide." -ForegroundColor Red
        }
    } while ($true)
}

# ==========================================
#  RESOLUTION MODE + MODELE
# ==========================================
if ([string]::IsNullOrWhiteSpace($Mode)) {
    $Mode = Show-ModeMenu
}

if ($Model -eq "default" -or [string]::IsNullOrWhiteSpace($Model)) {
    if ($Model -eq "default") {
        $Model = $DefaultModel
    } else {
        $Model = Show-ModelMenu -Mode $Mode
    }
}

Write-Host ""
Write-Host "[LCCA] Mode   : $Mode" -ForegroundColor Cyan
Write-Host "[LCCA] Modele : $Model" -ForegroundColor Green

# ==========================================
#  VARIABLES D'ENVIRONNEMENT selon le MODE
# ==========================================
$env:OLLAMA_MODELS = "D:\Continue\Ollama\models"

switch ($Mode) {
    "GPU" {
        $env:OLLAMA_NUM_GPU       = "99"
        $env:CUDA_VISIBLE_DEVICES = "0"
        $env:OLLAMA_NEW_ENGINE    = "1"
        Remove-Item Env:OLLAMA_SCHED_SPREAD -ErrorAction SilentlyContinue
        $modeDesc = "GPU full  | OLLAMA_NUM_GPU=99  CUDA=0  NEW_ENGINE=1"
    }
    "CPU" {
        $env:OLLAMA_NUM_GPU       = "0"
        $env:CUDA_VISIBLE_DEVICES = "NoDevFiles"
        Remove-Item Env:OLLAMA_NEW_ENGINE    -ErrorAction SilentlyContinue
        Remove-Item Env:OLLAMA_SCHED_SPREAD  -ErrorAction SilentlyContinue
        $modeDesc = "CPU only  | OLLAMA_NUM_GPU=0   CUDA=NoDevFiles"
    }
    "Hybride" {
        $env:OLLAMA_NUM_GPU       = "1"
        $env:CUDA_VISIBLE_DEVICES = "0"
        $env:OLLAMA_NEW_ENGINE    = "1"
        $env:OLLAMA_SCHED_SPREAD  = "1"
        $modeDesc = "Hybride   | OLLAMA_NUM_GPU=1   CUDA=0  SCHED_SPREAD=1"
    }
}

# ==========================================
#  ECRITURE DU MODELE ACTIF (pour LCCA)
# ==========================================
$ActiveModelFile = "$PSScriptRoot\.ollama-active-model.json"
$json = "{`"model`": `"$Model`", `"mode`": `"$Mode`"}"
Set-Content -Path $ActiveModelFile -Value $json -Encoding UTF8
Write-Host "[LCCA] Modele actif ecrit dans : $ActiveModelFile" -ForegroundColor DarkGray

# ==========================================
#  ARRET DES INSTANCES EXISTANTES
# ==========================================
Write-Host ""
Write-Host "[LCCA] Arret des instances Ollama existantes..." -ForegroundColor Yellow
taskkill /F /IM ollama.exe             /T 2>$null | Out-Null
taskkill /F /IM ollama_llm_server.exe  /T 2>$null | Out-Null
taskkill /F /IM ollama_app.exe         /T 2>$null | Out-Null
Start-Sleep -Seconds 5

# Verifie que le port est libre (max 20s)
$portFree = $false
for ($i = 0; $i -lt 20; $i++) {
    $portCheck = netstat -ano | Select-String ":11434"
    if (-not $portCheck) { $portFree = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $portFree) {
    Write-Host "[LCCA] Port 11434 toujours occupe apres 20s." -ForegroundColor Red
    netstat -ano | findstr ":11434"
    Write-Host "[LCCA] Lancer : taskkill /F /PID <PID> /T" -ForegroundColor Gray
    exit 1
}

# ==========================================
#  HEADER DEMARRAGE
# ==========================================
Write-Host ""
Write-Header "LCCA - Ollama [$Mode]  --  $(Get-Date -Format 'HH:mm')" "Green"
Write-Host "  Modele  : $Model" -ForegroundColor White
Write-Host "  Config  : $modeDesc" -ForegroundColor White
Write-Host "  Dossier : $env:OLLAMA_MODELS" -ForegroundColor White
Write-Host "  GPU     : Quadro M2000M (CUDA device 0, 4 GB VRAM)" -ForegroundColor White
Write-Host "  Port    : 11434" -ForegroundColor White
Write-Host ""

# ==========================================
#  DEMARRAGE OLLAMA
# ==========================================
Write-Host "[LCCA] Demarrage Ollama... (Ctrl+C pour arreter)" -ForegroundColor Green
$ollamaProc = Start-Process -FilePath "ollama" -ArgumentList "serve" -PassThru -NoNewWindow

Write-Host "[LCCA] Attente demarrage Ollama (max 30s)..." -ForegroundColor Cyan
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 11434 -WarningAction SilentlyContinue
    if ($tcp.TcpTestSucceeded) { $ready = $true; break }
}

if (-not $ready) {
    Write-Host "[LCCA] Ollama ne repond pas apres 30s." -ForegroundColor Red
    Stop-Process -Id $ollamaProc.Id -Force -ErrorAction SilentlyContinue
    exit 1
}
Write-Host "[LCCA] Ollama pret." -ForegroundColor Green

# Verification GPU si mode GPU ou Hybride
if ($Mode -ne "CPU") {
    $nsmi = "C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
    if (Test-Path $nsmi) {
        $gpuRaw = & $nsmi --query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu `
                    --format=csv,noheader,nounits 2>$null
        if ($gpuRaw) {
            $p = ($gpuRaw -split ",\s*")
            Write-Host ("[LCCA] GPU       : {0}/{1} MB VRAM | {2}% | {3}C" -f $p[0].Trim(),$p[1].Trim(),$p[2].Trim(),$p[3].Trim()) -ForegroundColor DarkGray
        }
    }
}

# ==========================================
#  VERIFICATION / PULL DU MODELE
# ==========================================
Write-Host "[LCCA] Verification modele $Model..." -ForegroundColor Cyan
$modelList = ollama list 2>$null
if ($modelList -match [regex]::Escape($Model)) {
    Write-Host "[LCCA] $Model present. Warm-up en cours..." -ForegroundColor Green
    $numGpu     = switch ($Mode) { "GPU" { "-1" }; "CPU" { "0" }; "Hybride" { "1" } }
    $warmupBody = "{`"model`":`"$Model`",`"prompt`":`"ok`",`"stream`":false,`"options`":{`"num_predict`":1,`"num_gpu`":$numGpu}}"
    try {
        Invoke-WebRequest -Uri "http://localhost:11434/api/generate" `
            -Method POST -Body $warmupBody -ContentType "application/json" `
            -TimeoutSec 120 -ErrorAction Stop | Out-Null
        Write-Host "[LCCA] Modele charge (warm-up OK)." -ForegroundColor Green
    } catch {
        Write-Host "[LCCA] Warm-up ignore (modele charge au premier appel)." -ForegroundColor DarkGray
    }
} else {
    Write-Host "[LCCA] $Model absent. Pull en cours..." -ForegroundColor Yellow
    ollama pull $Model
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[LCCA] Echec du pull $Model." -ForegroundColor Red
        Write-Host "[LCCA] Ollama tourne mais sans modele actif valide." -ForegroundColor Yellow
    } else {
        Write-Host "[LCCA] $Model telecharge avec succes." -ForegroundColor Green
    }
}

# ==========================================
#  ETAT FINAL
# ==========================================
Write-Host ""
Write-Host "[LCCA] Ollama tourne (PID $($ollamaProc.Id))" -ForegroundColor Green
Write-Host "[LCCA] Mode   : $Mode | Modele : $Model" -ForegroundColor Green
Write-Host "[LCCA] Config : $modeDesc" -ForegroundColor DarkGray
Write-Host "[LCCA] Fichier modele actif : $ActiveModelFile" -ForegroundColor DarkGray
Write-Host "[LCCA] Ctrl+C pour arreter." -ForegroundColor DarkGray
Write-Host ""

# ==========================================
#  ATTENTE (jusqu'au Ctrl+C)
# ==========================================
try {
    $ollamaProc.WaitForExit()
} finally {
    Stop-Process -Id $ollamaProc.Id -Force -ErrorAction SilentlyContinue
    Remove-Item -Path $ActiveModelFile -ErrorAction SilentlyContinue
    Write-Host "[LCCA] Ollama arrete." -ForegroundColor Yellow
}

