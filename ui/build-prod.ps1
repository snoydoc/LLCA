# build-prod.ps1 — PROD-01 : Build Windows de l'application Adham Desktop
# Usage : cd D:\LLMCodeAgent\ui ; .\build-prod.ps1
# Prérequis : Node.js >= 18, npm, Pillow (pip install Pillow)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$UI_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $UI_DIR

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Adham Desktop — Build PROD-01" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# ── Étape 1 : Vérifier l'icône ICO ──────────────────────────────────────────
Write-Host "[1/5] Vérification de l'icône..." -ForegroundColor Yellow
$icoPath = Join-Path $UI_DIR "assets\AdhamDesktop.ico"
if (-not (Test-Path $icoPath)) {
    Write-Host "      ⚠  AdhamDesktop.ico manquant — tentative de conversion depuis PNG..." -ForegroundColor Yellow
    $pngPath = Join-Path $UI_DIR "assets\AdhamDesktop.png"
    if (Test-Path $pngPath) {
        python (Join-Path $UI_DIR "make_ico.py")
        if ($LASTEXITCODE -ne 0) {
            Write-Host "      ❌ Conversion ICO échouée. Installez Pillow : pip install Pillow" -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Host "      ❌ assets\AdhamDesktop.png introuvable." -ForegroundColor Red
        exit 1
    }
}
Write-Host "      ✅ AdhamDesktop.ico OK" -ForegroundColor Green

# ── Étape 2 : npm install ────────────────────────────────────────────────────
Write-Host "[2/5] Vérification des dépendances npm..." -ForegroundColor Yellow
if (-not (Test-Path (Join-Path $UI_DIR "node_modules"))) {
    Write-Host "      Installation des dépendances npm..." -ForegroundColor White
    npm install
    if ($LASTEXITCODE -ne 0) { Write-Host "      ❌ npm install échoué" -ForegroundColor Red; exit 1 }
}
Write-Host "      ✅ node_modules OK" -ForegroundColor Green

# ── Étape 3 : Build electron-vite ───────────────────────────────────────────
Write-Host "[3/5] Compilation TypeScript + React (electron-vite build)..." -ForegroundColor Yellow
npm run build
if ($LASTEXITCODE -ne 0) {
    Write-Host "      ❌ Build échoué. Voir erreurs ci-dessus." -ForegroundColor Red
    exit 1
}
Write-Host "      ✅ Build OK → out/" -ForegroundColor Green

# ── Étape 4 : electron-builder dist ─────────────────────────────────────────
Write-Host "[4/5] Packaging Windows (electron-builder --win)..." -ForegroundColor Yellow
Write-Host "      Cette étape peut prendre 2-5 minutes (téléchargement binaires Electron)." -ForegroundColor Gray
npm run dist
if ($LASTEXITCODE -ne 0) {
    Write-Host "      ❌ electron-builder échoué. Voir erreurs ci-dessus." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Solutions courantes :" -ForegroundColor Yellow
    Write-Host "  - Erreur ICO  → vérifier assets\AdhamDesktop.ico (format valide)" -ForegroundColor White
    Write-Host "  - Erreur NSIS → installer NSIS : https://nsis.sourceforge.io" -ForegroundColor White
    Write-Host "  - Erreur réseau → utiliser npm run dist:dir (sans installeur)" -ForegroundColor White
    exit 1
}
Write-Host "      ✅ Packaging OK" -ForegroundColor Green

# ── Étape 5 : Résultat ──────────────────────────────────────────────────────
Write-Host "[5/5] Résultat..." -ForegroundColor Yellow
$distDir = Join-Path $UI_DIR "dist"
if (Test-Path $distDir) {
    $exes = Get-ChildItem $distDir -Filter "*.exe" | Sort-Object LastWriteTime -Descending
    if ($exes.Count -gt 0) {
        Write-Host ""
        Write-Host "  ✅✅ BUILD RÉUSSI !" -ForegroundColor Green
        Write-Host ""
        foreach ($exe in $exes) {
            $sizeMB = [math]::Round($exe.Length / 1MB, 1)
            Write-Host "  📦 $($exe.Name) ($sizeMB MB)" -ForegroundColor Cyan
            Write-Host "     $($exe.FullName)" -ForegroundColor Gray
        }
    } else {
        $dirs = Get-ChildItem $distDir -Directory
        Write-Host ""
        Write-Host "  ✅ BUILD RÉUSSI (mode --dir, pas d'installeur)" -ForegroundColor Green
        foreach ($d in $dirs) {
            Write-Host "  📁 $($d.Name) — $($d.FullName)" -ForegroundColor Cyan
        }
    }
}
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
