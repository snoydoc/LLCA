# start-ollama-cpu.ps1 - Ollama en mode CPU pur (pas de GPU)
# BENCHMARK MODE 1/3 : CPU only

Set-StrictMode -Version Latest
$ErrorActionPreference = "SilentlyContinue"

Write-Host "[BENCH] Arret des instances Ollama existantes..." -ForegroundColor Yellow
Get-Process | Where-Object { $_.Name -like "*ollama*" } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3

# Mode CPU pur : on cache completement le GPU
$env:OLLAMA_MODELS        = "D:\Continue\Ollama\models"
$env:OLLAMA_NEW_ENGINE    = "0"
$env:OLLAMA_NUM_GPU       = "0"
$env:CUDA_VISIBLE_DEVICES = "NoDevFiles"

Write-Host ""
Write-Host "==========================================" -ForegroundColor Blue
Write-Host "  BENCHMARK MODE [1/3] : CPU ONLY" -ForegroundColor Blue
Write-Host "==========================================" -ForegroundColor Blue
Write-Host "  GPU         : DESACTIVE" -ForegroundColor White
Write-Host "  OLLAMA_NUM_GPU=0" -ForegroundColor Gray
Write-Host "  CUDA_VISIBLE_DEVICES=NoDevFiles" -ForegroundColor Gray
Write-Host ""
Write-Host "[OK] Demarrage Ollama CPU... (Ctrl+C pour arreter)" -ForegroundColor Green
Write-Host ""

ollama serve
