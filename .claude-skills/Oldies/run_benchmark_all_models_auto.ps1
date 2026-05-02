# run_benchmark_all_models.ps1 - Benchmark multi-modeles LCCA
# Cycle propre : stop Ollama -> start -> charge modele -> benchmark -> stop -> suivant
# Usage :
#   .\run_benchmark_all_models.ps1              -> tous les modeles, 6 prompts
#   .\run_benchmark_all_models.ps1 -Quick       -> 2 prompts, 1 run (test rapide)
#   .\run_benchmark_all_models.ps1 -Models "3b,14b"  -> seulement 3b et 14b

param(
    [switch]$Quick,
    [string]$Models = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "SilentlyContinue"

$python     = "$PSScriptRoot\CPUVsGPU\.venv\Scripts\python.exe"
$srcDir     = "$PSScriptRoot\CPUVsGPU"
$resultsDir = "$PSScriptRoot\CPUVsGPU\results"

# ==========================================
#  MODELES A BENCHMARKER -- MIS A JOUR 2026-04-25
#  TOUS les modeles inclus -- aucun exclu a priori.
#  Critere final : meilleur resultat global (qualite + vitesse), pas vitesse seule.
#
#  Historique benchmarks LCCA :
#    qwen2.5-coder:3b  = 10.87 tok/s full GPU  [baseline prod]
#    qwen3:8b          =  3.23 tok/s hybride
#    qwen3:14b         =  1.79 tok/s hybride   VRAM 2935 MB
#    deepseek-r1:14b   =  1.66 tok/s hybride   VRAM 3005 MB
#    qwen3:30b-a3b     =  5.31 tok/s MoE
# ==========================================
$AllModels = @(

    # --- FULL GPU (~2.5-3.5 GB VRAM) ---
    [PSCustomObject]@{ Name = "qwen3:4b";            Label = "Qwen3 4B               thinking mode  ~2.7 GB VRAM"; Color = "Green" }
    [PSCustomObject]@{ Name = "gemma3:4b";           Label = "Gemma3 4B              Google         ~3.0 GB VRAM"; Color = "Cyan" }
    [PSCustomObject]@{ Name = "phi4-mini";           Label = "Phi4-Mini 3.8B         Microsoft      ~3.0 GB VRAM"; Color = "DarkYellow" }
    [PSCustomObject]@{ Name = "phi4-mini:reasoning"; Label = "Phi4-Mini Reasoning    CoT dedie      ~3.0 GB VRAM"; Color = "DarkYellow" }

    # --- HYBRIDE (~4-6 GB VRAM) ---
    [PSCustomObject]@{ Name = "deepseek-r1:8b";      Label = "DeepSeek-R1 8B (0528)  reasoning      ~5.2 GB VRAM"; Color = "Magenta" }
    [PSCustomObject]@{ Name = "qwen3:8b";            Label = "Qwen3 8B               dense          ~5.5 GB VRAM"; Color = "Yellow" }

    # --- LOURDS / QUALITE ---
    [PSCustomObject]@{ Name = "qwen3:14b";           Label = "Qwen3 14B              dense          ~9.0 GB RAM";  Color = "Gray" }
    [PSCustomObject]@{ Name = "deepseek-r1:14b";     Label = "DeepSeek-R1 14B        reasoning      ~9.0 GB RAM";  Color = "Gray" }
    [PSCustomObject]@{ Name = "qwen3:30b-a3b";       Label = "Qwen3 30B-A3B          MoE 3B actifs  ~18 GB RAM";  Color = "DarkGray" }
)

# ==========================================
#  VARIABLES ENV GPU
# ==========================================
$env:OLLAMA_MODELS        = "D:\Continue\Ollama\models"
$env:OLLAMA_NEW_ENGINE    = "1"
$env:OLLAMA_NUM_GPU       = "99"
$env:CUDA_VISIBLE_DEVICES = "0"

# ==========================================
#  VERIFICATION PREREQUIS
# ==========================================
if (-not (Test-Path $python)) {
    Write-Host "[ERREUR] Environnement virtuel CPUVsGPU non trouve." -ForegroundColor Red
    Write-Host "         Lance d'abord : cd CPUVsGPU && .\setup.ps1" -ForegroundColor Gray
    exit 1
}

# ==========================================
#  FONCTIONS CYCLE OLLAMA
# ==========================================
function Stop-OllamaClean {
    Write-Host "  [stop] Arret Ollama..." -ForegroundColor DarkGray
    taskkill /F /IM ollama.exe /T 2>$null | Out-Null
    taskkill /F /IM ollama_llm_server.exe /T 2>$null | Out-Null
    Start-Sleep -Seconds 2

    # Fallback : tuer le process qui tient encore :11434 (runner CUDA survivant)
    $netLines = netstat -ano 2>$null | Select-String ":11434\s"
    foreach ($line in $netLines) {
        $parts = ($line.Line.Trim() -split "\s+")
        $pid = $parts[-1]
        if ($pid -match "^\d+$" -and $pid -ne "0") {
            Write-Host "  [stop] Kill PID $pid (tenait :11434)" -ForegroundColor DarkGray
            taskkill /F /PID $pid /T 2>$null | Out-Null
        }
    }
    Start-Sleep -Seconds 1

    # Attente liberation port 11434 (max 25s)
    for ($i = 0; $i -lt 25; $i++) {
        if (-not (netstat -ano 2>$null | Select-String ":11434\s")) {
            Write-Host "  [stop] Port 11434 libre." -ForegroundColor DarkGray
            return $true
        }
        Start-Sleep -Seconds 1
    }
    Write-Host "  [WARN] Port 11434 toujours occupe apres 25s -- on continue quand meme" -ForegroundColor Yellow
    return $false
}

function Start-OllamaForModel {
    param([string]$ModelName)

    Write-Host "  [start] Demarrage Ollama..." -ForegroundColor DarkGray
    $proc = Start-Process -FilePath "ollama" -ArgumentList "serve" -PassThru -NoNewWindow

    # Attendre que le port reponde (max 30s)
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 11434 -WarningAction SilentlyContinue
        if ($tcp.TcpTestSucceeded) { $ready = $true; break }
    }
    if (-not $ready) {
        Write-Host "  [ERREUR] Ollama ne repond pas apres 30s" -ForegroundColor Red
        return $null
    }
    Write-Host "  [start] Ollama pret (port 11434 OK)" -ForegroundColor DarkGray

    # Pull si modele absent
    $modelList = ollama list 2>$null
    if (-not ($modelList -match [regex]::Escape($ModelName))) {
        Write-Host "  [pull] $ModelName absent -- telechargement..." -ForegroundColor Yellow
        ollama pull $ModelName
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [ERREUR] Pull $ModelName echoue" -ForegroundColor Red
            return $null
        }
        Write-Host "  [OK] $ModelName telecharge" -ForegroundColor Green
    }

    # Warm-up : force le chargement du modele en RAM/VRAM
    Write-Host "  [warmup] Chargement $ModelName en memoire..." -ForegroundColor DarkGray
    $warmupBody = '{"model":"' + $ModelName + '","prompt":"ok","stream":false,"options":{"num_predict":1}}'
    try {
        Invoke-WebRequest -Uri "http://localhost:11434/api/generate" `
            -Method POST -Body $warmupBody -ContentType "application/json" `
            -TimeoutSec 300 -ErrorAction Stop | Out-Null
        Write-Host "  [warmup] Modele charge." -ForegroundColor DarkGray
    } catch {
        Write-Host "  [WARN] Warm-up timeout -- modele sera charge au premier prompt" -ForegroundColor Yellow
    }

    return $proc
}

# ==========================================
#  HEADER
# ==========================================
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  LCCA - Benchmark multi-modeles" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Prompts  : $(if ($Quick) { '2 (mode rapide)' } else { '6 (complet)' })" -ForegroundColor White
Write-Host "  Runs/pmt : $(if ($Quick) { '1' } else { '3' })" -ForegroundColor White
Write-Host "  Cycle    : stop Ollama -> start -> charge -> bench -> stop" -ForegroundColor White
Write-Host ""

# Filtrer par -Models si fourni
$modelsToRun = $AllModels
if ($Models -ne "") {
    $filter = $Models -split "," | ForEach-Object { $_.Trim() }
    $modelsToRun = $AllModels | Where-Object {
        $name = $_.Name
        $filter | Where-Object { $name -like "*$_*" }
    }
    if ($modelsToRun.Count -eq 0) {
        Write-Host "[ERREUR] Aucun modele correspondant a : $Models" -ForegroundColor Red
        exit 1
    }
}

# Verifier quels modeles sont deja en local (Ollama possiblement inactif = on tente)
$localModels = @()
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 3 -ErrorAction Stop
    $json = $resp.Content | ConvertFrom-Json
    $localModels = $json.models | ForEach-Object { $_.name }
} catch {}

# Afficher le plan
Write-Host "  Modeles a benchmarker :" -ForegroundColor White
foreach ($m in $modelsToRun) {
    $status = if ($localModels -contains $m.Name) { "[local]" } else { "[pull] " }
    $col    = if ($localModels -contains $m.Name) { $m.Color } else { "DarkGray" }
    Write-Host ("    {0} {1}" -f $status, $m.Label) -ForegroundColor $col
}
Write-Host ""
Write-Host "  Appuie sur ENTREE pour demarrer..." -ForegroundColor Yellow
# Read-Host (overnight)

# Kill initial : etat propre avant de commencer
Write-Host ""
Write-Host "  Arret initial Ollama (etat propre)..." -ForegroundColor Yellow
Stop-OllamaClean | Out-Null
Start-Sleep -Seconds 3

# ==========================================
#  BOUCLE PRINCIPALE
# ==========================================
$Results = @()

foreach ($m in $modelsToRun) {

    Write-Host ""
    Write-Host "------------------------------------------" -ForegroundColor $m.Color
    Write-Host "  $($m.Label)" -ForegroundColor $m.Color
    Write-Host "------------------------------------------" -ForegroundColor $m.Color

    # Demarrer Ollama + charger le modele
    $ollamaProc = Start-OllamaForModel -ModelName $m.Name
    if ($null -eq $ollamaProc) {
        Write-Host "  [SKIP] $($m.Name) -- demarrage echoue" -ForegroundColor Red
        $Results += [PSCustomObject]@{ Name = $m.Name; Label = $m.Label; TokS = "ERREUR" }
        continue
    }

    # Lancer le benchmark Python
    Push-Location $srcDir
    if ($Quick) {
        $output = & $python -m src.main --mode gpu --model $m.Name --quick 2>&1
    } else {
        $output = & $python -m src.main --mode gpu --model $m.Name 2>&1
    }
    Pop-Location

    Write-Host ($output -join "`n") -ForegroundColor Gray

    # Extraire la moyenne
    $avgLine = $output | Select-String "Moyenne globale"
    $tokS = if ($avgLine) {
        ($avgLine.Line -replace ".*:\s*", "").Trim()
    } else {
        "N/A"
    }

    $Results += [PSCustomObject]@{
        Name  = $m.Name
        Label = $m.Label
        TokS  = $tokS
    }

    # Stop Ollama avant le modele suivant
    Write-Host ""
    Write-Host "  [>] Arret Ollama (liberation RAM)..." -ForegroundColor DarkGray
    Stop-OllamaClean | Out-Null
    Start-Sleep -Seconds 5
}

# ==========================================
#  RAPPORT FINAL
# ==========================================
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  RESULTATS BENCHMARK MULTI-MODELES" -ForegroundColor Cyan
Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm')" -ForegroundColor Cyan
Write-Host "  Machine : Lenovo P50 | GPU : Quadro M2000M 4 GB" -ForegroundColor Cyan
Write-Host "  RAM     : 24 GB | Ollama GPU mode" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

$maxLabelLen = ($Results | ForEach-Object { $_.Label.Length } | Measure-Object -Maximum).Maximum
foreach ($r in $Results) {
    $col = ($modelsToRun | Where-Object { $_.Name -eq $r.Name }).Color
    if (-not $col) { $col = "White" }
    $padded = $r.Label.PadRight($maxLabelLen + 2)
    Write-Host ("  {0} : {1}" -f $padded, $r.TokS) -ForegroundColor $col
}

Write-Host ""
Write-Host "  Rappel historique benchmarks LCCA :" -ForegroundColor Gray
Write-Host "    [baseline 21/04]  qwen2.5-coder:3b   GPU full  = 10.87 tok/s" -ForegroundColor DarkGray
Write-Host "    [baseline 24/04]  qwen3:8b           GPU hybr. =  3.23 tok/s" -ForegroundColor DarkGray
Write-Host "    [mesure 25/04]    qwen3:14b          GPU hybr. =  1.79 tok/s  RAM ~18 GB  VRAM 2935 MB" -ForegroundColor DarkGray
Write-Host "    [mesure 25/04]    deepseek-r1:14b    GPU hybr. =  1.66 tok/s  RAM ~17.5 GB VRAM 3005 MB" -ForegroundColor DarkGray
Write-Host "    [en cours 25/04]  qwen3:30b-a3b      telechargement 1.2/18 GB" -ForegroundColor DarkGray
Write-Host ""

# Sauvegarde rapport texte
$timestamp  = Get-Date -Format "yyyyMMdd_HHmm"
$reportFile = "$resultsDir\benchmark_multimodel_$timestamp.txt"
New-Item -ItemType Directory -Force -Path $resultsDir | Out-Null

$lines = @(
    "BENCHMARK MULTI-MODELES LCCA"
    "Date     : $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    "Machine  : Lenovo P50 | Quadro M2000M 4 GB VRAM | 24 GB RAM"
    "Mode     : GPU (Ollama) -- cycle stop/start propre par modele"
    "Prompts  : $(if ($Quick) { '2 (rapide)' } else { '6 (complet)' })"
    ""
    "RESULTATS"
    "---------"
)
foreach ($r in $Results) {
    $lines += ("  {0} : {1}" -f $r.Label.PadRight(50), $r.TokS)
}
$lines += ""
$lines += "HISTORIQUE BENCHMARKS LCCA"
$lines += "  [baseline 21/04] qwen2.5-coder:3b   GPU full  = 10.87 tok/s"
$lines += "  [baseline 24/04] qwen3:8b           GPU hybr. =  3.23 tok/s"
$lines += "  [mesure  25/04]  qwen3:14b          GPU hybr. =  1.79 tok/s  RAM ~18 GB   VRAM 2935 MB  CPU 40-43%"
$lines += "  [mesure  25/04]  deepseek-r1:14b    GPU hybr. =  1.66 tok/s  RAM ~17.5 GB VRAM 3005 MB  CPU 38-39%"
$lines += "  [en cours 25/04] qwen3:30b-a3b      telechargement en cours (1.2/18 GB)"

$lines | Out-File -FilePath $reportFile -Encoding UTF8
Write-Host "  Rapport sauvegarde : $reportFile" -ForegroundColor Cyan
Write-Host ""
Write-Host "  -> Mettre a jour 002-context.md avec les nouveaux chiffres !" -ForegroundColor Magenta
Write-Host ""
