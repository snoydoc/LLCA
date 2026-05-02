# start-ollama-gpu.ps1 - Ollama en mode GPU pur (Quadro M2000M)
# BENCHMARK MODE 2/3 : GPU only

Set-StrictMode -Version Latest
$ErrorActionPreference = "SilentlyContinue"

Write-Host "[BENCH] Arret des instances Ollama existantes..." -ForegroundColor Yellow
Get-Process | Where-Object { $_.Name -like "*ollama*" } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3

# Mode GPU pur : on force tout sur le GPU, nouveau engine actif
$env:OLLAMA_MODELS        = "D:\Continue\Ollama\models"
$env:OLLAMA_NEW_ENGINE    = "1"
$env:OLLAMA_NUM_GPU       = "99"
$env:CUDA_VISIBLE_DEVICES = "0"

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "  BENCHMARK MODE [2/3] : GPU ONLY" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host "  GPU         : Quadro M2000M (ACTIVE)" -ForegroundColor White
Write-Host "  OLLAMA_NUM_GPU=99" -ForegroundColor Gray
Write-Host "  CUDA_VISIBLE_DEVICES=0" -ForegroundColor Gray
Write-Host "  OLLAMA_NEW_ENGINE=1" -ForegroundColor Gray
Write-Host ""
Write-Host "[OK] Demarrage Ollama GPU... (Ctrl+C pour arreter)" -ForegroundColor Green
Write-Host ""

ollama serve
