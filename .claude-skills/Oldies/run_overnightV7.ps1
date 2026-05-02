# run_overnightV7.ps1
# Benchmark GPU/CPU hybride - Quadro M2000M (4GB VRAM CUDA)
# Lancer via prepare_and_launch.ps1 -- ne pas lancer directement
# ASCII pur - pas d accents dans ce fichier
#
# V7 (2026-04-27) -- CORRECTIFS critiques issus du crash V4 / analyse V6 :
#
#   [MODE]      3 modes de test selectionnables au lancement :
#               -Mode GPU      : uniquement les modeles GPU (ModelsTierGPU)
#               -Mode CPU      : uniquement les modeles CPU (ModelsTierCPU)
#               -Mode Hybride  : tous les modeles (defaut, comportement V6)
#               Exemple : .\run_overnightV7.ps1 -Mode GPU
#
#   [TIMEOUT]   Systeme de timeout adaptatif par famille + prompt + tier :
#               - Table $TimeoutTable[famille][prompt] avec valeurs basees sur
#                 les observations V4 (phi4 3x timeout a 600s sur coding_lcca).
#               - Fallback progressif : famille -> tier -> prompt -> defaut.
#               - Minimum garanti $TIMEOUT_MIN_SEC, maximum $TIMEOUT_MAX_SEC.
#               - Valeur affichee dans les logs pour tracabilite.
#               Regle les 3x timeout phi4-mini-reasoning sur coding_lcca.
#
#   [CRASH-OOM] Garde-fou RAM avant chaque modele :
#               Si RAM systeme libre < RAM_FREE_MIN_MB (defaut 3000 MB),
#               le modele est skipped avec motif "oom_risk".
#               Evite le crash systeme de gemma4:e4b (14 GB RAM Ollama).
#
#   [CRASH-OOM] Surveillance RAM Ollama apres warmup :
#               Si Ollama depasse OLLAMA_RAM_MAX_MB apres chargement,
#               on unload + skip plutot que de continuer.
#
#   [TOKENS]    gemma4:* : num_predict x4 (modeles avec thinking block natif
#               qui consomme tout le budget avant la reponse visible).
#               gemma3:* : num_predict x2 pour code_simple (truncation observee).
#               qwen3:*  : num_predict x3 pour coding_lcca reasoning (trop court).
#
#   [REPRISE]   Reprise granulaire au niveau run individuel (heritee de V6).
#               Cle : "run_MODEL__PROMPT__RUN" = "ok|error"
#               Recharge CSV incremental au demarrage.
#               En cas de crash systeme, relancer suffit.
#
#   [RETRY]     2 tentatives par run avec backoff (10s puis 20s).
#               Restart Ollama automatique sur 500/terminated/oom.
#
#   [EXPORT]    CSV incremental sauve apres CHAQUE run (pas seulement apres chaque modele).
#               Plus de perte de donnees entre deux modeles.
#
#   [ERRLOG]    Fichier JSON d erreurs categorisees avec suggestion de fix.
#
#   [DASHBOARD] Dashboard inline mis a jour en temps reel.
#
#   [TEMP]      Alerte si GPU > 85C.

param(
    [ValidateSet("GPU", "CPU", "Hybride")]
    [string]$Mode = "Hybride"
)

$ErrorActionPreference = "Continue"
$ResultsDir  = "$PSScriptRoot\CPUVsGPU\results"
$ResponseDir = "$ResultsDir\responses"
$LogFile     = "$ResultsDir\bench_gpu_$(Get-Date -Format 'yyyyMMdd_HHmm').log"
$ErrLogFile  = "$ResultsDir\llm_errors_$(Get-Date -Format 'yyyyMMdd_HHmm').json"

New-Item -ItemType Directory -Force -Path $ResultsDir  | Out-Null
New-Item -ItemType Directory -Force -Path $ResponseDir | Out-Null

# ==========================================
#  SEUILS SECURITE MEMOIRE
# ==========================================
$RAM_FREE_MIN_MB  = 3000   # RAM systeme libre minimum avant de charger un modele
$OLLAMA_RAM_MAX_MB = 13000  # RAM Ollama max apres warmup avant skip (gemma4:e4b = 14GB -> crash)
$GPU_TEMP_WARN     = 85

# ==========================================
#  TIMEOUT ADAPTATIF
# ==========================================
# Valeurs en secondes. Logique de resolution (ordre decroissant de priorite) :
#   1. $TimeoutTable[famille][prompt]   -> valeur specifique famille+prompt
#   2. $TimeoutTable[famille]["_default"] -> fallback famille
#   3. $TimeoutTable["_tier_cpu"]         -> fallback tier CPU
#   4. $TimeoutTable["_tier_gpu"]         -> fallback tier GPU
#   5. $TIMEOUT_DEFAULT_SEC              -> dernier recours
#
# Base de calibration V4/V7 :
#   phi4-mini-reasoning : coding_lcca  -> 3x timeout a 600s => 7200s choisi
#   qwen3 reasoning     : coding_lcca  -> long chain of thought => 5400s
#   deepseek-r1 (CPU)   : coding_lcca  -> 8b/14b sur CPU => 7200s
#   gemma4 e4b          : thinking block => 5400s sur coding_lcca
#   defaut GPU          : 900s  (conservateur, evite blocages longs)
#   defaut CPU          : 5400s (CPU = lent, mais 3600 etait trop juste sur V4)
#
$TIMEOUT_MIN_SEC     = 120    # jamais moins de 2 min (securite contre config erronee)
$TIMEOUT_MAX_SEC     = 10800  # plafond 3h (evite blocage infini)
$TIMEOUT_DEFAULT_SEC = 900    # fallback si aucune regle ne matche

$TimeoutTable = @{
    # --- Famille phi4 (phi4-mini-reasoning, phi4) ---
    "phi4" = @{
        "code_simple" = 900
        "debug"       = 1200
        "coding_lcca" = 7200   # V4 : 3x timeout a 600s -> 7200s confirme
        "_default"    = 2400
    }
    # --- Famille qwen3 (reasoning, long CoT) ---
    "qwen3" = @{
        "code_simple" = 1200
        "debug"       = 1800
        "coding_lcca" = 5400
        "_default"    = 2400
    }
    # --- Famille qwen2.5 ---
    "qwen2" = @{
        "code_simple" = 600
        "debug"       = 900
        "coding_lcca" = 1800
        "_default"    = 1200
    }
    # --- Famille deepseek-r1 (CPU, reasoning) ---
    "deepseek" = @{
        "code_simple" = 1800
        "debug"       = 2400
        "coding_lcca" = 7200
        "_default"    = 3600
    }
    # --- Famille gemma4 (thinking block natif) ---
    "gemma4" = @{
        "code_simple" = 1200
        "debug"       = 1800
        "coding_lcca" = 5400
        "_default"    = 2400
    }
    # --- Famille gemma3 ---
    "gemma3" = @{
        "code_simple" = 600
        "debug"       = 900
        "coding_lcca" = 2400
        "_default"    = 1200
    }
    # --- Fallbacks par tier ---
    "_tier_gpu" = 900
    "_tier_cpu" = 5400
}

function Get-AdaptiveTimeout {
    param(
        [string]$ModelName,
        [string]$PromptKey,
        [bool]$IsCPU
    )
    # Detection famille
    $fam = "unknown"
    if ($ModelName -match "phi[34]")      { $fam = "phi4" }
    elseif ($ModelName -match "qwen3")    { $fam = "qwen3" }
    elseif ($ModelName -match "qwen2")    { $fam = "qwen2" }
    elseif ($ModelName -match "deepseek") { $fam = "deepseek" }
    elseif ($ModelName -match "gemma4")   { $fam = "gemma4" }
    elseif ($ModelName -match "gemma3")   { $fam = "gemma3" }

    $resolved = $TIMEOUT_DEFAULT_SEC

    if ($fam -ne "unknown" -and $TimeoutTable.ContainsKey($fam)) {
        $famTable = $TimeoutTable[$fam]
        if ($famTable.ContainsKey($PromptKey)) {
            $resolved = $famTable[$PromptKey]
        } elseif ($famTable.ContainsKey("_default")) {
            $resolved = $famTable["_default"]
        }
    } elseif ($IsCPU -and $TimeoutTable.ContainsKey("_tier_cpu")) {
        $resolved = $TimeoutTable["_tier_cpu"]
    } elseif (-not $IsCPU -and $TimeoutTable.ContainsKey("_tier_gpu")) {
        $resolved = $TimeoutTable["_tier_gpu"]
    }

    # Bornes de securite
    $resolved = [Math]::Max($TIMEOUT_MIN_SEC, [Math]::Min($TIMEOUT_MAX_SEC, $resolved))
    return $resolved
}

$LLMErrors = [System.Collections.Generic.List[object]]::new()

# ==========================================
#  DASHBOARD INLINE
# ==========================================
$script:DashRow      = -1
$script:DashHeight   = 13
$script:BenchStart   = [DateTime]::Now
$script:LastTok      = 0.0
$script:LastRunMs    = 0
$script:RunsDone     = 0
$script:RunsTotal    = 0
$script:ModelesDone  = 0
$script:ModelesTotal = 0
$script:ModelesOk    = [System.Collections.Generic.List[string]]::new()
$script:ModelesSkip  = [System.Collections.Generic.List[string]]::new()
$script:IsResume     = $false
$script:LastRAMFree  = 0
$script:LastOllamaRAM = 0

function Format-ETA {
    param([int]$Sec)
    if ($Sec -le 0) { return "calcul..." }
    if ($Sec -ge 3600) { return "$([int]($Sec/3600))h $([int](($Sec%3600)/60))m" }
    if ($Sec -ge 60)   { return "$([int]($Sec/60))m $($Sec%60)s" }
    return "${Sec}s"
}

function Format-Elapsed {
    $e = ([DateTime]::Now - $script:BenchStart)
    return "$([int]$e.TotalHours)h $($e.Minutes.ToString('00'))m $($e.Seconds.ToString('00'))s"
}

function Draw-Bar {
    param([int]$Pct, [int]$Width = 30)
    $filled = [int]($Width * $Pct / 100)
    $empty  = $Width - $filled
    return ("[" + ("#" * $filled) + ("-" * $empty) + "] $Pct%")
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

function Update-Dashboard {
    param(
        [string]$CurrentModel   = "",
        [string]$CurrentPrompt  = "",
        [int]$CurrentRun        = 0,
        [int]$RunTotal          = 3,
        [string]$Phase          = "",
        [int]$CurrentTimeoutSec = 0
    )
    $elapsed   = ([DateTime]::Now - $script:BenchStart).TotalSeconds
    $doneFrac  = if ($script:RunsTotal -gt 0) { $script:RunsDone / $script:RunsTotal } else { 0 }
    $etaSec    = if ($doneFrac -gt 0.02) { [int]($elapsed / $doneFrac * (1 - $doneFrac)) } else { 0 }
    $pctGlobal = [int]($doneFrac * 100)
    $bar       = Draw-Bar -Pct $pctGlobal
    $tokStr    = if ($script:LastTok -gt 0) { "$($script:LastTok) tok/s" } else { "---" }
    $resumeTag = if ($script:IsResume) { " [REPRISE]" } else { "" }
    $modeTag   = " [MODE:$Mode]"
    $ramStr    = "RAM libre: $($script:LastRAMFree) MB | Ollama: $($script:LastOllamaRAM) MB"
    $toStr     = if ($CurrentTimeoutSec -gt 0) { "timeout: ${CurrentTimeoutSec}s" } else { "" }
    $W   = 72
    $sep = "=" * $W
    $derniersOk = if ($script:ModelesOk.Count -gt 0) { ($script:ModelesOk | Select-Object -Last 4) -join ", " } else { "(aucun)" }
    $lines = @(
        $sep,
        ("  BENCHMARK V7{0}{1} | Elapsed: {2,-12} | ETA: {3,-14}" -f $resumeTag, $modeTag, (Format-Elapsed), (Format-ETA $etaSec)),
        ("  Progression : {0}" -f $bar),
        ("  Modeles  : {0}/{1} OK | {2} skips | {3}" -f $script:ModelesDone, $script:ModelesTotal, $script:ModelesSkip.Count, $ramStr),
        ("  Derniers OK : {0}" -f $derniersOk),
        $sep,
        ("  Modele courant : [{0}/{1}] {2}" -f ($script:ModelesDone + 1), $script:ModelesTotal, $CurrentModel),
        ("  Prompt  : {0,-22} Run : {1}/{2}" -f $CurrentPrompt, $CurrentRun, $RunTotal),
        ("  Phase   : {0,-30} {1}  {2}" -f $Phase, $tokStr, $toStr),
        ("  Runs    : {0}/{1}   Dernier : {2} ms" -f $script:RunsDone, $script:RunsTotal, $script:LastRunMs),
        $sep,
        ""
    )
    if ($script:DashRow -lt 0) { $script:DashRow = [Console]::CursorTop }
    $savedTop = [Console]::CursorTop
    [Console]::SetCursorPosition(0, $script:DashRow)
    foreach ($l in $lines) { Write-Host $l.PadRight($W) -ForegroundColor Cyan }
    $logRow = [Math]::Max($savedTop, $script:DashRow + $script:DashHeight)
    [Console]::SetCursorPosition(0, $logRow)
}

# ==========================================
#  LOG
# ==========================================
function Log {
    param([string]$M, [string]$C = "White")
    $validColors = [System.Enum]::GetNames([System.ConsoleColor])
    if ([string]::IsNullOrWhiteSpace($C) -or ($C -notin $validColors)) { $C = "White" }
    $L = "[$(Get-Date -Format 'HH:mm:ss')] $M"
    if ($script:DashRow -ge 0) {
        $cur = [Console]::CursorTop
        if ($cur -lt $script:DashRow + $script:DashHeight) {
            [Console]::SetCursorPosition(0, $script:DashRow + $script:DashHeight)
        }
    }
    Write-Host $L -ForegroundColor $C
    Add-Content $LogFile $L -Encoding UTF8
}

# ==========================================
#  LOGERROR
# ==========================================
function LogError {
    param(
        [string]$Model, [string]$Prompt, [int]$Run,
        [string]$ErrorMessage, [hashtable]$Options = @{},
        [string]$DoneReason = "", [int]$ResponseLen = 0,
        [int]$TokensOut = 0, [string]$Category = "unknown",
        [int]$TimeoutUsed = 0
    )
    if ($Category -eq "unknown") {
        if ($ErrorMessage -match "500|internal server error")          { $Category = "server_error_500" }
        elseif ($ErrorMessage -match "timeout|timedout|timed out")     { $Category = "timeout" }
        elseif ($ErrorMessage -match "terminated|killed|oom|out.of.memory") { $Category = "oom_or_crash" }
        elseif ($ResponseLen -eq 0 -and $DoneReason -ne "stop")       { $Category = "empty_response" }
        elseif ($DoneReason -eq "length")                              { $Category = "truncated_response" }
        else                                                           { $Category = "other" }
    }
    $suggestion = switch ($Category) {
        "server_error_500"   { "Restart Ollama. Reduce num_predict. Check VRAM." }
        "timeout"            { "Increase TimeoutSec in TimeoutTable. Reduce num_predict. Use smaller quant. Current: ${TimeoutUsed}s" }
        "oom_or_crash"       { "RAM_FREE_MIN_MB threshold hit. Reduce model tier or add RAM." }
        "empty_response"     { "Model has thinking block: multiply num_predict x4." }
        "truncated_response" { "Increase num_predict. Response cut short by token budget." }
        default              { "Review error message and adjust options." }
    }
    $LLMErrors.Add([PSCustomObject]@{
        timestamp    = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        model        = $Model; prompt = $Prompt; run = $Run
        category     = $Category; error_msg = $ErrorMessage
        done_reason  = $DoneReason; response_len = $ResponseLen; tokens_out = $TokensOut
        options_used = $Options; suggestion = $suggestion; timeout_sec = $TimeoutUsed
    })
    $LLMErrors | ConvertTo-Json -Depth 6 | Out-File $ErrLogFile -Encoding UTF8 -Force
    Log "    [ERR-LOG] $Category => $suggestion" "DarkYellow"
}

# ==========================================
#  RECAP PAR MODELE
# ==========================================
function Show-ModelSummary {
    param([string]$Model, [string]$Tier, $ModelResults)
    if (-not $ModelResults -or $ModelResults.Count -eq 0) { return }
    $ok    = @($ModelResults | Where-Object { $_.response_len -gt 0 })
    $empty = @($ModelResults | Where-Object { $_.response_len -eq 0 })
    $trunc = @($ModelResults | Where-Object { $_.done_reason  -eq "length" })
    $avgTok = if ($ok.Count -gt 0) { [math]::Round(($ok | Measure-Object tok_s -Average).Average, 2) } else { 0 }
    Log ("-" * 60) "DarkCyan"
    Log ("  RECAP [{0}] {1}" -f $Tier, $Model) "Cyan"
    Log ("  Runs OK:{0}/{1}  Vides:{2}  Tronquees:{3}  Moy:{4} tok/s" -f $ok.Count, $ModelResults.Count, $empty.Count, $trunc.Count, $avgTok) `
        $(if ($empty.Count -gt 0) { "Red" } elseif ($avgTok -ge 10) { "Green" } else { "White" })
    Log ("-" * 60) "DarkCyan"
}

# ==========================================
#  GPU / CPU
# ==========================================
$Nsmi = "C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
if (-not (Test-Path $Nsmi)) { $Nsmi = "nvidia-smi" }

function GpuSnap {
    try {
        $raw  = & $Nsmi --query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu `
                    --format=csv,noheader,nounits 2>$null
        $p    = ($raw -split ",\s*")
        $snap = @{ U = [int]$p[0]; T = [int]$p[1]; G = [int]$p[2]; C = [int]$p[3] }
        if ($snap.C -ge $GPU_TEMP_WARN) { Log "  [!!! ALERTE TEMP GPU !!!] $($snap.C)C >= ${GPU_TEMP_WARN}C" "Red" }
        return $snap
    } catch { return @{ U = -1; T = -1; G = -1; C = -1 } }
}

function CpuSnap {
    try {
        $c = (Get-Counter "\Processor(_Total)\% Processor Time" -SampleInterval 1 -MaxSamples 1 -ErrorAction Stop)
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

function Get-ModelInfo {
    param([string]$ModelName)
    try {
        $info = Invoke-RestMethod -Uri "http://localhost:11434/api/show" -Method Post `
            -Body (@{ name = $ModelName } | ConvertTo-Json) -ContentType "application/json" -TimeoutSec 30
        return "family=$($info.details.family) size=$($info.details.parameter_size) quant=$($info.details.quantization_level)"
    } catch { return "info unavailable" }
}

function Test-ModelExists {
    param([string]$Name)
    try {
        $list = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get -TimeoutSec 10
        return ($list.models | Where-Object { $_.name -eq $Name }) -ne $null
    } catch { return $false }
}

function Restart-Ollama {
    Log "  [RESTART] Redemarrage Ollama..." "Yellow"
    taskkill /F /IM ollama.exe /T 2>$null | Out-Null
    taskkill /F /IM ollama_llm_server.exe /T 2>$null | Out-Null
    taskkill /F /IM ollama_app.exe /T 2>$null | Out-Null
    Start-Sleep -Seconds 8
    $env:OLLAMA_MODELS = "D:\Continue\Ollama\models"
    Start-Process -FilePath "ollama" -ArgumentList "serve" -NoNewWindow
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 2
        $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 11434 -WarningAction SilentlyContinue
        if ($tcp.TcpTestSucceeded) { Log "  [RESTART] Ollama OK ($($i*2+2)s)" "Green"; Start-Sleep 5; return }
    }
    Log "  [RESTART] Echec apres 60s" "Red"
}

function Unload-Model {
    param([string]$ModelName)
    try {
        Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
            -Body (@{ model = $ModelName; prompt = ""; keep_alive = 0 } | ConvertTo-Json) `
            -ContentType "application/json" -TimeoutSec 30 | Out-Null
        Log "  [UNLOAD] $ModelName flushed" "DarkGray"
    } catch { Log "  [UNLOAD] soft unload failed" "DarkGray" }
}

function Save-Response {
    param([string]$Model, [string]$Prompt, [int]$Run, [string]$Content)
    $safe  = $Model -replace "[:\\\/]", "_"
    $fpath = "$ResponseDir\${safe}__${Prompt}__run${Run}.txt"
    $hdr   = "MODEL: $Model | PROMPT: $Prompt | RUN: $Run | $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Set-Content -Path $fpath -Value ("=" * 80 + "`n" + $hdr + "`n" + "=" * 80 + "`n`n" + $Content) -Encoding UTF8
}

# ==========================================
#  MODELES
# ==========================================
$ModelsTierGPU = @(
    "qwen2.5-coder:3b",
    "gemma4:e2b",
    "qwen3:4b",
    "phi4-mini-reasoning:latest",
    "gemma3:4b",
    "gemma4:e4b"
)
$ModelsTierCPU = @(
    "deepseek-r1:8b",
    "qwen3:8b",
    "qwen3:14b",
    "deepseek-r1:14b",
    "qwen3-coder:30b-a3b-q4_K_M",
    "qwen3:30b-a3b"
)

# --- Filtrage selon le mode choisi ---
$AllModels = switch ($Mode) {
    "GPU"     { $ModelsTierGPU }
    "CPU"     { $ModelsTierCPU }
    "Hybride" { $ModelsTierGPU + $ModelsTierCPU }
}
$ModelTotal = $AllModels.Count

# ==========================================
#  MULTIPLICATEURS num_predict PAR FAMILLE
#  Corrige les empty_response et truncations observees en V4
# ==========================================
$TokenMultipliers = @{
    "gemma4"   = 4   # Thinking block natif : consomme tout le budget avant la reponse
    "phi3"     = 3   # phi4-mini-reasoning : grand reasoning avant reponse
    "qwen3"    = 3   # Models reasoning qwen3 : long chain of thought
    "gemma3"   = 2   # Truncation observee sur code_simple a 512 tokens
    "default"  = 1
}

# ==========================================
#  PROMPTS
# ==========================================
$Prompts = [ordered]@{
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

$PromptKeys  = @($Prompts.Keys)
$PromptTotal = $PromptKeys.Count
$RunTotal    = 3

$script:ModelesTotal = $ModelTotal
$script:RunsTotal    = $ModelTotal * $PromptTotal * $RunTotal

# ==========================================
#  REPRISE GRANULAIRE (niveau run individuel)
# ==========================================
$Results   = [System.Collections.Generic.List[object]]::new()
# Fichier de progression specifique au mode pour eviter les collisions
$ProgressF = "$ResultsDir\overnight_v7_progress_${Mode}.json"
$Done      = @{}

function Save-Progress {
    $Done | ConvertTo-Json -Depth 3 | Out-File $ProgressF -Encoding UTF8 -Force
}

function Get-RunKey {
    param([string]$Model, [string]$Prompt, [int]$Run)
    $safe = $Model -replace "[:\\\/\s]", "_"
    return "run_${safe}__${Prompt}__${Run}"
}

function Is-RunDone {
    param([string]$Model, [string]$Prompt, [int]$Run)
    return $Done[(Get-RunKey -Model $Model -Prompt $Prompt -Run $Run)] -eq "ok"
}

function Mark-RunDone {
    param([string]$Model, [string]$Prompt, [int]$Run, [string]$Status = "ok")
    $Done[(Get-RunKey -Model $Model -Prompt $Prompt -Run $Run)] = $Status
    Save-Progress
}

# Chargement de la progression existante
$isResuming = $false
if (Test-Path $ProgressF) {
    try {
        $saved = Get-Content $ProgressF -Raw | ConvertFrom-Json
        foreach ($e in $saved.PSObject.Properties) { $Done[$e.Name] = $e.Value }
        $isResuming = $Done.Keys.Count -gt 0
        $script:IsResume = $isResuming
    } catch { $Done = @{} }
}

# Recharger les resultats partiels depuis CSV incremental si reprise
$csvInc = "$ResultsDir\bench_gpu_incremental_${Mode}.csv"
if ($isResuming -and (Test-Path $csvInc)) {
    try {
        $loaded = Import-Csv $csvInc -Encoding UTF8
        foreach ($row in $loaded) { $Results.Add($row) }
        Log "=== REPRISE : $($Results.Count) runs recharges depuis CSV incremental ===" "Yellow"
    } catch {
        Log "  [WARN] Impossible de recharger le CSV incremental : $_" "Yellow"
    }
}

# Recalcul RunsDone / ModelesDone depuis la progression
$script:RunsDone    = ($Done.Keys | Where-Object { $_ -like "run_*" -and $Done[$_] -eq "ok" }).Count
$script:ModelesDone = ($Done.Keys | Where-Object { $_ -like "done_*" -and $Done[$_] -in @("ok","skip","skip_warmup","skip_oom") }).Count
foreach ($k in ($Done.Keys | Where-Object { $_ -like "done_*" -and $Done[$_] -eq "ok" })) {
    $script:ModelesOk.Add($k -replace "^done_", "")
}

# ==========================================
#  HEADER
# ==========================================
$resumeLabel = if ($isResuming) { " [REPRISE depuis $($script:RunsDone) runs]" } else { "" }
$hdr = @"

##############################################################
##   BENCHMARK OLLAMA V7  --  $(Get-Date -Format 'yyyy-MM-dd HH:mm')$resumeLabel
##   MODE : $Mode
##   GPU : Quadro M2000M | VRAM : 4 GB
##   GPU models : $($ModelsTierGPU.Count)    CPU models : $($ModelsTierCPU.Count)
##   Modeles actifs dans ce mode : $($AllModels.Count)
##   Prompts    : $($PromptKeys -join ', ')
##   Runs/prompt: $RunTotal    Total runs : $($ModelTotal * $PromptTotal * $RunTotal)
##   Timeouts   : adaptatifs (voir TimeoutTable dans le script)
##   Garde-fous : RAM_FREE_MIN=$RAM_FREE_MIN_MB MB | OLLAMA_RAM_MAX=$OLLAMA_RAM_MAX_MB MB
##   Results    : $ResultsDir
##############################################################

"@
Write-Host $hdr -ForegroundColor DarkCyan
Add-Content $LogFile $hdr -Encoding UTF8

# Init metriques RAM
$script:LastRAMFree   = Get-FreeRAM_MB
$script:LastOllamaRAM = Get-OllamaRAM_MB
$gpuInit = GpuSnap
Log "  GPU init  : $($gpuInit.U)/$($gpuInit.T) MB VRAM | $($gpuInit.G)% | $($gpuInit.C)C" "White"
Log "  RAM libre : $($script:LastRAMFree) MB | Ollama : $($script:LastOllamaRAM) MB" "White"
Log "  Mode      : $Mode ($($AllModels.Count) modeles)" "White"
Update-Dashboard -CurrentModel "demarrage..." -CurrentPrompt "-" -CurrentRun 0 -RunTotal $RunTotal -Phase "INIT"

# ==========================================
#  BOUCLE PRINCIPALE
# ==========================================
$modelIdx = 0

foreach ($model in $AllModels) {
    $modelIdx++

    # Modele entierement termine
    if ($Done["done_$model"] -in @("ok","skip","skip_warmup","skip_oom")) {
        $statusLabel = $Done["done_$model"]
        Log "[SKIP resume] [$modelIdx/$ModelTotal] $model ($statusLabel)" "DarkGray"
        if ($statusLabel -eq "ok" -and -not ($script:ModelesOk -contains $model)) {
            $script:ModelesDone++; $script:ModelesOk.Add($model)
        } elseif ($statusLabel -ne "ok") {
            $script:ModelesDone++
            if (-not ($script:ModelesSkip -contains $model)) { $script:ModelesSkip.Add($model) }
        }
        continue
    }

    # --- Garde-fou RAM systeme avant chargement ---
    $script:LastRAMFree   = Get-FreeRAM_MB
    $script:LastOllamaRAM = Get-OllamaRAM_MB
    Update-Dashboard -CurrentModel $model -CurrentPrompt "init" -CurrentRun 0 -RunTotal $RunTotal -Phase "VERIF RAM"
    Log "" ""
    Log ("=" * 72) "Magenta"
    Log ("  [$modelIdx/$ModelTotal] $model  | RAM libre : $($script:LastRAMFree) MB | Ollama : $($script:LastOllamaRAM) MB") "Magenta"
    Log ("=" * 72) "Magenta"

    if ($script:LastRAMFree -lt $RAM_FREE_MIN_MB) {
        Log "  [SKIP OOM-RISK] RAM libre $($script:LastRAMFree) MB < seuil $RAM_FREE_MIN_MB MB -> skip $model" "Red"
        LogError -Model $model -Prompt "N/A" -Run 0 `
            -ErrorMessage "RAM libre $($script:LastRAMFree) MB < seuil $RAM_FREE_MIN_MB MB" `
            -Category "oom_or_crash"
        $Done["done_$model"] = "skip_oom"
        $script:ModelesDone++; $script:ModelesSkip.Add($model)
        Save-Progress
        continue
    }

    if (-not (Test-ModelExists $model)) {
        Log "  [SKIP] $model : non disponible localement" "Red"
        LogError -Model $model -Prompt "N/A" -Run 0 -ErrorMessage "Model not found" -Category "model_missing"
        $Done["done_$model"] = "skip"
        $script:ModelesDone++; $script:ModelesSkip.Add($model)
        Save-Progress
        continue
    }

    $isCPU       = $ModelsTierCPU -contains $model
    $tier        = if ($isCPU) { "CPU" } else { "GPU" }
    $isReasoning = $model -match "^qwen3:|deepseek-r1|reasoning"
    $temperature = if ($isReasoning) { 0.6 } else { 0 }

    # Calcul multiplicateur num_predict selon la famille
    $family = "default"
    if ($model -match "gemma4")  { $family = "gemma4" }
    elseif ($model -match "phi[34]") { $family = "phi3" }
    elseif ($model -match "qwen3")   { $family = "qwen3" }
    elseif ($model -match "gemma3")  { $family = "gemma3" }
    $tokMult = $TokenMultipliers[$family]

    $runsAlreadyDone = ($Done.Keys | Where-Object {
        $_ -like "run_$($model -replace '[:\\\/\s]','_')__*" -and $Done[$_] -eq "ok"
    }).Count
    $isPartialResume = $runsAlreadyDone -gt 0

    if ($isPartialResume) {
        Log ("  [REPRISE PARTIELLE] $runsAlreadyDone/$($PromptTotal * $RunTotal) runs deja faits") "Yellow"
    }
    Log ("  tier=$tier | reasoning=$isReasoning | temp=$temperature | tokMult=${tokMult}x") "DarkGray"

    # Unload precedent
    Update-Dashboard -CurrentModel $model -CurrentPrompt "-" -CurrentRun 0 -RunTotal $RunTotal -Phase "UNLOAD PRECEDENT"
    Unload-Model -ModelName $model
    Start-Sleep -Seconds 3

    # Warmup
    Update-Dashboard -CurrentModel $model -CurrentPrompt "-" -CurrentRun 0 -RunTotal $RunTotal -Phase "WARMUP"
    Log "  [WARMUP] Chargement $model ..." "DarkYellow"
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
            Log "  [WARMUP] OK en $([math]::Round($swW.Elapsed.TotalMilliseconds,0)) ms" "Green"
            $warmupOk = $true; break
        } catch {
            $wErr = "$_"
            Log "  [WARMUP] Tentative $w echouee : $wErr" "Yellow"
            LogError -Model $model -Prompt "warmup" -Run $w -ErrorMessage $wErr -Category "warmup_fail"
            if ($w -eq 1) { Start-Sleep -Seconds (5 * $w); Restart-Ollama }
        }
    }
    if (-not $warmupOk) {
        Log "  [SKIP] $model warmup echoue x2" "Red"
        $Done["done_$model"] = "skip_warmup"
        $script:ModelesDone++; $script:ModelesSkip.Add($model)
        Save-Progress
        continue
    }

    # --- Garde-fou RAM Ollama apres warmup ---
    $script:LastOllamaRAM = Get-OllamaRAM_MB
    $script:LastRAMFree   = Get-FreeRAM_MB
    Log "  [RAM apres warmup] Ollama=$($script:LastOllamaRAM) MB | Systeme libre=$($script:LastRAMFree) MB" "DarkGray"
    if ($script:LastOllamaRAM -gt $OLLAMA_RAM_MAX_MB) {
        Log "  [SKIP OOM-RISK] Ollama RAM $($script:LastOllamaRAM) MB > max $OLLAMA_RAM_MAX_MB MB -> skip $model" "Red"
        LogError -Model $model -Prompt "N/A" -Run 0 `
            -ErrorMessage "Ollama RAM $($script:LastOllamaRAM) MB apres warmup > seuil $OLLAMA_RAM_MAX_MB MB" `
            -Category "oom_or_crash"
        Unload-Model -ModelName $model
        Start-Sleep -Seconds 5
        $Done["done_$model"] = "skip_oom"
        $script:ModelesDone++; $script:ModelesSkip.Add($model)
        Save-Progress
        continue
    }

    Log "  [INFO] $(Get-ModelInfo $model)" "Gray"
    $gpuL = GpuSnap
    Log "  [GPU apres load] $($gpuL.U)/$($gpuL.T) MB | $($gpuL.G)% | $($gpuL.C)C" "Gray"
    Start-Sleep -Seconds 3

    $ModelRuns = [System.Collections.Generic.List[object]]::new()
    $promptIdx = 0

    foreach ($promptKey in $PromptKeys) {
        $promptIdx++
        Log "" ""
        Log "  --- [$promptIdx/$PromptTotal] PROMPT : $promptKey ---" "White"

        $basePredict = $Prompts[$promptKey].tokens
        # Appliquer multiplicateur de famille + x2 pour reasoning
        $numPredict  = $basePredict * $tokMult
        if ($isReasoning) { $numPredict = $numPredict * 2 }
        Log "    base=$basePredict x tokMult=$tokMult x reasoning=$(if($isReasoning){'x2'}else{'x1'}) = num_predict=$numPredict" "DarkGray"

        # Calcul timeout adaptatif pour ce modele+prompt
        $timeoutSec = Get-AdaptiveTimeout -ModelName $model -PromptKey $promptKey -IsCPU $isCPU
        Log "    timeout adaptatif : ${timeoutSec}s (famille=$family | prompt=$promptKey | tier=$tier)" "DarkGray"

        for ($run = 1; $run -le $RunTotal; $run++) {

            # Reprise granulaire
            if (Is-RunDone -Model $model -Prompt $promptKey -Run $run) {
                Log "    [SKIP run] $model | $promptKey | run $run (deja fait)" "DarkGray"
                $script:RunsDone++
                Update-Dashboard -CurrentModel $model -CurrentPrompt $promptKey `
                    -CurrentRun $run -RunTotal $RunTotal -Phase "SKIP (deja fait)" -CurrentTimeoutSec $timeoutSec
                continue
            }

            Update-Dashboard -CurrentModel $model -CurrentPrompt $promptKey `
                -CurrentRun $run -RunTotal $RunTotal -Phase "INFERENCE" -CurrentTimeoutSec $timeoutSec

            Log "    [RUN $run/$RunTotal] $model | $promptKey | predict=$numPredict | timeout=${timeoutSec}s" "Yellow"

            $gpu1 = GpuSnap
            $cpu1 = if ($isCPU) { CpuSnap } else { -1 }
            $ram1 = Get-OllamaRAM_MB
            Log "      GPU=$($gpu1.U)/$($gpu1.T)MB | $($gpu1.G)% | $($gpu1.C)C | CPU=$cpu1% | OllamaRAM=${ram1}MB" "DarkGray"

            $opts = @{
                num_predict = $numPredict; temperature = $temperature
                seed = 42; num_gpu = if ($isCPU) { 0 } else { -1 }
            }

            $sw     = [System.Diagnostics.Stopwatch]::StartNew()
            $resp   = $null
            $errMsg = $null

            for ($attempt = 1; $attempt -le 2; $attempt++) {
                try {
                    $reqBody = @{
                        model = $model; prompt = $Prompts[$promptKey].text
                        stream = $false; options = $opts
                    } | ConvertTo-Json -Depth 5
                    $resp = Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
                        -Body $reqBody -ContentType "application/json" -TimeoutSec $timeoutSec
                    $errMsg = $null; break
                } catch {
                    $errMsg = "$_"
                    Log "      [ERR attempt $attempt] $errMsg" "Red"
                    if ($attempt -lt 2) {
                        $backoff = 10 * $attempt
                        Log "      [RETRY] Attente ${backoff}s..." "Yellow"
                        Update-Dashboard -CurrentModel $model -CurrentPrompt $promptKey `
                            -CurrentRun $run -RunTotal $RunTotal -Phase "RETRY backoff ${backoff}s" -CurrentTimeoutSec $timeoutSec
                        Start-Sleep -Seconds $backoff
                        if ($errMsg -match "500|terminated|oom") { Restart-Ollama }
                    }
                }
            }
            $sw.Stop()

            $ram2    = Get-OllamaRAM_MB
            $gpu2    = GpuSnap
            $cpu2    = if ($isCPU) { CpuSnap } else { -1 }
            $totalMs = [math]::Round($sw.Elapsed.TotalMilliseconds, 1)
            $script:LastRunMs    = $totalMs
            $script:LastOllamaRAM = $ram2
            $script:RunsDone++

            if ($resp) {
                $tok      = Calc-TokPerSec $resp
                $tokOut   = if ($resp.eval_count)           { $resp.eval_count }                                   else { 0 }
                $loadMs   = if ($resp.load_duration)        { [math]::Round($resp.load_duration        / 1e6, 1) } else { 0 }
                $evalMs   = if ($resp.eval_duration)        { [math]::Round($resp.eval_duration        / 1e6, 1) } else { 0 }
                $promptMs = if ($resp.prompt_eval_duration) { [math]::Round($resp.prompt_eval_duration / 1e6, 1) } else { 0 }
                $ramAvg   = [int](($ram1 + $ram2) / 2)
                $doneRsn  = if ($resp.done_reason) { $resp.done_reason } else { "" }
                $rtext    = if ($resp.response)    { $resp.response }    else { "" }

                $script:LastTok = $tok

                if ($rtext.Length -eq 0) {
                    Log "      [!!!] REPONSE VIDE eval_count=$tokOut done_reason=$doneRsn" "Red"
                    LogError -Model $model -Prompt $promptKey -Run $run -ErrorMessage "Empty response" `
                        -Options $opts -DoneReason $doneRsn -ResponseLen 0 -TokensOut $tokOut -TimeoutUsed $timeoutSec
                } elseif ($doneRsn -eq "length") {
                    Log "      [TRUNC] Tronquee -> suggere num_predict $numPredict -> $($numPredict*2) en V8" "Yellow"
                    LogError -Model $model -Prompt $promptKey -Run $run `
                        -ErrorMessage "Truncated (done_reason=length)" -Options $opts `
                        -DoneReason $doneRsn -ResponseLen $rtext.Length -TokensOut $tokOut `
                        -Category "truncated_response" -TimeoutUsed $timeoutSec
                } elseif ($rtext.Length -lt 50) {
                    Log "      [WARN] Reponse courte ($($rtext.Length) chars)" "Yellow"
                }
                if ($rtext.Length -gt 0) { Save-Response -Model $model -Prompt $promptKey -Run $run -Content $rtext }

                $color = if ($tok -ge 20) { "Green" } elseif ($tok -ge 8) { "Yellow" } else { "DarkYellow" }
                Log ("      [OK] {0} tok/s | {1}ms | load {2}ms | eval {3}ms | {4} tok | RAM {5}MB | GPU {6}MB | len={7} | {8}" -f `
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
                $Results.Add($row); $ModelRuns.Add($row)
                Mark-RunDone -Model $model -Prompt $promptKey -Run $run -Status "ok"

            } else {
                $script:LastTok = 0
                LogError -Model $model -Prompt $promptKey -Run $run `
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
                $Results.Add($row); $ModelRuns.Add($row)
                Mark-RunDone -Model $model -Prompt $promptKey -Run $run -Status "error"
            }

            # Export CSV incremental apres chaque run (protection anti-crash)
            $Results | Export-Csv $csvInc -NoTypeInformation -Encoding UTF8 -Force

            Update-Dashboard -CurrentModel $model -CurrentPrompt $promptKey `
                -CurrentRun $run -RunTotal $RunTotal -Phase "RUN $run TERMINE" -CurrentTimeoutSec $timeoutSec

            Start-Sleep -Seconds 4
        }
    }

    # Marquer modele done si tous ses runs sont OK
    $allRunsOk = $true
    foreach ($pk in $PromptKeys) {
        for ($r = 1; $r -le $RunTotal; $r++) {
            if (-not (Is-RunDone -Model $model -Prompt $pk -Run $r)) { $allRunsOk = $false; break }
        }
        if (-not $allRunsOk) { break }
    }

    if ($allRunsOk) {
        $Done["done_$model"] = "ok"
        Save-Progress
        $script:ModelesDone++
        $script:ModelesOk.Add($model)
        Log "  [DONE] $model : tous les runs OK" "Green"
    } else {
        Log "  [PARTIAL] $model : reprise possible au prochain lancement" "Yellow"
    }

    Show-ModelSummary -Model $model -Tier $tier -ModelResults $ModelRuns
    Update-Dashboard -CurrentModel $model -CurrentPrompt "-" -CurrentRun 0 -RunTotal $RunTotal -Phase "UNLOAD + PAUSE"

    Unload-Model -ModelName $model
    Start-Sleep -Seconds 8
}

# ==========================================
#  EXPORT FINAL
# ==========================================
$allDone = ($Done.Keys | Where-Object { $_ -like "done_*" -and $Done[$_] -in @("ok","skip","skip_warmup","skip_oom") }).Count -eq $ModelTotal
if ($allDone) {
    Remove-Item $ProgressF -Force -ErrorAction SilentlyContinue
    Log "  [PROGRESS] Benchmark complet - fichier de progression supprime" "Green"
} else {
    Log "  [PROGRESS] Conserve pour reprise : $ProgressF" "Yellow"
}

$csvFinal = "$ResultsDir\bench_gpu_FINAL_V7_${Mode}_$(Get-Date -Format 'yyyyMMdd_HHmmss').csv"
$Results | Export-Csv $csvFinal -NoTypeInformation -Encoding UTF8

$elapsed    = ([DateTime]::Now - $script:BenchStart)
$elapsedStr = "$([int]$elapsed.TotalHours)h $($elapsed.Minutes.ToString('00'))m $($elapsed.Seconds.ToString('00'))s"

Update-Dashboard -CurrentModel "TERMINE" -CurrentPrompt "-" -CurrentRun 0 -RunTotal $RunTotal -Phase "FIN"

Log "" ""
Log ("=" * 72) "Cyan"
Log "  FIN BENCHMARK V7 [$Mode]  $(Get-Date -Format 'yyyy-MM-dd HH:mm')  (duree : $elapsedStr)" "Cyan"
Log "  CSV final   : $csvFinal" "Green"
Log "  Erreurs LLM : $ErrLogFile ($($LLMErrors.Count) entrees)" $(if ($LLMErrors.Count -gt 0) { "Yellow" } else { "Green" })
Log "  Reponses    : $ResponseDir" "Green"
Log ("=" * 72) "Cyan"
Log "" ""

# ==========================================
#  CLASSEMENT FINAL
# ==========================================
Log "=== CLASSEMENT FINAL [$Mode] ===" "Cyan"
$Results | Where-Object { $_.tok_s -gt 0 } | Group-Object model | ForEach-Object {
    $grp = $_.Group
    [PSCustomObject]@{
        Modele  = $_.Name
        Tier    = ($grp | Select-Object -First 1).tier
        Mode    = $Mode
        TokS    = [math]::Round(($grp | Measure-Object tok_s        -Average).Average, 1)
        VRAM_MB = [math]::Round(($grp | Measure-Object vram_after   -Average).Average, 0)
        GPU_pct = [math]::Round(($grp | Measure-Object gpu_util_pct -Average).Average, 0)
        CPU_pct = if (($grp | Select-Object -First 1).cpu_util_pct -eq -1) { "N/A" } `
                  else { [math]::Round(($grp | Where-Object { $_.cpu_util_pct -ge 0 } | Measure-Object cpu_util_pct -Average).Average, 0) }
        RAM_MB  = [math]::Round(($grp | Measure-Object ram_avg_mb   -Average).Average, 0)
        RespAvg = [math]::Round(($grp | Measure-Object response_len -Average).Average, 0)
        Vides   = ($grp | Where-Object { $_.response_len -eq 0 }).Count
        Tronc   = ($grp | Where-Object { $_.done_reason  -eq "length" }).Count
        Runs    = $grp.Count
    }
} | Sort-Object TokS -Descending | Format-Table -AutoSize

Log "" ""
Log "=== DIAGNOSTICS ERREURS LLM ===" "Yellow"
if ($LLMErrors.Count -eq 0) {
    Log "  Aucune erreur enregistree." "Green"
} else {
    Log "  $($LLMErrors.Count) erreur(s) -> $ErrLogFile" "Yellow"
    $LLMErrors | Group-Object category | Sort-Object Count -Descending | ForEach-Object {
        Log "  [$($_.Count)x] $($_.Name)" "Yellow"
        $_.Group | Select-Object -First 1 | ForEach-Object { Log "       Fix : $($_.suggestion)" "DarkYellow" }
    }
}

Log "" ""
Log "=== REPONSES VIDES ===" "Yellow"
$empty = $Results | Where-Object { $_.response_len -eq 0 -and $_.error -eq "" }
if ($empty.Count -eq 0) { Log "  Aucune." "Green" }
else { $empty | Select-Object model, prompt, run, tok_s, done_reason, tokens_out, num_predict_used | Format-Table -AutoSize }

Log "" ""
Log "=== REPONSES TRONQUEES ===" "Yellow"
$trunc = $Results | Where-Object { $_.done_reason -eq "length" }
if ($trunc.Count -eq 0) { Log "  Aucune." "Green" }
else {
    $trunc | Select-Object model, prompt, run, tokens_out, response_len, num_predict_used, tok_multiplier, timeout_sec | Format-Table -AutoSize
    Log "  -> Augmenter tok_multiplier pour ces modeles/prompts en V8" "DarkYellow"
}
