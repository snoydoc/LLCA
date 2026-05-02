# setup.ps1 - Installation de l'environnement CPUVsGPU
# Lance ce script une seule fois pour tout preparer

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  SETUP CPUVsGPU - Benchmark Ollama" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Etape 1 : Verifier Python
Write-Host "Etape 1/4 : Verification de Python..." -ForegroundColor Yellow

$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3\.[9-9]|Python 3\.1[0-9]") {
            $pythonCmd = $cmd
            Write-Host "  [OK] $ver trouve ($cmd)" -ForegroundColor Green
            break
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Host "  [ERREUR] Python 3.9+ non trouve !" -ForegroundColor Red
    Write-Host "  Installe Python depuis : https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

# Etape 2 : Creer l'environnement virtuel
Write-Host ""
Write-Host "Etape 2/4 : Creation de l'environnement virtuel..." -ForegroundColor Yellow

if (Test-Path ".venv") {
    Write-Host "  [INFO] .venv existe deja, on le reutilise" -ForegroundColor Cyan
} else {
    & $pythonCmd -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERREUR] Creation venv echouee" -ForegroundColor Red
        exit 1
    }
    Write-Host "  [OK] Environnement virtuel cree (.venv)" -ForegroundColor Green
}

# Etape 3 : Installer les dependances
Write-Host ""
Write-Host "Etape 3/4 : Installation des dependances Python..." -ForegroundColor Yellow

$pip = ".\.venv\Scripts\pip.exe"
& $pip install --quiet --upgrade pip
& $pip install --quiet requests psutil rich

if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERREUR] Installation packages echouee" -ForegroundColor Red
    exit 1
}
Write-Host "  [OK] requests, psutil, rich installes" -ForegroundColor Green

# Etape 4 : Verifier Ollama
Write-Host ""
Write-Host "Etape 4/4 : Verification d'Ollama..." -ForegroundColor Yellow

try {
    $response = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 3 -ErrorAction Stop
    Write-Host "  [OK] Ollama repond sur le port 11434" -ForegroundColor Green

    $data = $response.Content | ConvertFrom-Json
    $models = $data.models
    if ($models.Count -gt 0) {
        Write-Host "  [OK] $($models.Count) modele(s) disponible(s) :" -ForegroundColor Green
        foreach ($m in $models) {
            Write-Host "     -> $($m.name)" -ForegroundColor Cyan
        }
    } else {
        Write-Host "  [WARN] Aucun modele - telecharge-en un :" -ForegroundColor Yellow
        Write-Host "     ollama pull mistral:7b-instruct" -ForegroundColor Cyan
        Write-Host "     ollama pull phi3:mini  (plus leger)" -ForegroundColor Cyan
    }
} catch {
    Write-Host "  [WARN] Ollama n'est pas demarre" -ForegroundColor Yellow
    Write-Host "  Lance Ollama depuis le menu demarrer, puis relance ce script" -ForegroundColor Cyan
}

# Resume
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  SETUP TERMINE !" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Prochaines etapes :" -ForegroundColor White
Write-Host ""
Write-Host "  1. Diagnostic complet :" -ForegroundColor Cyan
Write-Host "     .\.venv\Scripts\python src\diag.py" -ForegroundColor White
Write-Host ""
Write-Host "  2. Benchmark rapide :" -ForegroundColor Cyan
Write-Host "     .\run_benchmark.bat quick" -ForegroundColor White
Write-Host ""
Write-Host "  3. Benchmark complet :" -ForegroundColor Cyan
Write-Host "     .\run_benchmark.bat" -ForegroundColor White
Write-Host ""
