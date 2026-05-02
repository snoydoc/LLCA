# run_benchmark_all_models.ps1 - Benchmark sequentiel de tous les modeles en mode GPU
# Usage : .\scripts\run_benchmark_all_models.ps1
#         .\scripts\run_benchmark_all_models.ps1 -Quick
#         .\scripts\run_benchmark_all_models.ps1 -Models @("qwen3:4b","gemma4:e4b")
#
# Prerequis : Ollama doit etre demarre en mode GPU (start-ollama-gpu.ps1)
# ASCII pur - pas d'accents dans ce fichier

param(
    [switch]$Quick,
    [string[]]$Models = @(
        "qwen2.5-coder:3b",
        "qwen3:4b",
        "gemma4:e4b",
        "gemma4:e2b",
        "phi4-mini",
        "phi4-mini-reasoning",
        "deepseek-r1:8b",
        "deepseek-coder:6.7b"
    )
)

$python   = "$PSScriptRoot\..\venv\Scripts\python.exe"
$mainPy   = "$PSScriptRoot\..\src\main.py"
$results  = "$PSScriptRoot\..\results"

# Fallback vers le venv du projet benchmark si le venv LCCA n est pas trouve
if (-not (Test-Path $python)) {
    $python = "$PSScriptRoot\..\.venv\Scripts\python.exe"
}
if (-not (Test-Path $python)) {
    Write-Host "[ERREUR] Python introuvable. Verifie le venv." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  BENCHMARK MULTI-MODELES (GPU MODE)" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Python   : $python" -ForegroundColor Gray
Write-Host "  Rapide   : $(if ($Quick) { 'Oui (2 prompts)' } else { 'Non (6 prompts)' })" -ForegroundColor Gray
Write-Host "  Modeles  : $($Models.Count) modeles" -ForegroundColor Gray
Write-Host ""

# Verification qu Ollama repond
function Test-Ollama {
    try {
        Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 3 -ErrorAction Stop | Out-Null
        return $true
    } catch {
        return $false
    }
}

if (-not (Test-Ollama)) {
    Write-Host "[ERREUR] Ollama ne repond pas sur :11434" -ForegroundColor Red
    Write-Host "  Lance d abord : .\scripts\start-ollama-gpu.ps1" -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK] Ollama repond" -ForegroundColor Green

# Pull des modeles manquants
Write-Host ""
Write-Host "-- Verification des modeles disponibles --" -ForegroundColor Cyan
foreach ($model in $Models) {
    Write-Host "  Verification : $model" -ForegroundColor Gray
    $tags = (Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 5).Content | ConvertFrom-Json
    $found = $tags.models | Where-Object { $_.name -eq $model }
    if (-not $found) {
        Write-Host "  [PULL] $model manquant, telechargement..." -ForegroundColor Yellow
        ollama pull $model
    } else {
        Write-Host "  [OK] $model present" -ForegroundColor Green
    }
}

# Benchmark de chaque modele
$summary = @()
$startAll = Get-Date

foreach ($model in $Models) {
    Write-Host ""
    Write-Host "==========================================" -ForegroundColor Yellow
    Write-Host "  MODELE : $model" -ForegroundColor Yellow
    Write-Host "==========================================" -ForegroundColor Yellow

    $startModel = Get-Date

    Push-Location "$PSScriptRoot\.."
    if ($Quick) {
        & $python -m src.main --mode gpu --quick --model $model
    } else {
        & $python -m src.main --mode gpu --model $model
    }
    Pop-Location

    $elapsed = (Get-Date) - $startModel
    Write-Host "  Duree : $([math]::Round($elapsed.TotalSeconds, 1)) s" -ForegroundColor Gray

    # Lire le dernier fichier JSON produit pour extraire le tok/s
    $lastJson = Get-ChildItem "$results\benchmark_gpu_*.json" | Sort-Object LastWriteTime | Select-Object -Last 1
    if ($lastJson) {
        $data = Get-Content $lastJson.FullName | ConvertFrom-Json
        $tokS = $data.overall_avg_tok_s
        $vram = $data.results[0].runs[0].system.vram_avg_mb
        $summary += [PSCustomObject]@{
            Model     = $model
            TokPerSec = $tokS
            VRAM_MB   = $vram
            Duration  = [math]::Round($elapsed.TotalSeconds, 1)
        }
        Write-Host "  Resultat : $tokS tok/s | VRAM $vram MB" -ForegroundColor Cyan
    }

    # Pause courte entre les modeles pour laisser Ollama se stabiliser
    Start-Sleep -Seconds 5
}

# Resume final
$totalElapsed = (Get-Date) - $startAll
Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "  RESUME FINAL - TOUS LES MODELES" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host ("  {0,-30} {1,9}  {2,8}" -f "Modele", "tok/s", "VRAM MB") -ForegroundColor White
Write-Host ("  " + "-" * 52) -ForegroundColor Gray
$summary | Sort-Object TokPerSec -Descending | ForEach-Object {
    $line = "  {0,-30} {1,9:F2}  {2,8:F0}" -f $_.Model, $_.TokPerSec, $_.VRAM_MB
    Write-Host $line -ForegroundColor Cyan
}
Write-Host ""
Write-Host "  Duree totale : $([math]::Round($totalElapsed.TotalMinutes, 1)) min" -ForegroundColor Gray
Write-Host "  Resultats : $results\" -ForegroundColor Cyan
Write-Host ""

# Sauvegarder le resume dans un fichier CSV
$csvPath = "$results\summary_$(Get-Date -Format 'yyyyMMdd_HHmmss').csv"
$summary | Export-Csv -Path $csvPath -NoTypeInformation -Encoding UTF8
Write-Host "[OK] Resume CSV : $csvPath" -ForegroundColor Green
