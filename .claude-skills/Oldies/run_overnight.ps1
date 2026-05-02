# run_overnight.ps1
# Benchmark interactif : 1 modele, tous, petits, gros, ou overnight.
# Pull automatique des modeles manquants + reprise si interruption.
# Usage : .\run_overnight.ps1
# ASCII pur - pas d accents dans ce fichier

Set-StrictMode -Version Latest
$ErrorActionPreference = "SilentlyContinue"

$ResultsDir   = "$PSScriptRoot\CPUVsGPU\results"
$ProgressFile = "$ResultsDir\overnight_progress.json"
$LogFile      = "$ResultsDir\overnight_$(Get-Date -Format 'yyyyMMdd_HHmm').log"
New-Item -ItemType Directory -Force -Path $ResultsDir | Out-Null

function Log {
    param([string]$Msg, [string]$Color = "White")
    $line = "[$(Get-Date -Format 'HH:mm:ss')] $Msg"
    Write-Host $line -ForegroundColor $Color
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

# ==========================================
#  CATALOGUE COMPLET DES MODELES
#
#  TIER 1 -- Full-GPU (<= 3.5 GB VRAM) -- challengers du qwen2.5-coder:3b
#    gemma4:e2b          ~1.5 GB VRAM  Google Apr2026, ultra-leger
#    qwen3:4b            ~2.7 GB VRAM  successeur naturel du 3b, fenetre 40K
#    phi4-mini           ~3.0 GB VRAM  Microsoft, fort en logique
#    phi4-mini-reasoning ~3.0 GB VRAM  variante chain-of-thought dedié
#    gemma4:e4b          ~3.2 GB VRAM  meilleur ratio qualite/VRAM tier 4B
#    gemma3:4b           ~3.3 GB VRAM  gen precedente Google (reference)
#
#  TIER 2 -- Hybride CPU+GPU (~5.5 GB) -- usage ponctuel
#    deepseek-r1:8b      ~5.2 GB hybr  distill Qwen2.5, reasoning
#    qwen3:8b            ~5.2 GB hybr  general, voisin du 3b
#
#  TIER 3 -- CPU overnight (~9 GB RAM) -- lents mais utiles pour comparaison
#    qwen3:14b           ~9.3 GB RAM   teste 25/04 : 1.79 tok/s
#    deepseek-r1:14b     ~9.0 GB RAM   teste 25/04 : 1.66 tok/s
#
#  TIER 4 -- CPU overnight (~17-18 GB RAM) -- qualite maximale LCCA
#    qwen3-coder:30b-a3b-q4_K_M  ~18 GB  MoE coding-agent SOTA
#    qwen3:30b-a3b                ~18 GB  MoE general (teste : 5.31 tok/s)
# ==========================================

# -- Tier 1 : Full-GPU (fast, journee)
$ModelsTier1 = @(
    "gemma4:e2b",
    "qwen3:4b",
    "phi4-mini",
    "phi4-mini-reasoning",
    "gemma4:e4b",
    "gemma3:4b"
)

# -- Tier 2 : Hybride (acceptable, journee ou soiree)
$ModelsTier2 = @(
    "deepseek-r1:8b",
    "qwen3:8b"
)

# -- Tier 3 : CPU moyen (lents ~1.7 tok/s, a faire la nuit)
$ModelsTier3 = @(
    "qwen3:14b",
    "deepseek-r1:14b"
)

# -- Tier 4 : CPU heavy (tres gros, uniquement la nuit)
$ModelsTier4 = @(
    "qwen3-coder:30b-a3b-q4_K_M",
    "qwen3:30b-a3b"
)

# -- Groupes de selection
$AllModels   = $ModelsTier1 + $ModelsTier2 + $ModelsTier3 + $ModelsTier4
$SmallModels = $ModelsTier1 + $ModelsTier2      # <= ~5.5 GB, utilisables en journee
$BigModels   = $ModelsTier3 + $ModelsTier4      # >= 9 GB, overnight uniquement

# ==========================================
#  MODELES A CONSERVER apres benchmark
#  Tout modele absent de cette liste sera supprime en fin de script.
# ==========================================
$ModelsToKeep = @(
    # Role Fast/UI : full-GPU
    "gemma4:e2b",
    "qwen3:4b",
    "phi4-mini",
    "phi4-mini-reasoning",
    "gemma4:e4b",
    "gemma3:4b",
    # Role Core + Debug : hybride overnight
    "qwen3:8b",
    "deepseek-r1:8b",
    # Role comparaison 14B (si resultats interessants)
    "qwen3:14b",
    "deepseek-r1:14b",
    # Role Heavy SOTA : qualite maximale LCCA
    "qwen3-coder:30b-a3b-q4_K_M",
    "qwen3:30b-a3b"
)

# Modeles dont l echec de pull est critique
$CriticalModels = @(
    "qwen3-coder:30b-a3b-q4_K_M",
    "phi4-mini-reasoning"
)

# Seuil espace disque minimum avant chaque pull (en Go)
$DiskMinGB = 20

# ==========================================
#  HELPERS
# ==========================================
function Check-DiskSpace {
    param([string]$Drive = "D")
    $disk = Get-PSDrive -Name $Drive -ErrorAction SilentlyContinue
    if (-not $disk) {
        $wmi    = Get-WmiObject Win32_LogicalDisk -Filter "DeviceID='${Drive}:'" -ErrorAction SilentlyContinue
        $freeGB = if ($wmi) { [math]::Round($wmi.FreeSpace / 1GB, 1) } else { 999 }
    } else {
        $freeGB = [math]::Round($disk.Free / 1GB, 1)
    }
    return $freeGB
}

function Assert-DiskSpace {
    param([string]$ModelName)
    $freeGB = Check-DiskSpace -Drive "D"
    if ($freeGB -lt $DiskMinGB) {
        Log ""
        Log "======================================================" "Red"
        Log "  ESPACE DISQUE INSUFFISANT" "Red"
        Log "  Libre : ${freeGB} Go  |  Minimum requis : ${DiskMinGB} Go" "Red"
        Log "  Prochain modele : $ModelName" "Red"
        Log "======================================================" "Red"
        Log "  PAUSE -- Liberez de l espace disque puis appuyez sur Entree." "Yellow"
        Read-Host "  > Appuyez sur Entree une fois l espace libere"
        $freeGB2 = Check-DiskSpace -Drive "D"
        if ($freeGB2 -lt $DiskMinGB) {
            Log "  Toujours insuffisant (${freeGB2} Go). Abandon." "Red"
            exit 1
        }
        Log "  Espace OK apres liberation : ${freeGB2} Go. Reprise." "Green"
    } else {
        Log "  Disque D: libre : ${freeGB} Go" "DarkGray"
    }
}

function Save-Progress {
    $Done | ConvertTo-Json | Out-File -FilePath $ProgressFile -Encoding UTF8 -Force
}

# ==========================================
#  MENU PRINCIPAL
# ==========================================
function Show-Menu {
    Write-Host ""
    Write-Host "==========================================" -ForegroundColor Cyan
    Write-Host "  BENCHMARK OLLAMA -- MENU PRINCIPAL" -ForegroundColor Cyan
    Write-Host "==========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  [1] Un modele a la fois     (choix dans la liste)" -ForegroundColor White
    Write-Host "  [2] Tous les modeles        ($($AllModels.Count) modeles -- peut durer toute la nuit)" -ForegroundColor White
    Write-Host "  [3] Petits modeles          ($($SmallModels.Count) modeles <= 5.5 GB -- journee OK)" -ForegroundColor Green
    Write-Host "  [4] Gros modeles            ($($BigModels.Count) modeles >= 9 GB -- overnight)" -ForegroundColor Yellow
    Write-Host "  [5] Quitter" -ForegroundColor Gray
    Write-Host ""
    $choice = Read-Host "  Votre choix [1-5]"
    return $choice
}

function Show-ModelMenu {
    Write-Host ""
    Write-Host "  Modeles disponibles :" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  -- TIER 1 : Full-GPU (journee) --" -ForegroundColor Green
    $idx = 1
    $map = @{}
    foreach ($m in $ModelsTier1) {
        Write-Host ("  [{0,2}] {1}" -f $idx, $m) -ForegroundColor White
        $map[$idx] = $m
        $idx++
    }
    Write-Host ""
    Write-Host "  -- TIER 2 : Hybride (journee/soiree) --" -ForegroundColor Yellow
    foreach ($m in $ModelsTier2) {
        Write-Host ("  [{0,2}] {1}" -f $idx, $m) -ForegroundColor White
        $map[$idx] = $m
        $idx++
    }
    Write-Host ""
    Write-Host "  -- TIER 3 : CPU moyen (nuit recommandee) --" -ForegroundColor DarkYellow
    foreach ($m in $ModelsTier3) {
        Write-Host ("  [{0,2}] {1}" -f $idx, $m) -ForegroundColor White
        $map[$idx] = $m
        $idx++
    }
    Write-Host ""
    Write-Host "  -- TIER 4 : CPU heavy (nuit obligatoire) --" -ForegroundColor Red
    foreach ($m in $ModelsTier4) {
        Write-Host ("  [{0,2}] {1}" -f $idx, $m) -ForegroundColor White
        $map[$idx] = $m
        $idx++
    }
    Write-Host ""
    $raw = Read-Host "  Numero du modele (ou plusieurs separes par virgule, ex: 1,3,5)"
    $selected = @()
    foreach ($part in ($raw -split ",")) {
        $n = [int]($part.Trim())
        if ($map.ContainsKey($n)) {
            $selected += $map[$n]
        }
    }
    return $selected
}

# ==========================================
#  AFFICHER LE CATALOGUE ET DEMANDER LE CHOIX
# ==========================================
$menuChoice = Show-Menu

switch ($menuChoice) {
    "1" {
        $SelectedModels = Show-ModelMenu
        if ($SelectedModels.Count -eq 0) {
            Write-Host "  Aucun modele selectionne. Fin." -ForegroundColor Red
            exit 0
        }
        Write-Host ""
        Write-Host "  Modeles selectionnes : $($SelectedModels -join ', ')" -ForegroundColor Cyan
    }
    "2" {
        $SelectedModels = $AllModels
        Write-Host ""
        Write-Host "  Mode : TOUS ($($SelectedModels.Count) modeles)" -ForegroundColor Cyan
    }
    "3" {
        $SelectedModels = $SmallModels
        Write-Host ""
        Write-Host "  Mode : PETITS -- $($SelectedModels.Count) modeles (Tier 1+2, <= 5.5 GB)" -ForegroundColor Green
    }
    "4" {
        $SelectedModels = $BigModels
        Write-Host ""
        Write-Host "  Mode : GROS -- $($SelectedModels.Count) modeles (Tier 3+4, >= 9 GB)" -ForegroundColor Yellow
        Write-Host "  Conseil : lancez avant de dormir." -ForegroundColor DarkYellow
    }
    "5" {
        Write-Host "  Au revoir." -ForegroundColor Gray
        exit 0
    }
    default {
        Write-Host "  Choix invalide. Relancez le script." -ForegroundColor Red
        exit 1
    }
}

# ==========================================
#  REPRISE : charger la progression
# ==========================================
$Done = @{}
if (Test-Path $ProgressFile) {
    try {
        $saved = Get-Content $ProgressFile -Raw | ConvertFrom-Json
        foreach ($entry in $saved.PSObject.Properties) {
            $Done[$entry.Name] = $entry.Value
        }
        Log "=== REPRISE DETECTEE ===" "Yellow"
        Log "Modeles deja termines : $($Done.Keys -join ', ')" "Yellow"
    } catch {
        Log "Fichier progression illisible -- on repart de zero." "Yellow"
        $Done = @{}
    }
} else {
    Log "=== NOUVEAU LANCEMENT ===" "Cyan"
}

Log "Log : $LogFile" "Gray"
Log "Debut : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" "White"
Log "Modeles a benchmarker : $($SelectedModels -join ', ')" "Cyan"

# ==========================================
#  VARIABLES GPU
# ==========================================
$env:OLLAMA_MODELS        = "D:\Continue\Ollama\models"
$env:OLLAMA_NEW_ENGINE    = "1"
$env:OLLAMA_NUM_GPU       = "99"
$env:CUDA_VISIBLE_DEVICES = "0"

# ==========================================
#  ETAPE 1 : Demarrage Ollama
# ==========================================
Log ""
Log "--- ETAPE 1 : Demarrage Ollama ---" "Cyan"

taskkill /F /IM ollama.exe /T 2>$null | Out-Null
taskkill /F /IM ollama_llm_server.exe /T 2>$null | Out-Null
Start-Sleep -Seconds 3
Start-Process -FilePath "ollama" -ArgumentList "serve" -NoNewWindow

$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 11434 -WarningAction SilentlyContinue
    if ($tcp.TcpTestSucceeded) { $ready = $true; break }
}
if (-not $ready) {
    Log "ERREUR : Ollama ne repond pas. Abandon." "Red"
    exit 1
}
Log "Ollama demarre." "Green"

# ==========================================
#  ETAPE 2 : Pull modeles manquants
# ==========================================
Log ""
Log "--- ETAPE 2 : Pull modeles manquants ---" "Cyan"

foreach ($model in $SelectedModels) {
    if ($Done["pull_$model"] -eq "ok") {
        Log "  [SKIP] $model deja pull (reprise)" "DarkGray"
        continue
    }
    $list = ollama list 2>$null
    if ($list -match [regex]::Escape($model)) {
        Log "  [OK]   $model present" "Green"
    } else {
        Assert-DiskSpace -ModelName $model
        Log "  [PULL] $model en cours..." "Yellow"
        $t0 = Get-Date
        ollama pull $model 2>&1 | ForEach-Object { Add-Content -Path $LogFile -Value $_ -Encoding UTF8 }
        $elapsed = [int]((Get-Date) - $t0).TotalSeconds
        $list2 = ollama list 2>$null
        if ($list2 -match [regex]::Escape($model)) {
            Log "  [OK]   $model telecharge en ${elapsed}s" "Green"
        } else {
            $isCritical = $CriticalModels -contains $model
            if ($isCritical) {
                Log "" 
                Log "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" "Red"
                Log "  PULL ECHOUE : $model (CRITIQUE)" "Red"
                Log "  Verifiez avec : ollama pull $model" "Red"
                Log "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" "Red"
                Read-Host "  > Entree pour ignorer, Ctrl+C pour annuler"
            } else {
                Log "  [WARN] $model pull incertain -- on continue" "Yellow"
            }
        }
    }
    $Done["pull_$model"] = "ok"
    Save-Progress
}

# ==========================================
#  ETAPE 3 : Benchmark modele par modele
# ==========================================
Log ""
Log "--- ETAPE 3 : Benchmark (8 prompts x 3 runs) ---" "Cyan"
Log "Debut : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" "White"

$benchSource = "$PSScriptRoot\CPUVsGPU\scripts\run_benchmark_all_models.ps1"
if (-not (Test-Path $benchSource)) {
    Log "ERREUR : script benchmark introuvable : $benchSource" "Red"
    exit 1
}
$benchContent = [System.IO.File]::ReadAllText($benchSource, [System.Text.Encoding]::UTF8)
$benchPatched = $benchContent -replace 'Read-Host', '# Read-Host (overnight)'
$tempScript   = "$PSScriptRoot\CPUVsGPU\scripts\run_benchmark_all_models_auto.ps1"
[System.IO.File]::WriteAllText($tempScript, $benchPatched, [System.Text.Encoding]::UTF8)
Log "  Script benchmark charge depuis : $benchSource" "DarkGray"

foreach ($model in $SelectedModels) {
    if ($Done["bench_$model"] -eq "ok") {
        Log "  [SKIP] benchmark $model deja fait (reprise)" "DarkGray"
        continue
    }

    Log ""
    Log "  [BENCH] $model ..." "Cyan"

    & $tempScript -Models @($model) -Quick 2>&1 | Tee-Object -Append -FilePath $LogFile

    $Done["bench_$model"] = "ok"
    Save-Progress
    Log "  [OK]   $model benchmark termine" "Green"
}

Remove-Item "$PSScriptRoot\CPUVsGPU\scripts\run_benchmark_all_models_auto.ps1" -Force -ErrorAction SilentlyContinue

# ==========================================
#  FIN : nettoyer la progression
# ==========================================
Remove-Item $ProgressFile -Force -ErrorAction SilentlyContinue

# ==========================================
#  ETAPE 4 : Suppression des modeles inutiles
# ==========================================
Log ""
Log "--- ETAPE 4 : Nettoyage modeles hors liste ModelsToKeep ---" "Cyan"

$installedRaw   = ollama list 2>$null
$installedLines = $installedRaw -split "`n" | Where-Object { $_ -match "\S" } | Select-Object -Skip 1

foreach ($line in $installedLines) {
    $modelFull = ($line -split "\s+")[0]
    $modelBase = $modelFull -replace ":latest$", ""
    $keep = $false
    foreach ($k in $ModelsToKeep) {
        $kBase = $k -replace ":latest$", ""
        if ($modelBase -eq $kBase -or $modelFull -eq $k) {
            $keep = $true
            break
        }
    }
    if ($keep) {
        Log "  [KEEP]   $modelFull" "Green"
    } else {
        Log "  [REMOVE] $modelFull -- hors liste ModelsToKeep" "Yellow"
        ollama rm $modelFull 2>&1 | Out-Null
        Log "  [OK]     $modelFull supprime" "DarkGray"
    }
}

$freeAfter = Check-DiskSpace -Drive "D"
Log "  Espace disque D: apres nettoyage : ${freeAfter} Go" "Cyan"

Log ""
Log "=== FIN ===" "Cyan"
Log "Fin : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" "White"
Log "Resultats : $ResultsDir\" "Green"
Log "Log       : $LogFile" "Green"
