# diagnose_gpu.ps1
# Diagnostic complet GPU pour Ollama : detecte pourquoi Nvidia est a 0%
# Lance dans une NOUVELLE fenetre PowerShell (ne pas arreter le benchmark)
# ASCII pur - pas d accents dans ce fichier

$ErrorActionPreference = "SilentlyContinue"

function Sep  { Write-Host ("-" * 60) -ForegroundColor DarkGray }
function Head { param([string]$T) Write-Host ""; Write-Host "=== $T ===" -ForegroundColor Cyan }

# ==========================================
#  1. NVIDIA-SMI : carte detectee ?
# ==========================================
Head "1. NVIDIA-SMI"
$nsmi = "C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
if (-not (Test-Path $nsmi)) { $nsmi = "nvidia-smi" }

try {
    $smiOut = & $nsmi 2>&1
    Write-Host $smiOut -ForegroundColor White
} catch {
    Write-Host "  nvidia-smi introuvable ou erreur : $_" -ForegroundColor Red
}

# ==========================================
#  2. CUDA : version installee ?
# ==========================================
Head "2. CUDA version"
try {
    $cudaVer = & $nsmi --query-gpu=driver_version,compute_cap --format=csv,noheader 2>&1
    Write-Host "  Driver + Compute Capability : $cudaVer" -ForegroundColor White
} catch {
    Write-Host "  Impossible de lire la version CUDA" -ForegroundColor Red
}

# nvcc (compilateur CUDA) present ?
try {
    $nvcc = & nvcc --version 2>&1
    Write-Host "  nvcc : $nvcc" -ForegroundColor White
} catch {
    Write-Host "  nvcc absent (CUDA Toolkit non installe -- pas obligatoire pour Ollama)" -ForegroundColor Yellow
}

# ==========================================
#  3. OLLAMA : version + detection GPU
# ==========================================
Head "3. Ollama version"
try {
    $olVer = & ollama --version 2>&1
    Write-Host "  $olVer" -ForegroundColor White
} catch {
    Write-Host "  Ollama introuvable dans PATH" -ForegroundColor Red
}

# ==========================================
#  4. OLLAMA PS : modeles en cours + backend
# ==========================================
Head "4. Ollama ps (modeles charges)"
try {
    $olPs = & ollama ps 2>&1
    Write-Host $olPs -ForegroundColor White
    if ($olPs -match "100%.*CPU") {
        Write-Host "  --> CONFIRME : Ollama tourne en CPU pur" -ForegroundColor Red
    } elseif ($olPs -match "GPU") {
        Write-Host "  --> GPU detecte dans ollama ps" -ForegroundColor Green
    }
} catch {
    Write-Host "  Erreur ollama ps : $_" -ForegroundColor Red
}

# ==========================================
#  5. VARIABLES D ENVIRONNEMENT Ollama
# ==========================================
Head "5. Variables environnement Ollama"
$vars = @(
    "OLLAMA_NUM_GPU",
    "CUDA_VISIBLE_DEVICES",
    "OLLAMA_NEW_ENGINE",
    "OLLAMA_MODELS",
    "OLLAMA_GPU_OVERHEAD",
    "OLLAMA_DEBUG"
)
foreach ($v in $vars) {
    $val = [System.Environment]::GetEnvironmentVariable($v)
    if ($val) {
        Write-Host "  $v = $val" -ForegroundColor Green
    } else {
        Write-Host "  $v = (non defini)" -ForegroundColor DarkGray
    }
}

# ==========================================
#  6. GPU Windows : tous les GPU detectes
# ==========================================
Head "6. GPU detectes par Windows (WMI)"
$gpus = Get-WmiObject Win32_VideoController
$i = 0
foreach ($g in $gpus) {
    $vramGB = if ($g.AdapterRAM) { [math]::Round($g.AdapterRAM / 1GB, 1) } else { "?" }
    Write-Host "  GPU$i : $($g.Name)" -ForegroundColor White
    Write-Host "         VRAM declaree : ${vramGB} GB" -ForegroundColor Gray
    Write-Host "         Driver        : $($g.DriverVersion)" -ForegroundColor Gray
    Write-Host "         Status        : $($g.Status)" -ForegroundColor Gray
    $i++
}

# ==========================================
#  7. NVIDIA-SMI : utilisation temps reel
# ==========================================
Head "7. Utilisation GPU Nvidia temps reel (5 snapshots)"
try {
    for ($s = 1; $s -le 5; $s++) {
        $snap = & $nsmi --query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu `
            --format=csv,noheader,nounits 2>&1
        Write-Host "  [$s] $snap" -ForegroundColor White
        Start-Sleep -Seconds 2
    }
} catch {
    Write-Host "  Erreur snapshots : $_" -ForegroundColor Red
}

# ==========================================
#  8. OPTIMUS / HYBRID GRAPHICS
# ==========================================
Head "8. Hybrid Graphics (Optimus)"
$display = Get-WmiObject Win32_VideoController | Where-Object { $_.Name -match "Nvidia|NVIDIA" }
if ($display) {
    Write-Host "  Carte Nvidia trouvee : $($display.Name)" -ForegroundColor Green
    Write-Host "  Verifie dans NVIDIA Control Panel :" -ForegroundColor Yellow
    Write-Host "    Manage 3D Settings --> Preferred GPU --> doit etre 'High-performance NVIDIA'" -ForegroundColor Yellow
} else {
    Write-Host "  Carte Nvidia absente dans WMI VideoController" -ForegroundColor Red
}

# ==========================================
#  9. CUDA VISIBLE DEVICES : ce qu Ollama voit
# ==========================================
Head "9. Test direct API Ollama (pendant le benchmark)"
try {
    $body = @{ model = "gemma4:e2b"; prompt = "hello"; stream = $false; options = @{ num_predict = 5 } } | ConvertTo-Json
    $r = Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
        -Body $body -ContentType "application/json" -TimeoutSec 30
    Write-Host "  Reponse OK : $($r.response)" -ForegroundColor Green

    # Cherche des indices GPU dans la reponse
    if ($r.PSObject.Properties["context"]) {
        Write-Host "  Context tokens : $($r.context.Count)" -ForegroundColor Gray
    }
} catch {
    Write-Host "  API Ollama inaccessible (benchmark en cours sur ce modele ?)" -ForegroundColor Yellow
    Write-Host "  Normal si le benchmark occupe Ollama -- relance apres." -ForegroundColor DarkGray
}

# ==========================================
#  10. LOG OLLAMA : indices de debug
# ==========================================
Head "10. Logs Ollama (derniers messages GPU)"
$logPaths = @(
    "$env:LOCALAPPDATA\Ollama\logs\server.log",
    "$env:USERPROFILE\.ollama\logs\server.log",
    "C:\Users\$env:USERNAME\.ollama\logs\server.log"
)
$found = $false
foreach ($lp in $logPaths) {
    if (Test-Path $lp) {
        Write-Host "  Log trouve : $lp" -ForegroundColor Green
        $lines = Get-Content $lp -Tail 60 | Where-Object {
            $_ -match "cuda|gpu|nvidia|vram|metal|cpu|device|GGML|backend|load"
        }
        if ($lines) {
            $lines | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }
        } else {
            Write-Host "  (aucune ligne GPU dans les 60 dernieres)" -ForegroundColor DarkGray
            Get-Content $lp -Tail 20 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
        }
        $found = $true
        break
    }
}
if (-not $found) {
    Write-Host "  Aucun log Ollama trouve aux emplacements habituels." -ForegroundColor Yellow
    Write-Host "  Lance : ollama serve 2>&1 dans une fenetre separee pour voir les logs." -ForegroundColor Yellow
}

# ==========================================
#  RESUME FINAL
# ==========================================
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  RESUME" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Copie TOUT ce qui est affiche ci-dessus et envoie-le." -ForegroundColor White
Write-Host "  Les sections les plus importantes sont :" -ForegroundColor Gray
Write-Host "    - Section 1  : nvidia-smi (carte detectee ?)" -ForegroundColor Gray
Write-Host "    - Section 4  : ollama ps  (CPU ou GPU ?)" -ForegroundColor Gray
Write-Host "    - Section 10 : logs Ollama (erreur CUDA ?)" -ForegroundColor Gray
Write-Host ""
