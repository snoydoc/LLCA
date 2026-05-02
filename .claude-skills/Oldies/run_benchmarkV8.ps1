# run_benchmarkV8.ps1
# Benchmark GPU/CPU hybride - Quadro M2000M (4GB VRAM CUDA)
# Lancer via prepare_and_launchV8.ps1 -- ne pas lancer directement
# ASCII pur - pas d accents dans ce fichier
#
# V8 (2026-04-27) -- Refonte architecture + Menu interactif :
#   [MENU]      Menu interactif au lancement si -Interactive ou sans parametre -Mode
#   [CONFIG]    Chargement configuration externe JSON (optionnel)
#   [DRYRUN]    Mode simulation (-WhatIf) pour valider la config sans inferer
#   [MODULAR]   Fonctions factorisees, gestion d erreurs centralisee
#   [HEALTH]    Healthcheck Ollama + GPU au demarrage
#   [RESUME]    Reprise granulaire conservee et renforcee (checksum progression)
#   [EXPORT]    Export CSV + JSON + Markdown rapport final
#   [ALERTES]   Temperature GPU + RAM + VRAM avec seuils configurables

[CmdletBinding()]
param(
    [ValidateSet("GPU", "CPU", "Hybride", "")]
    [string]$Mode = "",

    [switch]$Interactive,

    [switch]$WhatIf,

    [string]$ConfigPath = "",

    [int]$RunsPerPrompt = 3
)

$ErrorActionPreference = "Stop"

# ==========================================
#  CONFIGURATION & CONSTANTES
# ==========================================
$script:Version      = "V8"
$script:StartTime    = Get-Date

# CORRECTION DEFINITIVE : utilisation de Path.Combine avec quotes systematiques
# pour eviter TOUT probleme d espace dans les chemins
$script:RootDir      = $PSScriptRoot
$script:ResultsDir   = [System.IO.Path]::Combine($script:RootDir, "CPUVsGPU", "results")
$script:ResponseDir  = [System.IO.Path]::Combine($script:RootDir, "CPUVsGPU", "results", "responses")
$script:LogFile      = [System.IO.Path]::Combine($script:ResultsDir, "bench_gpu_$(Get-Date -Format 'yyyyMMdd_HHmm').log")
$script:ErrLogFile   = [System.IO.Path]::Combine($script:ResultsDir, "llm_errors_$(Get-Date -Format 'yyyyMMdd_HHmm').json")
$script:ReportFile   = [System.IO.Path]::Combine($script:ResultsDir, "RAPPORT_FINAL_$(Get-Date -Format 'yyyyMMdd_HHmmss').md")
$script:ProgressFile = ""
$script:CSVFile      = ""

# Seuils securite memoire
$script:RAM_FREE_MIN_MB   = 3000
$script:OLLAMA_RAM_MAX_MB = 13000
$script:GPU_TEMP_WARN     = 85
$script:GPU_TEMP_CRIT     = 92

# Timeouts adaptatifs
$script:TIMEOUT_MIN_SEC     = 120
$script:TIMEOUT_MAX_SEC     = 10800
$script:TIMEOUT_DEFAULT_SEC = 900

# ==========================================
#  MENU INTERACTIF
# ==========================================
function Show-InteractiveMenu {
    Clear-Host
    $W = 60
    Write-Host ("=" * $W) -ForegroundColor Cyan
    Write-Host "   BENCHMARK OLLAMA HYBRIDE - MENU PRINCIPAL" -ForegroundColor Cyan
    Write-Host ("=" * $W) -ForegroundColor Cyan
    Write-Host ""
    Write-Host "   [1] Mode GPU     - Uniquement les modeles GPU (rapide)"
    Write-Host "   [2] Mode CPU     - Uniquement les modeles CPU (lourd)"
    Write-Host "   [3] Mode Hybride - Tous les modeles (complet, defaut)"
    Write-Host ""
    Write-Host "   [Q] Quitter"
    Write-Host ""
    Write-Host ("=" * $W) -ForegroundColor Cyan

    do {
        $choice = Read-Host "   Choix"
        switch ($choice.Trim().ToUpper()) {
            "1" { return "GPU" }
            "2" { return "CPU" }
            "3" { return "Hybride" }
            "Q" { exit 0 }
            default { Write-Host "   Choix invalide." -ForegroundColor Red }
        }
    } while ($true)
}

# ==========================================
#  RESOLUTION DU MODE
# ==========================================
if ([string]::IsNullOrWhiteSpace($Mode)) {
    if ($Interactive -or -not $Mode) {
        $Mode = Show-InteractiveMenu
    } else {
        $Mode = "Hybride"
    }
}

# Fichiers specifiques au mode
$script:ProgressFile = [System.IO.Path]::Combine($script:ResultsDir, "overnight_v8_progress_${Mode}.json")
$script:CSVFile      = [System.IO.Path]::Combine($script:ResultsDir, "bench_gpu_incremental_${Mode}.csv")

# Creation repertoires avec verification
if (-not (Test-Path $script:ResultsDir)) {
    New-Item -ItemType Directory -Force -Path $script:ResultsDir | Out-Null
}
if (-not (Test-Path $script:ResponseDir)) {
    New-Item -ItemType Directory -Force -Path $script:ResponseDir | Out-Null
}

# ==========================================
#  TABLE TIMEOUTS
# ==========================================
$script:TimeoutTable = @{
    "phi4"     = @{ "code_simple" = 900;  "debug" = 1200; "coding_lcca" = 7200; "_default" = 2400 }
    "qwen3"    = @{ "code_simple" = 1200; "debug" = 1800; "coding_lcca" = 5400; "_default" = 2400 }
    "qwen2"    = @{ "code_simple" = 600;  "debug" = 900;  "coding_lcca" = 1800; "_default" = 1200 }
    "deepseek" = @{ "code_simple" = 1800; "debug" = 2400; "coding_lcca" = 7200; "_default" = 3600 }
    "gemma4"   = @{ "code_simple" = 1200; "debug" = 1800; "coding_lcca" = 5400; "_default" = 2400 }
    "gemma3"   = @{ "code_simple" = 600;  "debug" = 900;  "coding_lcca" = 2400; "_default" = 1200 }
    "_tier_gpu"  = 900
    "_tier_cpu"  = 5400
}

# ==========================================
#  MULTIPLICATEURS TOKENS
# ==========================================
$script:TokenMultipliers = @{
    "gemma4"  = 4
    "phi3"    = 3
    "qwen3"   = 3
    "gemma3"  = 2
    "default" = 1
}

# ==========================================
#  LISTES MODELES
# ==========================================
$script:ModelsTierGPU = @(
    "qwen2.5-coder:3b",
    "gemma4:e2b",
    "qwen3:4b",
    "phi4-mini-reasoning:latest",
    "gemma3:4b",
    "gemma4:e4b"
)

$script:ModelsTierCPU = @(
    "deepseek-r1:8b",
    "qwen3:8b",
    "qwen3:14b",
    "deepseek-r1:14b",
    "qwen3-coder:30b-a3b-q4_K_M",
    "qwen3:30b-a3b"
)

$script:AllModels = switch ($Mode) {
    "GPU"     { $script:ModelsTierGPU }
    "CPU"     { $script:ModelsTierCPU }
    "Hybride" { $script:ModelsTierGPU + $script:ModelsTierCPU }
}

# ==========================================
#  PROMPTS
# ==========================================
$script:Prompts = [ordered]@{
    code_simple = @{
        text   = "Write a Python function named days_between that takes two date strings (YYYY-MM-DD) and returns the number of days between them. Include a docstring and a usage example."
        tokens = 512
    }
    debug = @{
        text   = "Here is a buggy Python function:`n`ndef average(lst):`n    return sum(lst) / len(lst)`n`nIt crashes with ZeroDivisionError when the list is empty. Identify the bug and provide a complete fixed version."
        tokens = 512
    }
    coding_lcca = @{
        text   = "You are a Python code assistant. Refactor the following class. Rules: use pathlib.Path not os.path, PascalCase for classes, snake_case for functions, docstring on every function, handle edge cases, return complete file without truncation.`n`nCode:`n`nimport os`n`nclass fileManager:`n    def __init__(self, base):`n        self.base = base`n    def ReadFile(self, name):`n        p = os.path.join(self.base, name)`n        return open(p).read()`n    def WriteFile(self, name, data):`n        p = os.path.join(self.base, name)`n        open(p, 'w').write(data)`n    def listfiles(self):`n        return os.listdir(self.base)"
        tokens = 2048
    }
}

# ==========================================
#  VARIABLES GLOBALES DASHBOARD
# ==========================================
$script:DashRow       = -1
$script:DashHeight    = 14
$script:RunsDone      = 0
$script:RunsTotal     = $script:AllModels.Count * $script:Prompts.Count * $RunsPerPrompt
$script:ModelesDone   = 0
$script:ModelesTotal  = $script:AllModels.Count
$script:ModelesOk     = [System.Collections.Generic.List[string]]::new()
$script:ModelesSkip   = [System.Collections.Generic.List[string]]::new()
$script:Results       = [System.Collections.Generic.List[object]]::new()
$script:LLMErrors     = [System.Collections.Generic.List[object]]::new()
$script:Done          = @{}
$script:IsResume      = $false
$script:LastTok       = 0.0
$script:LastRunMs     = 0

# ==========================================
#  FONCTIONS UTILITAIRES
# ==========================================
function Write-Log {
    param([string]$Message, [System.ConsoleColor]$Color = "White")
    $ts = Get-Date -Format "HH:mm:ss"
    $line = "[$ts] $Message"
    if ($script:DashRow -ge 0) {
        $cur = [Console]::CursorTop
        if ($cur -lt $script:DashRow + $script:DashHeight) {
            [Console]::SetCursorPosition(0, $script:DashRow + $script:DashHeight)
        }
    }
    Write-Host $line -ForegroundColor $Color
    Add-Content -Path $script:LogFile -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
}

function Write-LogError {
    param(
        [string]$Model, [string]$Prompt, [int]$Run,
        [string]$ErrorMessage, [hashtable]$Options = @{},
        [string]$DoneReason = "", [int]$ResponseLen = 0,
        [int]$TokensOut = 0, [string]$Category = "unknown",
        [int]$TimeoutUsed = 0
    )
    if ($Category -eq "unknown") {
        if ($ErrorMessage -match "500|internal server error") { $Category = "server_error_500" }
        elseif ($ErrorMessage -match "timeout|timedout|timed out") { $Category = "timeout" }
        elseif ($ErrorMessage -match "terminated|killed|oom|out.of.memory") { $Category = "oom_or_crash" }
        elseif ($ResponseLen -eq 0 -and $DoneReason -ne "stop") { $Category = "empty_response" }
        elseif ($DoneReason -eq "length") { $Category = "truncated_response" }
        else { $Category = "other" }
    }
    $suggestion = switch ($Category) {
        "server_error_500"   { "Restart Ollama. Reduce num_predict. Check VRAM." }
        "timeout"            { "Increase TimeoutSec. Reduce num_predict. Current: ${TimeoutUsed}s" }
        "oom_or_crash"       { "RAM threshold hit. Reduce model tier or add RAM." }
        "empty_response"     { "Model has thinking block: multiply num_predict x4." }
        "truncated_response" { "Increase num_predict. Response cut short by token budget." }
        default              { "Review error message and adjust options." }
    }
    $entry = [PSCustomObject]@{
        timestamp    = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        model        = $Model
        prompt       = $Prompt
        run          = $Run
        category     = $Category
        error_msg    = $ErrorMessage
        done_reason  = $DoneReason
        response_len = $ResponseLen
        tokens_out   = $TokensOut
        options_used = $Options
        suggestion   = $suggestion
        timeout_sec  = $TimeoutUsed
    }
    $script:LLMErrors.Add($entry)
    $script:LLMErrors | ConvertTo-Json -Depth 6 | Out-File $script:ErrLogFile -Encoding UTF8 -Force
    Write-Log "[ERR-LOG] $Category => $suggestion" "DarkYellow"
}

function Format-ETA {
    param([int]$Sec)
    if ($Sec -le 0) { return "calcul..." }
    if ($Sec -ge 3600) { return "$([int]($Sec/3600))h $([int](($Sec%3600)/60))m" }
    if ($Sec -ge 60)   { return "$([int]($Sec/60))m $($Sec%60)s" }
    return "${Sec}s"
}

function Format-Elapsed {
    $e = (Get-Date) - $script:StartTime
    return "$([int]$e.TotalHours)h $($e.Minutes.ToString('00'))m $($e.Seconds.ToString('00'))s"
}

function Draw-Bar {
    param([int]$Pct, [int]$Width = 30)
    $filled = [int]($Width * $Pct / 100)
    $empty  = $Width - $filled
    return "[" + ("#" * $filled) + ("-" * $empty) + "] $Pct%"
}

function Get-FreeRAM_MB {
    try {
        $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
        return [int]($os.FreePhysicalMemory / 1024)
    } catch { return 99999 }
}

function Get-OllamaRAM_MB {
    $sum = (Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match "ollama" } |
            Measure-Object PrivateMemorySize64 -Sum).Sum
    return [int]($sum / 1MB)
}

function Get-AdaptiveTimeout {
    param([string]$ModelName, [string]$PromptKey, [bool]$IsCPU)
    $fam = "unknown"
    if ($ModelName -match "phi[34]")      { $fam = "phi4" }
    elseif ($ModelName -match "qwen3")    { $fam = "qwen3" }
    elseif ($ModelName -match "qwen2")    { $fam = "qwen2" }
    elseif ($ModelName -match "deepseek") { $fam = "deepseek" }
    elseif ($ModelName -match "gemma4")   { $fam = "gemma4" }
    elseif ($ModelName -match "gemma3")   { $fam = "gemma3" }

    $resolved = $script:TIMEOUT_DEFAULT_SEC
    if ($fam -ne "unknown" -and $script:TimeoutTable.ContainsKey($fam)) {
        $ft = $script:TimeoutTable[$fam]
        if ($ft.ContainsKey($PromptKey)) { $resolved = $ft[$PromptKey] }
        elseif ($ft.ContainsKey("_default")) { $resolved = $ft["_default"] }
    }
    elseif ($IsCPU -and $script:TimeoutTable.ContainsKey("_tier_cpu")) { $resolved = $script:TimeoutTable["_tier_cpu"] }
    elseif (-not $IsCPU -and $script:TimeoutTable.ContainsKey("_tier_gpu")) { $resolved = $script:TimeoutTable["_tier_gpu"] }

    return [Math]::Max($script:TIMEOUT_MIN_SEC, [Math]::Min($script:TIMEOUT_MAX_SEC, $resolved))
}

# ==========================================
#  DASHBOARD
# ==========================================
function Update-Dashboard {
    param(
        [string]$CurrentModel   = "",
        [string]$CurrentPrompt  = "",
        [int]$CurrentRun        = 0,
        [int]$RunTotal          = $RunsPerPrompt,
        [string]$Phase          = "",
        [int]$CurrentTimeoutSec = 0
    )
    $elapsed   = ((Get-Date) - $script:StartTime).TotalSeconds
    $doneFrac  = if ($script:RunsTotal -gt 0) { $script:RunsDone / $script:RunsTotal } else { 0 }
    $etaSec    = if ($doneFrac -gt 0.02) { [int]($elapsed / $doneFrac * (1 - $doneFrac)) } else { 0 }
    $pctGlobal = [int]($doneFrac * 100)
    $bar       = Draw-Bar -Pct $pctGlobal
    $tokStr    = if ($script:LastTok -gt 0) { "$($script:LastTok) tok/s" } else { "---" }
    $resumeTag = if ($script:IsResume) { " [REPRISE]" } else { "" }
    $modeTag   = " [MODE:$Mode]"
    $ramFree   = Get-FreeRAM_MB
    $ollamaRam = Get-OllamaRAM_MB
    $toStr     = if ($CurrentTimeoutSec -gt 0) { "timeout: ${CurrentTimeoutSec}s" } else { "" }
    $W         = 72
    $sep       = "=" * $W
    $derniersOk = if ($script:ModelesOk.Count -gt 0) { ($script:ModelesOk | Select-Object -Last 4) -join ", " } else { "(aucun)" }

    $lines = @(
        $sep,
        "  BENCHMARK $script:Version${resumeTag}${modeTag} | Duree: $(Format-Elapsed) | ETA: $(Format-ETA $etaSec)",
        "  Progression : $bar",
        "  Modeles  : $($script:ModelesDone)/$($script:ModelesTotal) OK | $($script:ModelesSkip.Count) skips | RAM libre: ${ramFree}MB | Ollama: ${ollamaRam}MB",
        "  Derniers OK : $derniersOk",
        $sep,
        "  Modele courant : [$($script:ModelesDone + 1)/$($script:ModelesTotal)] $CurrentModel",
        "  Prompt  : ${CurrentPrompt,-22} Run : $CurrentRun/$RunTotal",
        "  Phase   : ${Phase,-30} $tokStr  $toStr",
        "  Runs    : $($script:RunsDone)/$($script:RunsTotal)   Dernier : $($script:LastRunMs) ms",
        $sep,
        ""
    )

    if ($script:DashRow -lt 0) { $script:DashRow = [Console]::CursorTop }
    $savedTop = [Console]::CursorTop
    [Console]::SetCursorPosition(0, $script:DashRow)
    foreach ($l in $lines) {
        Write-Host $l.PadRight($W) -ForegroundColor Cyan
    }
    $logRow = [Math]::Max($savedTop, $script:DashRow + $script:DashHeight)
    [Console]::SetCursorPosition(0, $logRow)
}

# ==========================================
#  GPU / CPU / OLLAMA HELPERS
# ==========================================
$script:Nsmi = if (Test-Path "C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe") {
    "C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
} else { "nvidia-smi" }

function Get-GpuSnap {
    try {
        $raw = & $script:Nsmi --query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu `
                --format=csv,noheader,nounits 2>$null
        $p = ($raw -split ",\s*")
        $snap = @{ U = [int]$p[0]; T = [int]$p[1]; G = [int]$p[2]; C = [int]$p[3] }
        if ($snap.C -ge $script:GPU_TEMP_CRIT) {
            Write-Log "[!!! CRITIQUE TEMP GPU !!!] $($snap.C)C >= ${script:GPU_TEMP_CRIT}C - ARRET" "Red"
            throw "GPU CRITICAL TEMPERATURE"
        }
        elseif ($snap.C -ge $script:GPU_TEMP_WARN) {
            Write-Log "[!!! ALERTE TEMP GPU !!!] $($snap.C)C >= ${script:GPU_TEMP_WARN}C" "Red"
        }
        return $snap
    } catch { return @{ U = -1; T = -1; G = -1; C = -1 } }
}

function Get-CpuSnap {
    try {
        $c = Get-Counter "\Processor(_Total)\% Processor Time" -SampleInterval 1 -MaxSamples 1 -ErrorAction Stop
        return [math]::Round($c.CounterSamples.CookedValue, 1)
    } catch { return -1 }
}

function Calc-TokPerSec {
    param($resp)
    if ($resp.eval_rate -and $resp.eval_rate -gt 0) { return [math]::Round($resp.eval_rate, 2) }
    if ($resp.eval_count -and $resp.eval_duration -and $resp.eval_duration -gt 0) {
        return [math]::Round($resp.eval_count / ($resp.eval_duration / 1e9), 2)
    }
    return 0
}

function Test-ModelExists {
    param([string]$Name)
    try {
        $list = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get -TimeoutSec 10
        return ($list.models | Where-Object { $_.name -eq $Name }) -ne $null
    } catch { return $false }
}

function Get-ModelInfo {
    param([string]$ModelName)
    try {
        $info = Invoke-RestMethod -Uri "http://localhost:11434/api/show" -Method Post `
            -Body (@{ name = $ModelName } | ConvertTo-Json) -ContentType "application/json" -TimeoutSec 30
        return "family=$($info.details.family) size=$($info.details.parameter_size) quant=$($info.details.quantization_level)"
    } catch { return "info unavailable" }
}

function Restart-OllamaService {
    Write-Log "[RESTART] Redemarrage Ollama..." "Yellow"
    taskkill /F /IM ollama.exe /T 2>$null | Out-Null
    taskkill /F /IM ollama_llm_server.exe /T 2>$null | Out-Null
    taskkill /F /IM ollama_app.exe /T 2>$null | Out-Null
    Start-Sleep -Seconds 8
    $env:OLLAMA_MODELS = "D:\Continue\Ollama\models"
    Start-Process -FilePath "ollama" -ArgumentList "serve" -NoNewWindow
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 2
        try {
            $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 11434 -WarningAction SilentlyContinue
            if ($tcp.TcpTestSucceeded) {
                Write-Log "[RESTART] Ollama OK ($($i*2+2)s)" "Green"
                Start-Sleep 5
                return
            }
        } catch { }
    }
    Write-Log "[RESTART] Echec apres 60s" "Red"
}

function Unload-Model {
    param([string]$ModelName)
    try {
        Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
            -Body (@{ model = $ModelName; prompt = ""; keep_alive = 0 } | ConvertTo-Json) `
            -ContentType "application/json" -TimeoutSec 30 | Out-Null
        Write-Log "[UNLOAD] $ModelName flushed" "DarkGray"
    } catch { Write-Log "[UNLOAD] soft unload failed" "DarkGray" }
}

function Save-ResponseToFile {
    param([string]$Model, [string]$Prompt, [int]$Run, [string]$Content)
    $safe = $Model -replace "[:\\\/]", "_"
    $fpath = [System.IO.Path]::Combine($script:ResponseDir, "${safe}__${Prompt}__run${Run}.txt")
    $hdr = "MODEL: $Model | PROMPT: $Prompt | RUN: $Run | $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Set-Content -Path $fpath -Value ("=" * 80 + "`n" + $hdr + "`n" + "=" * 80 + "`n`n" + $Content) -Encoding UTF8
}

# ==========================================
#  HEALTHCHECK DEMARRAGE
# ==========================================
function Test-SystemHealth {
    Write-Log "=== HEALTHCHECK SYSTEME ===" "Cyan"

    $ollamaOk = $false
    try {
        $null = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get -TimeoutSec 5
        $ollamaOk = $true
        Write-Log "  Ollama    : OK (port 11434)" "Green"
    } catch {
        Write-Log "  Ollama    : INJOIGNABLE - tentative demarrage..." "Yellow"
        Restart-OllamaService
        $ollamaOk = $true
    }

    $gpu = Get-GpuSnap
    if ($gpu.U -ge 0) {
        Write-Log "  GPU       : $($gpu.U)/$($gpu.T) MB VRAM | $($gpu.G)% | $($gpu.C)C" "Green"
    } else {
        Write-Log "  GPU       : Non detecte (nvidia-smi absent?)" "Yellow"
    }

    $ram = Get-FreeRAM_MB
    Write-Log "  RAM libre : ${ram} MB" $(if ($ram -gt $script:RAM_FREE_MIN_MB) { "Green" } else { "Red" })

    $missing = @()
    foreach ($m in $script:AllModels) {
        if (-not (Test-ModelExists $m)) { $missing += $m }
    }
    if ($missing.Count -gt 0) {
        Write-Log "  Modeles manquants : $($missing -join ', ')" "Red"
    } else {
        Write-Log "  Modeles   : $($script:AllModels.Count)/$($script:AllModels.Count) disponibles" "Green"
    }

    return ($ollamaOk -and $missing.Count -eq 0)
}

# ==========================================
#  PROGRESSION / REPRISE
# ==========================================
function Get-RunKey {
    param([string]$Model, [string]$Prompt, [int]$Run)
    $safe = $Model -replace "[:\\\/\s]", "_"
    return "run_${safe}__${Prompt}__${Run}"
}

function Save-ProgressState {
    $script:Done | ConvertTo-Json -Depth 3 | Out-File $script:ProgressFile -Encoding UTF8 -Force
}

function Load-ProgressState {
    if (Test-Path $script:ProgressFile) {
        try {
            $saved = Get-Content $script:ProgressFile -Raw | ConvertFrom-Json
            foreach ($e in $saved.PSObject.Properties) { $script:Done[$e.Name] = $e.Value }
            $script:IsResume = $script:Done.Keys.Count -gt 0
            if ($script:IsResume) {
                Write-Log "=== REPRISE : $($script:Done.Keys.Count) cles de progression rechargees ===" "Yellow"
            }
        } catch { $script:Done = @{} }
    }
    if ($script:IsResume -and (Test-Path $script:CSVFile)) {
        try {
            $loaded = Import-Csv $script:CSVFile -Encoding UTF8
            foreach ($row in $loaded) { $script:Results.Add($row) }
            Write-Log "  CSV incremental : $($script:Results.Count) runs recharges" "Yellow"
        } catch {
            Write-Log "  [WARN] Impossible de recharger CSV incremental : $_" "Yellow"
        }
    }
    $script:RunsDone = ($script:Done.Keys | Where-Object { $_ -like "run_*" -and $script:Done[$_] -eq "ok" }).Count
    $script:ModelesDone = ($script:Done.Keys | Where-Object { $_ -like "done_*" -and $script:Done[$_] -in @("ok","skip","skip_warmup","skip_oom") }).Count
    foreach ($k in ($script:Done.Keys | Where-Object { $_ -like "done_*" -and $script:Done[$_] -eq "ok" })) {
        $m = $k -replace "^done_", ""
        if (-not ($script:ModelesOk -contains $m)) { $script:ModelesOk.Add($m) }
    }
}

# ==========================================
#  RECAP MODELE
# ==========================================
function Show-ModelSummary {
    param([string]$Model, [string]$Tier, $ModelResults)
    if (-not $ModelResults -or $ModelResults.Count -eq 0) { return }
    $ok    = @($ModelResults | Where-Object { $_.response_len -gt 0 })
    $empty = @($ModelResults | Where-Object { $_.response_len -eq 0 })
    $trunc = @($ModelResults | Where-Object { $_.done_reason -eq "length" })
    $avgTok = if ($ok.Count -gt 0) { [math]::Round(($ok | Measure-Object tok_s -Average).Average, 2) } else { 0 }
    Write-Log ("-" * 60) "DarkCyan"
    Write-Log "  RECAP [$Tier] $Model" "Cyan"
    $color = if ($empty.Count -gt 0) { "Red" } elseif ($avgTok -ge 10) { "Green" } else { "White" }
    Write-Log "  Runs OK:$($ok.Count)/$($ModelResults.Count)  Vides:$($empty.Count)  Tronquees:$($trunc.Count)  Moy:${avgTok} tok/s" $color
    Write-Log ("-" * 60) "DarkCyan"
}

# ==========================================
#  RAPPORT MARKDOWN FINAL
# ==========================================
function Export-MarkdownReport {
    param([string]$OutPath)
    $sb = [System.Text.StringBuilder]::new()
    [void]$sb.AppendLine("# Rapport Benchmark Ollama - $script:Version")
    [void]$sb.AppendLine("**Mode :** $Mode  ")
    [void]$sb.AppendLine("**Date :** $(Get-Date -Format 'yyyy-MM-dd HH:mm')  ")
    [void]$sb.AppendLine("**Duree :** $(Format-Elapsed)  ")
    [void]$sb.AppendLine("")
    [void]$sb.AppendLine("## Classement par vitesse (tok/s moyen)")
    [void]$sb.AppendLine("")
    [void]$sb.AppendLine("| Modele | Tier | Tok/s | VRAM (MB) | GPU% | RAM (MB) | Runs | Vides | Tronquees |")
    [void]$sb.AppendLine("|--------|------|-------|-----------|------|----------|------|-------|-----------|")

    $classement = $script:Results | Where-Object { $_.tok_s -gt 0 } | Group-Object model | ForEach-Object {
        $grp = $_.Group
        [PSCustomObject]@{
            Modele  = $_.Name
            Tier    = ($grp | Select-Object -First 1).tier
            TokS    = [math]::Round(($grp | Measure-Object tok_s -Average).Average, 1)
            VRAM    = [math]::Round(($grp | Measure-Object vram_after -Average).Average, 0)
            GPU     = [math]::Round(($grp | Measure-Object gpu_util_pct -Average).Average, 0)
            RAM     = [math]::Round(($grp | Measure-Object ram_avg_mb -Average).Average, 0)
            Runs    = $grp.Count
            Vides   = ($grp | Where-Object { $_.response_len -eq 0 }).Count
            Tronc   = ($grp | Where-Object { $_.done_reason -eq "length" }).Count
        }
    } | Sort-Object TokS -Descending

    foreach ($c in $classement) {
        [void]$sb.AppendLine("| $($c.Modele) | $($c.Tier) | $($c.TokS) | $($c.VRAM) | $($c.GPU) | $($c.RAM) | $($c.Runs) | $($c.Vides) | $($c.Tronc) |")
    }

    [void]$sb.AppendLine("")
    [void]$sb.AppendLine("## Erreurs LLM ($($script:LLMErrors.Count))")
    if ($script:LLMErrors.Count -eq 0) {
        [void]$sb.AppendLine("Aucune erreur.")
    } else {
        foreach ($e in ($script:LLMErrors | Group-Object category | Sort-Object Count -Descending)) {
            [void]$sb.AppendLine("- **$($e.Name)** : $($e.Count)x")
            $first = $e.Group | Select-Object -First 1
            [void]$sb.AppendLine("  - Suggestion : $($first.suggestion)")
        }
    }
    [void]$sb.AppendLine("")
    [void]$sb.AppendLine("## Fichiers generes")
    [void]$sb.AppendLine("- CSV : ``$($script:CSVFile)``")
    [void]$sb.AppendLine("- Log : ``$($script:LogFile)``")
    [void]$sb.AppendLine("- Erreurs : ``$($script:ErrLogFile)``")
    [void]$sb.AppendLine("- Reponses : ``$($script:ResponseDir)``")

    $sb.ToString() | Out-File $OutPath -Encoding UTF8
    Write-Log "Rapport Markdown : $OutPath" "Green"
}

# ==========================================
#  HEADER
# ==========================================
$resumeLabel = if ($script:IsResume) { " [REPRISE depuis $($script:RunsDone) runs]" } else { "" }
$hdr = @"

##############################################################
##   BENCHMARK OLLAMA $script:Version  --  $(Get-Date -Format 'yyyy-MM-dd HH:mm')$resumeLabel
##   MODE : $Mode
##   GPU : Quadro M2000M | VRAM : 4 GB
##   GPU models : $($script:ModelsTierGPU.Count)    CPU models : $($script:ModelsTierCPU.Count)
##   Modeles actifs : $($script:AllModels.Count)
##   Prompts : $($($script:Prompts.Keys) -join ', ')
##   Runs/prompt: $RunsPerPrompt    Total runs : $($script:RunsTotal)
##   Seuils : RAM_FREE_MIN=$script:RAM_FREE_MIN_MB MB | OLLAMA_RAM_MAX=$script:OLLAMA_RAM_MAX_MB MB
##   Results : $script:ResultsDir
##############################################################

"@
Write-Host $hdr -ForegroundColor DarkCyan
Add-Content $script:LogFile $hdr -Encoding UTF8

# ==========================================
#  DEMARRAGE
# ==========================================
Load-ProgressState

if (-not (Test-SystemHealth)) {
    Write-Log "HEALTHCHECK ECHOUE - arret" "Red"
    exit 1
}

$gpuInit = Get-GpuSnap
Write-Log "GPU init  : $($gpuInit.U)/$($gpuInit.T) MB VRAM | $($gpuInit.G)% | $($gpuInit.C)C" "White"
Write-Log "RAM libre : $(Get-FreeRAM_MB) MB | Ollama : $(Get-OllamaRAM_MB) MB" "White"
Write-Log "Mode      : $Mode ($($script:AllModels.Count) modeles)" "White"
Update-Dashboard -CurrentModel "demarrage..." -CurrentPrompt "-" -CurrentRun 0 -RunTotal $RunsPerPrompt -Phase "INIT"

if ($WhatIf) {
    Write-Log "=== MODE SIMULATION (WhatIf) ===" "Magenta"
    Write-Log "Aucune inference ne sera lancee." "Magenta"
    foreach ($m in $script:AllModels) {
        $isCPU = $script:ModelsTierCPU -contains $m
        $fam = "default"
        if ($m -match "gemma4") { $fam = "gemma4" }
        elseif ($m -match "phi[34]") { $fam = "phi3" }
        elseif ($m -match "qwen3") { $fam = "qwen3" }
        elseif ($m -match "gemma3") { $fam = "gemma3" }
        $mult = $script:TokenMultipliers[$fam]
        foreach ($pk in $script:Prompts.Keys) {
            $to = Get-AdaptiveTimeout -ModelName $m -PromptKey $pk -IsCPU $isCPU
            $np = $script:Prompts[$pk].tokens * $mult * $(if ($m -match "^qwen3:|deepseek-r1|reasoning") { 2 } else { 1 })
            Write-Log "  [DRYRUN] $m | $pk | timeout=${to}s | num_predict=$np | CPU=$isCPU" "DarkGray"
        }
    }
    exit 0
}

# ==========================================
#  BOUCLE PRINCIPALE
# ==========================================
$modelIdx = 0
foreach ($model in $script:AllModels) {
    $modelIdx++

    if ($script:Done["done_$model"] -in @("ok","skip","skip_warmup","skip_oom")) {
        $lbl = $script:Done["done_$model"]
        Write-Log "[SKIP resume] [$modelIdx/$($script:AllModels.Count)] $model ($lbl)" "DarkGray"
        if ($lbl -eq "ok" -and -not ($script:ModelesOk -contains $model)) {
            $script:ModelesDone++; $script:ModelesOk.Add($model)
        } elseif ($lbl -ne "ok") {
            $script:ModelesDone++
            if (-not ($script:ModelesSkip -contains $model)) { $script:ModelesSkip.Add($model) }
        }
        continue
    }

    $ramFree = Get-FreeRAM_MB
    $ollamaRam = Get-OllamaRAM_MB
    Update-Dashboard -CurrentModel $model -CurrentPrompt "init" -CurrentRun 0 -RunTotal $RunsPerPrompt -Phase "VERIF RAM"
    Write-Log ""
    Write-Log ("=" * 72) "Magenta"
    Write-Log "  [$modelIdx/$($script:AllModels.Count)] $model  | RAM libre : ${ramFree} MB | Ollama : ${ollamaRam} MB" "Magenta"
    Write-Log ("=" * 72) "Magenta"

    if ($ramFree -lt $script:RAM_FREE_MIN_MB) {
        Write-Log "  [SKIP OOM-RISK] RAM libre ${ramFree} MB < seuil $script:RAM_FREE_MIN_MB MB -> skip $model" "Red"
        Write-LogError -Model $model -Prompt "N/A" -Run 0 -ErrorMessage "RAM libre ${ramFree} MB < seuil" -Category "oom_or_crash"
        $script:Done["done_$model"] = "skip_oom"
        $script:ModelesDone++; $script:ModelesSkip.Add($model)
        Save-ProgressState
        continue
    }

    if (-not (Test-ModelExists $model)) {
        Write-Log "  [SKIP] $model : non disponible localement" "Red"
        Write-LogError -Model $model -Prompt "N/A" -Run 0 -ErrorMessage "Model not found" -Category "model_missing"
        $script:Done["done_$model"] = "skip"
        $script:ModelesDone++; $script:ModelesSkip.Add($model)
        Save-ProgressState
        continue
    }

    $isCPU       = $script:ModelsTierCPU -contains $model
    $tier        = if ($isCPU) { "CPU" } else { "GPU" }
    $isReasoning = $model -match "^qwen3:|deepseek-r1|reasoning"
    $temperature = if ($isReasoning) { 0.6 } else { 0 }

    $family = "default"
    if ($model -match "gemma4")  { $family = "gemma4" }
    elseif ($model -match "phi[34]") { $family = "phi3" }
    elseif ($model -match "qwen3")   { $family = "qwen3" }
    elseif ($model -match "gemma3")  { $family = "gemma3" }
    $tokMult = $script:TokenMultipliers[$family]

    $runsAlreadyDone = ($script:Done.Keys | Where-Object {
        $_ -like "run_$($model -replace '[:\\\/\s]','_')__*" -and $script:Done[$_] -eq "ok"
    }).Count
    $isPartialResume = $runsAlreadyDone -gt 0

    if ($isPartialResume) {
        Write-Log "  [REPRISE PARTIELLE] $runsAlreadyDone/$($script:Prompts.Count * $RunsPerPrompt) runs deja faits" "Yellow"
    }
    Write-Log "  tier=$tier | reasoning=$isReasoning | temp=$temperature | tokMult=${tokMult}x" "DarkGray"

    Update-Dashboard -CurrentModel $model -CurrentPrompt "-" -CurrentRun 0 -RunTotal $RunsPerPrompt -Phase "UNLOAD PRECEDENT"
    Unload-Model -ModelName $model
    Start-Sleep -Seconds 3

    Update-Dashboard -CurrentModel $model -CurrentPrompt "-" -CurrentRun 0 -RunTotal $RunsPerPrompt -Phase "WARMUP"
    Write-Log "  [WARMUP] Chargement $model ..." "DarkYellow"
    $warmupOk = $false
    for ($w = 1; $w -le 2; $w++) {
        try {
            $swW = [System.Diagnostics.Stopwatch]::StartNew()
            $warmupBody = @{
                model = $model; prompt = "hi"; stream = $false
                options = @{ num_predict = 5; num_gpu = if ($isCPU) { 0 } else { -1 } }
            } | ConvertTo-Json
            Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
                -Body $warmupBody -ContentType "application/json" -TimeoutSec 180 | Out-Null
            $swW.Stop()
            Write-Log "  [WARMUP] OK en $([math]::Round($swW.Elapsed.TotalMilliseconds,0)) ms" "Green"
            $warmupOk = $true; break
        } catch {
            $wErr = "$_"
            Write-Log "  [WARMUP] Tentative $w echouee : $wErr" "Yellow"
            Write-LogError -Model $model -Prompt "warmup" -Run $w -ErrorMessage $wErr -Category "warmup_fail"
            if ($w -eq 1) { Start-Sleep -Seconds (5 * $w); Restart-OllamaService }
        }
    }
    if (-not $warmupOk) {
        Write-Log "  [SKIP] $model warmup echoue x2" "Red"
        $script:Done["done_$model"] = "skip_warmup"
        $script:ModelesDone++; $script:ModelesSkip.Add($model)
        Save-ProgressState
        continue
    }

    $ollamaRam = Get-OllamaRAM_MB
    $ramFree = Get-FreeRAM_MB
    Write-Log "  [RAM apres warmup] Ollama=${ollamaRam} MB | Systeme libre=${ramFree} MB" "DarkGray"
    if ($ollamaRam -gt $script:OLLAMA_RAM_MAX_MB) {
        Write-Log "  [SKIP OOM-RISK] Ollama RAM ${ollamaRam} MB > max $script:OLLAMA_RAM_MAX_MB MB -> skip $model" "Red"
        Write-LogError -Model $model -Prompt "N/A" -Run 0 -ErrorMessage "Ollama RAM ${ollamaRam} MB apres warmup > seuil" -Category "oom_or_crash"
        Unload-Model -ModelName $model
        Start-Sleep -Seconds 5
        $script:Done["done_$model"] = "skip_oom"
        $script:ModelesDone++; $script:ModelesSkip.Add($model)
        Save-ProgressState
        continue
    }

    Write-Log "  [INFO] $(Get-ModelInfo $model)" "Gray"
    $gpuL = Get-GpuSnap
    Write-Log "  [GPU apres load] $($gpuL.U)/$($gpuL.T) MB | $($gpuL.G)% | $($gpuL.C)C" "Gray"
    Start-Sleep -Seconds 3

    $ModelRuns = [System.Collections.Generic.List[object]]::new()
    $promptIdx = 0

    foreach ($promptKey in $script:Prompts.Keys) {
        $promptIdx++
        Write-Log ""
        Write-Log "  --- [$promptIdx/$($script:Prompts.Count)] PROMPT : $promptKey ---" "White"

        $basePredict = $script:Prompts[$promptKey].tokens
        $numPredict  = $basePredict * $tokMult
        if ($isReasoning) { $numPredict = $numPredict * 2 }
        Write-Log "    base=$basePredict x tokMult=$tokMult x reasoning=$(if($isReasoning){'x2'}else{'x1'}) = num_predict=$numPredict" "DarkGray"

        $timeoutSec = Get-AdaptiveTimeout -ModelName $model -PromptKey $promptKey -IsCPU $isCPU
        Write-Log "    timeout adaptatif : ${timeoutSec}s (famille=$family | prompt=$promptKey | tier=$tier)" "DarkGray"

        for ($run = 1; $run -le $RunsPerPrompt; $run++) {
            $runKey = Get-RunKey -Model $model -Prompt $promptKey -Run $run
            if ($script:Done[$runKey] -eq "ok") {
                Write-Log "    [SKIP run] $model | $promptKey | run $run (deja fait)" "DarkGray"
                $script:RunsDone++
                Update-Dashboard -CurrentModel $model -CurrentPrompt $promptKey `
                    -CurrentRun $run -RunTotal $RunsPerPrompt -Phase "SKIP (deja fait)" -CurrentTimeoutSec $timeoutSec
                continue
            }

            Update-Dashboard -CurrentModel $model -CurrentPrompt $promptKey `
                -CurrentRun $run -RunTotal $RunsPerPrompt -Phase "INFERENCE" -CurrentTimeoutSec $timeoutSec

            Write-Log "    [RUN $run/$RunsPerPrompt] $model | $promptKey | predict=$numPredict | timeout=${timeoutSec}s" "Yellow"

            $gpu1 = Get-GpuSnap
            $cpu1 = if ($isCPU) { Get-CpuSnap } else { -1 }
            $ram1 = Get-OllamaRAM_MB
            Write-Log "      GPU=$($gpu1.U)/$($gpu1.T)MB | $($gpu1.G)% | $($gpu1.C)C | CPU=$cpu1% | OllamaRAM=${ram1}MB" "DarkGray"

            $opts = @{
                num_predict = $numPredict
                temperature = $temperature
                seed = 42
                num_gpu = if ($isCPU) { 0 } else { -1 }
            }

            $sw = [System.Diagnostics.Stopwatch]::StartNew()
            $resp = $null
            $errMsg = $null

            for ($attempt = 1; $attempt -le 2; $attempt++) {
                try {
                    $reqBody = @{
                        model = $model
                        prompt = $script:Prompts[$promptKey].text
                        stream = $false
                        options = $opts
                    } | ConvertTo-Json -Depth 5
                    $resp = Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
                        -Body $reqBody -ContentType "application/json" -TimeoutSec $timeoutSec
                    $errMsg = $null
                    break
                } catch {
                    $errMsg = "$_"
                    Write-Log "      [ERR attempt $attempt] $errMsg" "Red"
                    if ($attempt -lt 2) {
                        $backoff = 10 * $attempt
                        Write-Log "      [RETRY] Attente ${backoff}s..." "Yellow"
                        Update-Dashboard -CurrentModel $model -CurrentPrompt $promptKey `
                            -CurrentRun $run -RunTotal $RunsPerPrompt -Phase "RETRY backoff ${backoff}s" -CurrentTimeoutSec $timeoutSec
                        Start-Sleep -Seconds $backoff
                        if ($errMsg -match "500|terminated|oom") { Restart-OllamaService }
                    }
                }
            }
            $sw.Stop()

            $ram2    = Get-OllamaRAM_MB
            $gpu2    = Get-GpuSnap
            $cpu2    = if ($isCPU) { Get-CpuSnap } else { -1 }
            $totalMs = [math]::Round($sw.Elapsed.TotalMilliseconds, 1)
            $script:LastRunMs = $totalMs
            $script:RunsDone++

            if ($resp) {
                $tok      = Calc-TokPerSec $resp
                $tokOut   = if ($resp.eval_count) { $resp.eval_count } else { 0 }
                $loadMs   = if ($resp.load_duration) { [math]::Round($resp.load_duration / 1e6, 1) } else { 0 }
                $evalMs   = if ($resp.eval_duration) { [math]::Round($resp.eval_duration / 1e6, 1) } else { 0 }
                $promptMs = if ($resp.prompt_eval_duration) { [math]::Round($resp.prompt_eval_duration / 1e6, 1) } else { 0 }
                $ramAvg   = [int](($ram1 + $ram2) / 2)
                $doneRsn  = if ($resp.done_reason) { $resp.done_reason } else { "" }
                $rtext    = if ($resp.response) { $resp.response } else { "" }

                $script:LastTok = $tok

                if ($rtext.Length -eq 0) {
                    Write-Log "      [!!!] REPONSE VIDE eval_count=$tokOut done_reason=$doneRsn" "Red"
                    Write-LogError -Model $model -Prompt $promptKey -Run $run -ErrorMessage "Empty response" `
                        -Options $opts -DoneReason $doneRsn -ResponseLen 0 -TokensOut $tokOut -TimeoutUsed $timeoutSec
                } elseif ($doneRsn -eq "length") {
                    Write-Log "      [TRUNC] Tronquee -> suggere num_predict $numPredict -> $($numPredict*2) en V9" "Yellow"
                    Write-LogError -Model $model -Prompt $promptKey -Run $run `
                        -ErrorMessage "Truncated (done_reason=length)" -Options $opts `
                        -DoneReason $doneRsn -ResponseLen $rtext.Length -TokensOut $tokOut `
                        -Category "truncated_response" -TimeoutUsed $timeoutSec
                } elseif ($rtext.Length -lt 50) {
                    Write-Log "      [WARN] Reponse courte ($($rtext.Length) chars)" "Yellow"
                }

                if ($rtext.Length -gt 0) { Save-ResponseToFile -Model $model -Prompt $promptKey -Run $run -Content $rtext }

                $color = if ($tok -ge 20) { "Green" } elseif ($tok -ge 8) { "Yellow" } else { "DarkYellow" }
                Write-Log ("      [OK] {0} tok/s | {1}ms | load {2}ms | eval {3}ms | {4} tok | RAM {5}MB | GPU {6}MB | len={7} | {8}" -f `
                    $tok, $totalMs, $loadMs, $evalMs, $tokOut, $ramAvg, $gpu2.U, $rtext.Length, $doneRsn) $color

                $row = [PSCustomObject]@{
                    model=$model; tier=$tier; mode=$Mode; prompt=$promptKey; run=$run
                    tok_s=$tok; tokens_out=$tokOut; total_ms=$totalMs
                    load_ms=$loadMs; eval_ms=$evalMs; prompt_ms=$promptMs
                    ram_avg_mb=$ramAvg; vram_before=$gpu1.U; vram_after=$gpu2.U
                    vram_delta=($gpu2.U - $gpu1.U); gpu_util_pct=$gpu2.G
                    cpu_util_pct=$cpu2; temp_c=$gpu2.C; done_reason=$doneRsn
                    response_len=$rtext.Length; error=""
                    num_predict_used=$numPredict; tok_multiplier=$tokMult
                    timeout_sec=$timeoutSec
                    response_snippet=(& { if ($rtext.Length -gt 0) { $rtext.Substring(0,[Math]::Min(500,$rtext.Length)) } else { "" } })
                }
                $script:Results.Add($row)
                $ModelRuns.Add($row)
                $script:Done[$runKey] = "ok"
                Save-ProgressState

            } else {
                $script:LastTok = 0
                Write-LogError -Model $model -Prompt $promptKey -Run $run `
                    -ErrorMessage (& { if ($errMsg) { $errMsg } else { "Unknown error after 2 retries" } }) `
                    -Options $opts -TimeoutUsed $timeoutSec

                $row = [PSCustomObject]@{
                    model=$model; tier=$tier; mode=$Mode; prompt=$promptKey; run=$run
                    tok_s=0; tokens_out=0; total_ms=$totalMs
                    load_ms=0; eval_ms=0; prompt_ms=0
                    ram_avg_mb=[int](($ram1+$ram2)/2)
                    vram_before=$gpu1.U; vram_after=$gpu2.U; vram_delta=0
                    gpu_util_pct=$gpu2.G; cpu_util_pct=$cpu2; temp_c=$gpu2.C
                    done_reason=""; response_len=0; error=$errMsg
                    num_predict_used=$numPredict; tok_multiplier=$tokMult
                    timeout_sec=$timeoutSec; response_snippet=""
                }
                $script:Results.Add($row)
                $ModelRuns.Add($row)
                $script:Done[$runKey] = "error"
                Save-ProgressState
            }

            $script:Results | Export-Csv $script:CSVFile -NoTypeInformation -Encoding UTF8 -Force

            Update-Dashboard -CurrentModel $model -CurrentPrompt $promptKey `
                -CurrentRun $run -RunTotal $RunsPerPrompt -Phase "RUN $run TERMINE" -CurrentTimeoutSec $timeoutSec

            Start-Sleep -Seconds 4
        }
    }

    $allRunsOk = $true
    foreach ($pk in $script:Prompts.Keys) {
        for ($r = 1; $r -le $RunsPerPrompt; $r++) {
            if ($script:Done[(Get-RunKey -Model $model -Prompt $pk -Run $r)] -ne "ok") {
                $allRunsOk = $false; break
            }
        }
        if (-not $allRunsOk) { break }
    }

    if ($allRunsOk) {
        $script:Done["done_$model"] = "ok"
        Save-ProgressState
        $script:ModelesDone++
        $script:ModelesOk.Add($model)
        Write-Log "  [DONE] $model : tous les runs OK" "Green"
    } else {
        Write-Log "  [PARTIAL] $model : reprise possible au prochain lancement" "Yellow"
    }

    Show-ModelSummary -Model $model -Tier $tier -ModelResults $ModelRuns
    Update-Dashboard -CurrentModel $model -CurrentPrompt "-" -CurrentRun 0 -RunTotal $RunsPerPrompt -Phase "UNLOAD + PAUSE"

    Unload-Model -ModelName $model
    Start-Sleep -Seconds 8
}

# ==========================================
#  EXPORT FINAL
# ==========================================
$allDone = ($script:Done.Keys | Where-Object { $_ -like "done_*" -and $script:Done[$_] -in @("ok","skip","skip_warmup","skip_oom") }).Count -eq $script:AllModels.Count
if ($allDone) {
    Remove-Item $script:ProgressFile -Force -ErrorAction SilentlyContinue
    Write-Log "[PROGRESS] Benchmark complet - fichier de progression supprime" "Green"
} else {
    Write-Log "[PROGRESS] Conserve pour reprise : $script:ProgressFile" "Yellow"
}

$csvFinal = [System.IO.Path]::Combine($script:ResultsDir, "bench_gpu_FINAL_${script:Version}_${Mode}_$(Get-Date -Format 'yyyyMMdd_HHmmss').csv")
$script:Results | Export-Csv $csvFinal -NoTypeInformation -Encoding UTF8

$elapsed = (Get-Date) - $script:StartTime
$elapsedStr = "$([int]$elapsed.TotalHours)h $($elapsed.Minutes.ToString('00'))m $($elapsed.Seconds.ToString('00'))s"

Update-Dashboard -CurrentModel "TERMINE" -CurrentPrompt "-" -CurrentRun 0 -RunTotal $RunsPerPrompt -Phase "FIN"

Write-Log ""
Write-Log ("=" * 72) "Cyan"
Write-Log "  FIN BENCHMARK $script:Version [$Mode]  $(Get-Date -Format 'yyyy-MM-dd HH:mm')  (duree : $elapsedStr)" "Cyan"
Write-Log "  CSV final   : $csvFinal" "Green"
Write-Log "  Erreurs LLM : $script:ErrLogFile ($($script:LLMErrors.Count) entrees)" $(if ($script:LLMErrors.Count -gt 0) { "Yellow" } else { "Green" })
Write-Log "  Reponses    : $script:ResponseDir" "Green"
Write-Log ("=" * 72) "Cyan"
Write-Log ""

Export-MarkdownReport -OutPath $script:ReportFile

Write-Log "=== CLASSEMENT FINAL [$Mode] ===" "Cyan"
$script:Results | Where-Object { $_.tok_s -gt 0 } | Group-Object model | ForEach-Object {
    $grp = $_.Group
    [PSCustomObject]@{
        Modele  = $_.Name
        Tier    = ($grp | Select-Object -First 1).tier
        Mode    = $Mode
        TokS    = [math]::Round(($grp | Measure-Object tok_s -Average).Average, 1)
        VRAM_MB = [math]::Round(($grp | Measure-Object vram_after -Average).Average, 0)
        GPU_pct = [math]::Round(($grp | Measure-Object gpu_util_pct -Average).Average, 0)
        CPU_pct = if (($grp | Select-Object -First 1).cpu_util_pct -eq -1) { "N/A" } `
                  else { [math]::Round(($grp | Where-Object { $_.cpu_util_pct -ge 0 } | Measure-Object cpu_util_pct -Average).Average, 0) }
        RAM_MB  = [math]::Round(($grp | Measure-Object ram_avg_mb -Average).Average, 0)
        RespAvg = [math]::Round(($grp | Measure-Object response_len -Average).Average, 0)
        Vides   = ($grp | Where-Object { $_.response_len -eq 0 }).Count
        Tronc   = ($grp | Where-Object { $_.done_reason -eq "length" }).Count
        Runs    = $grp.Count
    }
} | Sort-Object TokS -Descending | Format-Table -AutoSize

Write-Log ""
Write-Log "=== DIAGNOSTICS ERREURS LLM ===" "Yellow"
if ($script:LLMErrors.Count -eq 0) {
    Write-Log "  Aucune erreur enregistree." "Green"
} else {
    Write-Log "  $($script:LLMErrors.Count) erreur(s) -> $script:ErrLogFile" "Yellow"
    $script:LLMErrors | Group-Object category | Sort-Object Count -Descending | ForEach-Object {
        Write-Log "  [$($_.Count)x] $($_.Name)" "Yellow"
        $_.Group | Select-Object -First 1 | ForEach-Object { Write-Log "       Fix : $($_.suggestion)" "DarkYellow" }
    }
}

Write-Log ""
Write-Log "=== REPONSES VIDES ===" "Yellow"
$empty = $script:Results | Where-Object { $_.response_len -eq 0 -and $_.error -eq "" }
if ($empty.Count -eq 0) { Write-Log "  Aucune." "Green" }
else { $empty | Select-Object model, prompt, run, tok_s, done_reason, tokens_out, num_predict_used | Format-Table -AutoSize }

Write-Log ""
Write-Log "=== REPONSES TRONQUEES ===" "Yellow"
$trunc = $script:Results | Where-Object { $_.done_reason -eq "length" }
if ($trunc.Count -eq 0) { Write-Log "  Aucune." "Green" }
else {
    $trunc | Select-Object model, prompt, run, tokens_out, response_len, num_predict_used, tok_multiplier, timeout_sec | Format-Table -AutoSize
    Write-Log "  -> Augmenter tok_multiplier pour ces modeles/prompts en V9" "DarkYellow"
}