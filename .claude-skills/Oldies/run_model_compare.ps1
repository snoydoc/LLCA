# run_model_compare.ps1 - Benchmark 3b vs 7b sur GPU (V9-02)
# Compare qwen2.5-coder:3b (full VRAM) vs qwen2.5-coder:7b (hybride CPU+GPU)
# Prerequis : Ollama deja lance en mode GPU via .\start-ollama.ps1
# Usage :
#   .\run_model_compare.ps1          -> 6 prompts, 2 runs chacun
#   .\run_model_compare.ps1 -Quick   -> 2 prompts, 1 run chacun

param([switch]$Quick)

$python     = "$PSScriptRoot\CPUVsGPU\.venv\Scripts\python.exe"
$srcDir     = "$PSScriptRoot\CPUVsGPU"
$resultsDir = "$PSScriptRoot\CPUVsGPU\results"
$model3b    = "qwen2.5-coder:3b"
$model7b    = "qwen2.5-coder:7b"

# Verifier l'environnement virtuel
if (-not (Test-Path $python)) {
    Write-Host "[ERREUR] Environnement virtuel CPUVsGPU non trouve." -ForegroundColor Red
    Write-Host "         Lance d'abord : cd CPUVsGPU && .\setup.ps1" -ForegroundColor Gray
    exit 1
}

# Verifier qu'Ollama repond
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  V9-02 : Benchmark 3b vs 7b (GPU)" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Mode     : GPU (Ollama deja demarre)" -ForegroundColor White
Write-Host "  3b       : $model3b (~2.0 GB, full VRAM)" -ForegroundColor White
Write-Host "  7b       : $model7b (~4.4 GB, hybride)" -ForegroundColor White
Write-Host "  Rapide   : $(if ($Quick) { 'Oui (2 prompts, 1 run)' } else { 'Non (6 prompts, 2 runs)' })" -ForegroundColor White
Write-Host ""

Write-Host "[V9-02] Verification Ollama..." -ForegroundColor Gray
try {
    Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 5 -ErrorAction Stop | Out-Null
    Write-Host "[V9-02] Ollama repond. OK" -ForegroundColor Green
} catch {
    Write-Host "[ERREUR] Ollama ne repond pas sur :11434." -ForegroundColor Red
    Write-Host "         Lance d'abord : .\start-ollama.ps1" -ForegroundColor Gray
    exit 1
}

Write-Host ""

# Fonction benchmark d'un modele
function Run-ModelBenchmark {
    param([string]$Model, [string]$Label, [string]$Color)

    Write-Host "------------------------------------------" -ForegroundColor $Color
    Write-Host "  $Label" -ForegroundColor $Color
    Write-Host "------------------------------------------" -ForegroundColor $Color

    $quickArg = if ($Quick) { "--quick" } else { "" }

    Push-Location $srcDir
    if ($Quick) {
        $output = & $python -m src.main --mode gpu --model $Model --quick 2>&1
    } else {
        # 2 runs au lieu de 3 pour un benchmark comparatif raisonnable
        $output = & $python -m src.main --mode gpu --model $Model 2>&1
    }
    Pop-Location

    # Extraire la ligne "Moyenne globale"
    $avgLine = $output | Select-String "Moyenne globale"
    $tokS = if ($avgLine) {
        ($avgLine.Line -replace ".*:\s*", "").Trim()
    } else {
        "N/A"
    }

    Write-Host ($output -join "`n") -ForegroundColor Gray
    return $tokS
}

# Benchmark 3b
Write-Host "[V9-02] Appuie sur ENTREE pour demarrer le benchmark $model3b..." -ForegroundColor Yellow
Read-Host
$result3b = Run-ModelBenchmark -Model $model3b -Label "qwen2.5-coder:3b (full VRAM)" -Color "Green"

Write-Host ""
Start-Sleep -Seconds 3

# Benchmark 7b
Write-Host "[V9-02] Appuie sur ENTREE pour demarrer le benchmark $model7b..." -ForegroundColor Yellow
Read-Host
$result7b = Run-ModelBenchmark -Model $model7b -Label "qwen2.5-coder:7b (hybride)" -Color "Yellow"

# Rapport comparatif
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  RESULTATS V9-02 : 3b vs 7b (GPU)" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ("  {0,-30} : {1}" -f "qwen2.5-coder:3b (full VRAM)", $result3b) -ForegroundColor Green
Write-Host ("  {0,-30} : {1}" -f "qwen2.5-coder:7b (hybride)",   $result7b) -ForegroundColor Yellow
Write-Host ""
Write-Host "  Rappel benchmark 21/04/2026 :" -ForegroundColor Gray
Write-Host "    llama3.2:3b GPU  = 11.34 tok/s" -ForegroundColor Gray
Write-Host "    llama3.2:3b CPU  =  8.03 tok/s" -ForegroundColor Gray
Write-Host ""
Write-Host "  Resultats sauvegardes dans : $resultsDir\" -ForegroundColor Cyan
Write-Host ""
Write-Host "  -> Mettre a jour 002-tech-context.md avec ces chiffres !" -ForegroundColor Magenta
Write-Host ""
