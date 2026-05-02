# run_benchmark.ps1 - Lance le benchmark CPU vs GPU vs Hybrid
# Doit etre lance depuis D:\LLMCodeAgent\CPUVsGPU\
# Usage :
#   .\run_benchmark.bat          -> benchmark complet (3 modes)
#   .\run_benchmark.bat quick    -> test rapide (2 prompts, 1 run)

param(
    [ValidateSet("cpu", "gpu", "hybrid", "all")]
    [string]$Mode = "all",
    [switch]$Quick
)

$python  = "$PSScriptRoot\.venv\Scripts\python.exe"
$scripts = "$PSScriptRoot\scripts"

if (-not (Test-Path $python)) {
    Write-Host "[ERREUR] Environnement virtuel non trouve. Lance d'abord : .\setup.bat" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "        BENCHMARK OLLAMA - CPU vs GPU vs Hybrid       " -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host ""

function Wait-Ollama {
    param([string]$modeName)
    Write-Host "  Verification Ollama mode $modeName..." -ForegroundColor Gray
    for ($i = 0; $i -lt 12; $i++) {
        try {
            Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 3 -ErrorAction Stop | Out-Null
            Write-Host "  [OK] Ollama repond !" -ForegroundColor Green
            return $true
        } catch {
            Write-Host "  Attente ($($i+1)/12)..." -ForegroundColor Gray
            Start-Sleep 5
        }
    }
    Write-Host "  [ERREUR] Ollama ne repond pas apres 60s" -ForegroundColor Red
    return $false
}

function Run-Mode {
    param([string]$mode)

    $scriptMap = @{
        "cpu"    = "$scripts\start-ollama-cpu.ps1"
        "gpu"    = "$scripts\start-ollama-gpu.ps1"
        "hybrid" = "$scripts\start-ollama-hybrid.ps1"
    }
    $colorMap = @{
        "cpu"    = "Blue"
        "gpu"    = "Green"
        "hybrid" = "Yellow"
    }

    $scriptPath = $scriptMap[$mode]
    $color      = $colorMap[$mode]

    Write-Host ""
    Write-Host "------------------------------------------------------" -ForegroundColor $color
    Write-Host "  MODE $($mode.ToUpper())" -ForegroundColor $color
    Write-Host "------------------------------------------------------" -ForegroundColor $color
    Write-Host ""
    Write-Host "  Une nouvelle fenetre va ouvrir Ollama en mode $($mode.ToUpper())." -ForegroundColor White
    Write-Host "  Ne la ferme pas pendant le test !" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Appuie sur ENTREE pour continuer..." -ForegroundColor Yellow
    Read-Host

    # Ouvre Ollama dans une nouvelle fenetre
    Start-Process powershell.exe -ArgumentList "-ExecutionPolicy Bypass -File `"$scriptPath`""

    # Laisser le temps a Ollama de demarrer
    Start-Sleep 5

    if (-not (Wait-Ollama -modeName $mode)) {
        Write-Host "  [SKIP] Mode $mode ignore" -ForegroundColor Red
        return $false
    }

    Write-Host ""
    Write-Host "  Lancement des tests $($mode.ToUpper())..." -ForegroundColor $color
    Write-Host ""

    # On se place dans le bon dossier pour que -m src.main fonctionne
    Push-Location $PSScriptRoot
    if ($Quick) {
        & $python -m src.main --mode $mode --quick
    } else {
        & $python -m src.main --mode $mode
    }
    Pop-Location

    return $true
}

$modes = if ($Mode -eq "all") { @("cpu", "gpu", "hybrid") } else { @($Mode) }

Write-Host "  Modes    : $($modes -join ' -> ')" -ForegroundColor White
Write-Host "  Rapide   : $(if ($Quick) { 'Oui (2 prompts)' } else { 'Non (6 prompts)' })" -ForegroundColor White
Write-Host ""

foreach ($m in $modes) {
    Run-Mode -mode $m
}

Write-Host ""
Write-Host "======================================" -ForegroundColor Green
Write-Host "  BENCHMARK TERMINE !" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Green
Write-Host "  Resultats : $PSScriptRoot\results\" -ForegroundColor Cyan
Write-Host ""
