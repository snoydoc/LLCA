# LCCA -- Script d'initialisation GitHub
# Exécuter depuis D:\LLMCodeAgent avec : .\init_github.ps1

$ErrorActionPreference = "Stop"
$RepoUrl = "https://github.com/snoydoc/LLCA.git"
$ProjectDir = "D:\LLMCodeAgent"

Set-Location $ProjectDir

Write-Host ""
Write-Host "=== LCCA -- Preparation GitHub ===" -ForegroundColor Cyan
Write-Host "Repo : $RepoUrl" -ForegroundColor Gray
Write-Host ""

# --- Etape 1 : git config (si pas encore configure) ---
$userName = git config user.name 2>$null
$userEmail = git config user.email 2>$null

if (-not $userName) {
    Write-Host "[!] Git user.name non configure." -ForegroundColor Yellow
    $userName = Read-Host "    Votre nom (ex: snoydoc)"
    git config --global user.name $userName
}
if (-not $userEmail) {
    Write-Host "[!] Git user.email non configure." -ForegroundColor Yellow
    $userEmail = Read-Host "    Votre email GitHub"
    git config --global user.email $userEmail
}

Write-Host "[OK] Git config : $userName <$userEmail>" -ForegroundColor Green

# --- Etape 2 : git init ---
if (Test-Path "$ProjectDir\.git") {
    Write-Host "[OK] Depot git existant detecte." -ForegroundColor Green
} else {
    Write-Host "[...] git init" -ForegroundColor Gray
    git init -b main
    Write-Host "[OK] Depot initialise (branche main)." -ForegroundColor Green
}

# --- Etape 3 : remote origin ---
$existingRemote = git remote 2>$null
if ($existingRemote -contains "origin") {
    Write-Host "[OK] Remote 'origin' deja present." -ForegroundColor Green
} else {
    Write-Host "[...] Ajout remote origin" -ForegroundColor Gray
    git remote add origin $RepoUrl
    Write-Host "[OK] Remote origin configure." -ForegroundColor Green
}

# --- Etape 4 : git add ---
Write-Host ""
Write-Host "[...] git add --all (peut prendre quelques secondes...)" -ForegroundColor Gray
git add --all

$status = git status --short | Measure-Object -Line
Write-Host "[OK] $($status.Lines) fichiers en attente de commit." -ForegroundColor Green

# --- Etape 5 : commit initial ---
$date = Get-Date -Format "yyyy-MM-dd HH:mm"
$msg = "chore: backup initial LCCA V10.5 -- $date"

Write-Host "[...] Commit : $msg" -ForegroundColor Gray
git commit -m $msg

# --- Etape 6 : push ---
Write-Host ""
Write-Host "[...] Push vers GitHub (origin main)..." -ForegroundColor Gray
Write-Host "      (Une fenetre d'authentification GitHub peut s'ouvrir)" -ForegroundColor Yellow
Write-Host ""

git push -u origin main

Write-Host ""
Write-Host "=== DONE ===" -ForegroundColor Cyan
Write-Host "Repo disponible : $RepoUrl" -ForegroundColor Green
Write-Host ""
