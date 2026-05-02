# setup_models.ps1 - Migration modeles LCCA (2026-04-24)
# Supprime les anciens modeles qwen2.5/deepseek-coder/llama3.2
# Puis pull qwen3:8b, qwen3:14b, deepseek-r1:14b
# Garde : nomic-embed-text (embeddings ChromaDB/MemPalace)
# Usage : .\setup_models.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = "SilentlyContinue"

# ==========================================
#  VERIFICATION OLLAMA
# ==========================================
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  LCCA - Migration modeles Ollama" -ForegroundColor Cyan
Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm')" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

try {
    Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 3 -ErrorAction Stop | Out-Null
    Write-Host "[OK] Ollama repond." -ForegroundColor Green
} catch {
    Write-Host "[ERREUR] Ollama ne repond pas. Lance d'abord : .\start-ollama.ps1" -ForegroundColor Red
    exit 1
}

# ==========================================
#  MODELES A SUPPRIMER
# ==========================================
$ToRemove = @(
    "qwen2.5-coder:3b"
    "qwen2.5-coder:7b"
    "qwen2.5-coder:14b"
    "deepseek-coder:6.7b"
    "llama3.2:3b"
    "llama3.2:latest"
)

Write-Host ""
Write-Host "-- SUPPRESSION DES ANCIENS MODELES ------" -ForegroundColor Yellow
foreach ($model in $ToRemove) {
    Write-Host "  Suppression : $model ..." -NoNewline
    ollama rm $model 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host " OK" -ForegroundColor Green
    } else {
        Write-Host " (absent, ignore)" -ForegroundColor DarkGray
    }
}

# ==========================================
#  VERIFICATION ESPACE DISQUE
# ==========================================
Write-Host ""
Write-Host "-- ESPACE DISQUE -------------------------" -ForegroundColor Cyan
$disk = Get-PSDrive D
$freeGB = [math]::Round($disk.Free / 1GB, 1)
Write-Host "  Libre sur D:\ : $freeGB GB" -ForegroundColor White
if ($freeGB -lt 25) {
    Write-Host "[WARN] Moins de 25 GB libres. Les pulls risquent d'echouer." -ForegroundColor Yellow
}

# ==========================================
#  MODELES A PULLER
# ==========================================
$ToPull = @(
    [PSCustomObject]@{
        Name  = "qwen3:8b"
        Label = "Qwen3 8B -- nouveau defaut LCCA (~5.5 GB)"
        Color = "Green"
    }
    [PSCustomObject]@{
        Name  = "qwen3:14b"
        Label = "Qwen3 14B -- qualite++ RAM CPU (~9 GB)"
        Color = "Cyan"
    }
    [PSCustomObject]@{
        Name  = "deepseek-r1:14b"
        Label = "DeepSeek R1 14B -- debug/reasoning (~9 GB)"
        Color = "Magenta"
    }
)

Write-Host ""
Write-Host "-- PULL DES NOUVEAUX MODELES -------------" -ForegroundColor Green
Write-Host "  Total a telecharger : ~23.5 GB" -ForegroundColor White
Write-Host ""

foreach ($m in $ToPull) {
    Write-Host "  [PULL] $($m.Label)" -ForegroundColor $m.Color
    ollama pull $m.Name
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] $($m.Name) telecharge." -ForegroundColor Green
    } else {
        Write-Host "  [ERREUR] Pull $($m.Name) echoue." -ForegroundColor Red
    }
    Write-Host ""
}

# ==========================================
#  ETAT FINAL
# ==========================================
Write-Host ""
Write-Host "-- MODELES INSTALLES ---------------------" -ForegroundColor Cyan
ollama list

$disk2  = Get-PSDrive D
$freeGB2 = [math]::Round($disk2.Free / 1GB, 1)
Write-Host ""
Write-Host "  Espace libre restant sur D:\ : $freeGB2 GB" -ForegroundColor White
Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "  Migration terminee !" -ForegroundColor Green
Write-Host "  Prochaine etape : .\run_benchmark_all_models.ps1 -Quick" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
