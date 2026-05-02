# start-ollama-hybrid.ps1 - Ollama en mode hybride (CPU + GPU)
# BENCHMARK MODE 3/3 : Hybrid
# Ollama decide automatiquement combien de couches mettre sur le GPU

Set-StrictMode -Version Latest
$ErrorActionPreference = "SilentlyContinue"

Write-Host "[BENCH] Arret des instances Ollama existantes..." -ForegroundColor Yellow
Get-Process | Where-Object { $_.Name -like "*ollama*" } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3

# Mode hybride : on laisse Ollama gerer la repartition CPU/GPU
# On supprime CUDA_VISIBLE_DEVICES pour que le GPU soit visible
Remove-Item Env:CUDA_VISIBLE_DEVICES -ErrorAction SilentlyContinue

$env:OLLAMA_MODELS     = "D:\Continue\Ollama\models"
$env:OLLAMA_NEW_ENGINE = "1"
# On ne fixe pas OLLAMA_NUM_GPU -> Ollama calcule automatiquement
# selon la VRAM disponible (4 GB sur Quadro M2000M)

Write-Host ""
Write-Host "==========================================" -ForegroundColor Yellow
Write-Host "  BENCHMARK MODE [3/3] : HYBRID" -ForegroundColor Yellow
Write-Host "==========================================" -ForegroundColor Yellow
Write-Host "  GPU         : Quadro M2000M (PARTAGE)" -ForegroundColor White
Write-Host "  OLLAMA_NUM_GPU=auto (Ollama decide)" -ForegroundColor Gray
Write-Host "  CUDA_VISIBLE_DEVICES=non defini" -ForegroundColor Gray
Write-Host "  OLLAMA_NEW_ENGINE=1" -ForegroundColor Gray
Write-Host ""
Write-Host "[OK] Demarrage Ollama Hybrid... (Ctrl+C pour arreter)" -ForegroundColor Green
Write-Host ""

ollama serve
