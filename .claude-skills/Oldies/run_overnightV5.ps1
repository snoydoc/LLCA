# run_overnightV5.ps1
# Benchmark GPU/CPU hybride - Quadro M2000M (4GB VRAM CUDA)
# Lancer via prepare_and_launch.ps1 -- ne pas lancer directement
# ASCII pur - pas d accents dans ce fichier
#
# V5 (2026-04-27) :
#   [FIX]  ForegroundColor vide -> fallback "White" dans Log()
#   [UX]   Dashboard ASCII inline (10 lignes) qui s'ecrase a chaque run
#          Affiche : modele courant, prompt, run, barre globale ASCII,
#          modeles termines/restants, tok/s dernier run, ETA recalcule live
#   [UX]   Header enrichi avec totaux
#   [UX]   Recap par modele apres chaque modele
#   [LOG]  llm_errors.json : journal structure des erreurs LLM
#          (message, options, done_reason, suggestion de fix)
#   [LOG]  Reponses tronquees detectees (done_reason=length) -> warning
#   [ALERTE] Seuil temperature GPU configurable
#   [RETRY]  Retry intelligent : backoff x2 sur erreur 500/terminated
#   [DIAG]   Section diagnostics amelioree en fin de script

$ErrorActionPreference = "Continue"
$ResultsDir  = "$PSScriptRoot\CPUVsGPU\results"
$ResponseDir = "$ResultsDir\responses"
$LogFile     = "$ResultsDir\bench_gpu_$(Get-Date -Format 'yyyyMMdd_HHmm').log"
$ErrLogFile  = "$ResultsDir\llm_errors_$(Get-Date -Format 'yyyyMMdd_HHmm').json"

New-Item -ItemType Directory -Force -Path $ResultsDir  | Out-Null
New-Item -ItemType Directory -Force -Path $ResponseDir | Out-Null

$GPU_TEMP_WARN = 85
$LLMErrors     = [System.Collections.Generic.List[object]]::new()

# ==========================================
#  DASHBOARD INLINE
#  Le bloc de 10 lignes s'ecrase sur lui-meme a chaque appel.
#  Les logs normaux s'affichent APRES ce bloc (curseur repositionne).
# ==========================================
$script:DashRow      = -1   # ligne Y du debut du dashboard (-1 = pas encore affiche)
$script:DashHeight   = 11   # nombre de lignes du bloc dashboard
$script:BenchStart   = [DateTime]::Now
$script:LastTok      = 0.0
$script:LastRunMs    = 0
$script:RunsDone     = 0
$script:RunsTotal    = 0
$script:ModelesDone  = 0
$script:ModelesTotal = 0
$script:ModelesOk    = [System.Collections.Generic.List[string]]::new()
$script:ModelesSkip  = [System.Collections.Generic.List[string]]::new()

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

function Update-Dashboard {
    param(
        [string]$CurrentModel  = "",
        [string]$CurrentPrompt = "",
        [int]$CurrentRun       = 0,
        [int]$RunTotal         = 3,
        [string]$Phase         = ""   # ex: "WARMUP", "INFERENCE", "UNLOAD"...
    )

    # --- Calcul ETA ---
    $elapsed  = ([DateTime]::Now - $script:BenchStart).TotalSeconds
    $doneFrac = if ($script:RunsTotal -gt 0) { $script:RunsDone / $script:RunsTotal } else { 0 }
    $etaSec   = if ($doneFrac -gt 0.02) { [int]($elapsed / $doneFrac * (1 - $doneFrac)) } else { 0 }

    # --- Barre globale ---
    $pctGlobal = [int]($doneFrac * 100)
    $bar       = Draw-Bar -Pct $pctGlobal -Width 34

    # --- Modeles restants ---
    $mDone = $script:ModelesDone
    $mTot  = $script:ModelesTotal
    $mLeft = $mTot - $mDone

    # --- Ligne modeles termines (max 5 afffiches) ---
    $okList   = if ($script:ModelesOk.Count -gt 0) {
        ($script:ModelesOk | Select-Object -Last 4) -join ", "
    } else { "(aucun)" }
    $skipList = if ($script:ModelesSkip.Count -gt 0) {
        ($script:ModelesSkip | Select-Object -Last 3) -join ", "
    } else { "-" }

    # --- Tok/s couleur (ANSI) ---
    $tokStr = if ($script:LastTok -ge 20) { "$($script:LastTok) tok/s" } `
              elseif ($script:LastTok -gt 0) { "$($script:LastTok) tok/s" } `
              else { "---" }

    # --- Phase en cours ---
    $phaseStr = if ($Phase) { "  >> $Phase" } else { "" }

    # --- Construire les lignes du dashboard ---
    $W = 70   # largeur totale
    $sep = "=" * $W

    $lines = @(
        $sep,
        ("  BENCHMARK V5 | Elapsed: {0,-12} | ETA: {1,-14}" -f (Format-Elapsed), (Format-ETA $etaSec)),
        ("  Progression globale : {0}" -f $bar),
        ("  Modeles  : {0}/{1} termines | {2} restants | {3} skips" -f $mDone, $mTot, $mLeft, $script:ModelesSkip.Count),
        ("  Dernier OK : {0}" -f $okList),
        $sep,
        ("  Modele courant : [{0}/{1}] {2}" -f $mDone+1, $mTot, $CurrentModel),
        ("  Prompt  : {0,-20} Run : {1}/{2}{3}" -f $CurrentPrompt, $CurrentRun, $RunTotal, $phaseStr),
        ("  Runs    : {0}/{1} (session)   Dernier run : {2,-14} {3}" -f $script:RunsDone, $script:RunsTotal, "${script:LastRunMs}ms", $tokStr),
        $sep,
        ""
    )

    # --- Premiere fois : memoriser la ligne du dashboard et l'afficher ---
    if ($script:DashRow -lt 0) {
        $script:DashRow = [Console]::CursorTop
    }

    # --- Sauvegarder position courante, aller au debut du bloc, ecraser ---
    $savedTop  = [Console]::CursorTop
    $savedLeft = [Console]::CursorLeft

    [Console]::SetCursorPosition(0, $script:DashRow)
    foreach ($l in $lines) {
        # Pad a la largeur pour effacer les restes de la ligne precedente
        $padded = $l.PadRight($W)
        Write-Host $padded -ForegroundColor Cyan
    }

    # --- Repositionner le curseur APRES le bloc pour les logs normaux ---
    # Si des logs ont fait defiler le terminal, on recalcule
    $logRow = [Math]::Max($savedTop, $script:DashRow + $script:DashHeight)
    [Console]::SetCursorPosition(0, $logRow)
}

# ==========================================
#  LOG (ecrit APRES le dashboard)
# ==========================================
function Log {
    param([string]$M, [string]$C = "White")
    $validColors = [System.Enum]::GetNames([System.ConsoleColor])
    if ([string]::IsNullOrWhiteSpace($C) -or ($C -notin $validColors)) { $C = "White" }
    $L = "[$(Get-Date -Format 'HH:mm:ss')] $M"
    # S'assurer qu'on ecrit apres le bloc dashboard
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
        [string]$Model,
        [string]$Prompt,
        [int]$Run,
        [string]$ErrorMessage,
        [hashtable]$Options = @{},
        [string]$DoneReason = "",
        [int]$ResponseLen = 0,
        [int]$TokensOut = 0,
        [string]$Category = "unknown"
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
        "server_error_500"   { "Restart Ollama. Reduce num_predict. Check VRAM. Try num_gpu=0." }
        "timeout"            { "Increase TimeoutSec. Reduce num_predict. Use smaller quant." }
        "oom_or_crash"       { "Reduce num_gpu layers or use num_gpu=0. Close other GPU apps." }
        "empty_response"     { "Increase num_predict. Try temperature=0.7. Check model (ollama pull)." }
        "truncated_response" { "Double num_predict. Response cut short by token limit." }
        default              { "Review error message and adjust options." }
    }
    $entry = [PSCustomObject]@{
        timestamp    = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        model        = $Model; prompt       = $Prompt; run          = $Run
        category     = $Category; error_msg = $ErrorMessage
        done_reason  = $DoneReason; response_len = $ResponseLen; tokens_out = $TokensOut
        options_used = $Options; suggestion = $suggestion
    }
    $LLMErrors.Add($entry)
    $LLMErrors | ConvertTo-Json -Depth 6 | Out-File $ErrLogFile -Encoding UTF8 -Force
    Log "    [ERR-LOG] $Category -> $suggestion" "DarkYellow"
}

# ==========================================
#  RECAP PAR MODELE
# ==========================================
function Show-ModelSummary {
    param([string]$Model, [string]$Tier, $ModelResults)
    if (-not $ModelResults -or $ModelResults.Count -eq 0) { return }
    $ok    = @($ModelResults | Where-Object { $_.response_len -gt 0 })
    $empty = @($ModelResults | Where-Object { $_.response_len -eq 0 })
    $trunc = @($ModelResults | Where-Object { $_.done_reason -eq "length" })
    $avgTok = if ($ok.Count -gt 0) { [math]::Round(($ok | Measure-Object tok_s -Average).Average, 2) } else { 0 }
    $bar = "-" * 60
    Log $bar "DarkCyan"
    Log ("  RECAP [{0}] {1}" -f $Tier, $Model) "Cyan"
    Log ("  Runs OK : {0}/{1}   Vides : {2}   Tronquees : {3}" -f $ok.Count, $ModelResults.Count, $empty.Count, $trunc.Count) $(if ($empty.Count -gt 0) { "Red" } else { "White" })
    Log ("  Moy tok/s : {0}" -f $avgTok) $(if ($avgTok -ge 20) { "Green" } elseif ($avgTok -ge 8) { "Yellow" } else { "Red" })
    Log $bar "DarkCyan"
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
        if ($snap.C -ge $GPU_TEMP_WARN) {
            Log "  [!!! ALERTE TEMP GPU !!!] $($snap.C)C >= seuil ${GPU_TEMP_WARN}C" "Red"
        }
        return $snap
    } catch { return @{ U = -1; T = -1; G = -1; C = -1 } }
}

function CpuSnap {
    try {
        $c = (Get-Counter "\Processor(_Total)\% Processor Time" -SampleInterval 1 -MaxSamples 1 -ErrorAction Stop)
        return [math]::Round($c.CounterSamples.CookedValue, 1)
    } catch { return -1 }
}

# ==========================================
#  HELPERS
# ==========================================
function Calc-TokPerSec {
    param($resp)
    if ($resp.eval_rate -and $resp.eval_rate -gt 0)  { return [math]::Round($resp.eval_rate, 2) }
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
    Start-Sleep -Seconds 6
    $env:OLLAMA_MODELS = "D:\Continue\Ollama\models"
    Start-Process -FilePath "ollama" -ArgumentList "serve" -NoNewWindow
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 2
        $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 11434 -WarningAction SilentlyContinue
        if ($tcp.TcpTestSucceeded) { Log "  [RESTART] Ollama OK ($($i*2+2)s)" "Green"; Start-Sleep 5; return }
    }
    Log "  [RESTART] Echec apres 60s" "Red"
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
$AllModels  = $ModelsTierGPU + $ModelsTierCPU
$ModelTotal = $AllModels.Count

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

# Initialiser compteurs globaux dashboard
$script:ModelesTotal = $ModelTotal
$script:RunsTotal    = $ModelTotal * $PromptTotal * $RunTotal

$Results   = @()
$ProgressF = "$ResultsDir\overnight_v5_progress.json"

$Done = @{}
if (Test-Path $ProgressF) {
    try {
        $saved = Get-Content $ProgressF -Raw | ConvertFrom-Json
        foreach ($e in $saved.PSObject.Properties) { $Done[$e.Name] = $e.Value }
        # Recalculer RunsDone depuis les skips/ok deja faits
        $alreadyDone = ($Done.Keys | Where-Object { $Done[$_] -in @("ok","skip","skip_warmup") }).Count
        $script:ModelesDone = $alreadyDone
        $script:RunsDone    = $alreadyDone * $PromptTotal * $RunTotal
    } catch { $Done = @{} }
}

function Save-Progress { $Done | ConvertTo-Json | Out-File $ProgressF -Encoding UTF8 -Force }

# ==========================================
#  HEADER (affiche avant le dashboard)
# ==========================================
$hdr = @"

##############################################################
##   BENCHMARK OLLAMA V5  --  $(Get-Date -Format 'yyyy-MM-dd HH:mm')
##   GPU : Quadro M2000M | VRAM : 4 GB
##   GPU models : $($ModelsTierGPU.Count)    CPU models : $($ModelsTierCPU.Count)
##   Prompts    : $($PromptKeys -join ', ')
##   Runs/prompt: $RunTotal    Total runs : $($ModelTotal * $PromptTotal * $RunTotal)
##   Results    : $ResultsDir
##############################################################

"@
Write-Host $hdr -ForegroundColor DarkCyan
Add-Content $LogFile $hdr -Encoding UTF8

$gpuInit = GpuSnap
Log "  GPU init : $($gpuInit.U)/$($gpuInit.T) MB VRAM | $($gpuInit.G)% | $($gpuInit.C)C" "White"

# Premier affichage du dashboard (fixe sa position Y dans le terminal)
Update-Dashboard -CurrentModel "demarrage..." -CurrentPrompt "-" -CurrentRun 0 -RunTotal $RunTotal -Phase "INIT"

# ==========================================
#  BOUCLE PRINCIPALE
# ==========================================
$modelIdx = 0

foreach ($model in $AllModels) {
    $modelIdx++

    if ($Done["done_$model"] -eq "ok") {
        Log "[SKIP resume] [$modelIdx/$ModelTotal] $model" "DarkGray"
        $script:ModelesDone++
        $script:ModelesOk.Add($model)
        Update-Dashboard -CurrentModel $model -CurrentPrompt "-" -CurrentRun 0 -RunTotal $RunTotal -Phase "SKIP (resume)"
        continue
    }

    Update-Dashboard -CurrentModel $model -CurrentPrompt "init" -CurrentRun 0 -RunTotal $RunTotal -Phase "VERIFICATION"

    if (-not (Test-ModelExists $model)) {
        Log "  [SKIP] $model : non disponible localement" "Red"
        LogError -Model $model -Prompt "N/A" -Run 0 -ErrorMessage "Model not found" -Category "model_missing"
        $Done["done_$model"] = "skip"
        $script:ModelesDone++
        $script:ModelesSkip.Add($model)
        Save-Progress
        Update-Dashboard -CurrentModel $model -CurrentPrompt "-" -CurrentRun 0 -RunTotal $RunTotal -Phase "SKIP (absent)"
        continue
    }

    $isCPU       = $ModelsTierCPU -contains $model
    $tier        = if ($isCPU) { "CPU" } else { "GPU" }
    $isReasoning = $model -match "^qwen3:|deepseek-r1|reasoning"
    $temperature = if ($isReasoning) { 0.6 } else { 0 }
    $timeoutSec  = if ($isCPU) { 3600 } else { 600 }

    Log "" ""
    Log ("=" * 70) "Magenta"
    Log ("  [$modelIdx/$ModelTotal] $model  [$tier]  reasoning=$isReasoning  temp=$temperature") "Magenta"
    Log ("=" * 70) "Magenta"

    # Unload precedent
    Update-Dashboard -CurrentModel $model -CurrentPrompt "-" -CurrentRun 0 -RunTotal $RunTotal -Phase "UNLOAD PRECEDENT"
    try {
        Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
            -Body (@{ model = $model; prompt = ""; keep_alive = 0 } | ConvertTo-Json) `
            -ContentType "application/json" -TimeoutSec 30 | Out-Null
        Log "  [UNLOAD] keep_alive=0 sent" "DarkGray"
    } catch { Log "  [UNLOAD] soft unload failed" "DarkGray" }
    Start-Sleep -Seconds 3

    # Warmup
    Update-Dashboard -CurrentModel $model -CurrentPrompt "-" -CurrentRun 0 -RunTotal $RunTotal -Phase "WARMUP / CHARGEMENT"
    Log "  [WARMUP] Chargement $model ..." "DarkYellow"
    $warmupOk = $false
    for ($w = 1; $w -le 2; $w++) {
        try {
            $swW = [System.Diagnostics.Stopwatch]::StartNew()
            $warmupBody = @{
                model   = $model; prompt = "hi"; stream = $false
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
        $script:ModelesDone++
        $script:ModelesSkip.Add($model)
        Save-Progress
        Update-Dashboard -CurrentModel $model -CurrentPrompt "-" -CurrentRun 0 -RunTotal $RunTotal -Phase "SKIP (warmup KO)"
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
        $numPredict  = if ($isReasoning) { $basePredict * 2 } else { $basePredict }
        Log "    num_predict=$numPredict  reasoning=$isReasoning" "DarkGray"

        for ($run = 1; $run -le $RunTotal; $run++) {

            Update-Dashboard -CurrentModel $model -CurrentPrompt $promptKey `
                -CurrentRun $run -RunTotal $RunTotal -Phase "INFERENCE"

            Log "    [RUN $run/$RunTotal] $model | $promptKey" "Yellow"

            $gpu1 = GpuSnap
            $cpu1 = if ($isCPU) { CpuSnap } else { -1 }
            $ram1 = (Get-Process | Where-Object { $_.ProcessName -match "ollama" } |
                     Measure-Object PrivateMemorySize64 -Sum).Sum / 1MB
            Log "      GPU : $($gpu1.U)/$($gpu1.T)MB | $($gpu1.G)% | $($gpu1.C)C | CPU=$cpu1%" "DarkGray"

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
                            -CurrentRun $run -RunTotal $RunTotal -Phase "RETRY (backoff ${backoff}s)"
                        Start-Sleep -Seconds $backoff
                        if ($errMsg -match "500|terminated|oom") { Restart-Ollama }
                    }
                }
            }
            $sw.Stop()

            $ram2     = (Get-Process | Where-Object { $_.ProcessName -match "ollama" } |
                         Measure-Object PrivateMemorySize64 -Sum).Sum / 1MB
            $gpu2     = GpuSnap
            $cpu2     = if ($isCPU) { CpuSnap } else { -1 }
            $totalMs  = [math]::Round($sw.Elapsed.TotalMilliseconds, 1)

            # Mettre a jour les compteurs globaux pour le dashboard
            $script:RunsDone++
            $script:LastRunMs = $totalMs

            if ($resp) {
                $tok      = Calc-TokPerSec $resp
                $tokOut   = if ($resp.eval_count)           { $resp.eval_count }                                   else { 0 }
                $loadMs   = if ($resp.load_duration)        { [math]::Round($resp.load_duration        / 1e6, 1) } else { 0 }
                $evalMs   = if ($resp.eval_duration)        { [math]::Round($resp.eval_duration        / 1e6, 1) } else { 0 }
                $promptMs = if ($resp.prompt_eval_duration) { [math]::Round($resp.prompt_eval_duration / 1e6, 1) } else { 0 }
                $ramAvg   = [math]::Round(($ram1 + $ram2) / 2, 0)
                $doneRsn  = if ($resp.done_reason) { $resp.done_reason } else { "" }
                $rtext    = if ($resp.response)    { $resp.response }    else { "" }

                $script:LastTok = $tok

                if ($rtext.Length -eq 0) {
                    Log "      [!!!] REPONSE VIDE eval_count=$tokOut done_reason=$doneRsn" "Red"
                    LogError -Model $model -Prompt $promptKey -Run $run `
                        -ErrorMessage "Empty response" -Options $opts -DoneReason $doneRsn `
                        -ResponseLen 0 -TokensOut $tokOut
                } elseif ($doneRsn -eq "length") {
                    Log "      [TRUNC] Tronquee (length) -> augmenter num_predict de $numPredict a $($numPredict*2)" "Yellow"
                    LogError -Model $model -Prompt $promptKey -Run $run `
                        -ErrorMessage "Truncated (done_reason=length)" -Options $opts `
                        -DoneReason $doneRsn -ResponseLen $rtext.Length -TokensOut $tokOut `
                        -Category "truncated_response"
                } elseif ($rtext.Length -lt 50) {
                    Log "      [WARN] Reponse courte ($($rtext.Length) chars)" "Yellow"
                }
                if ($rtext.Length -gt 0) { Save-Response -Model $model -Prompt $promptKey -Run $run -Content $rtext }

                $color = if ($tok -ge 20) { "Green" } elseif ($tok -ge 8) { "Yellow" } else { "DarkYellow" }
                Log ("      [OK] {0} tok/s | {1}ms total | load {2}ms | eval {3}ms | {4} tok | RAM {5}MB | GPU {6}MB | len={7} | {8}" -f `
                    $tok, $totalMs, $loadMs, $evalMs, $tokOut, $ramAvg, $gpu2.U, $rtext.Length, $doneRsn) $color

                $row = [PSCustomObject]@{
                    model=$model; tier=$tier; prompt=$promptKey; run=$run
                    tok_s=$tok; tokens_out=$tokOut; total_ms=$totalMs
                    load_ms=$loadMs; eval_ms=$evalMs; prompt_ms=$promptMs
                    ram_avg_mb=$ramAvg; vram_before=$gpu1.U; vram_after=$gpu2.U
                    vram_delta=($gpu2.U - $gpu1.U); gpu_util_pct=$gpu2.G
                    cpu_util_pct=$cpu2; temp_c=$gpu2.C; done_reason=$doneRsn
                    response_len=$rtext.Length; error=""
                    response_snippet=if ($rtext.Length -gt 0) { $rtext.Substring(0,[Math]::Min(500,$rtext.Length)) } else { "" }
                }
                $Results += $row; $ModelRuns.Add($row)

            } else {
                $script:LastTok = 0
                LogError -Model $model -Prompt $promptKey -Run $run `
                    -ErrorMessage ($errMsg ?? "Unknown error after 2 retries") -Options $opts

                $row = [PSCustomObject]@{
                    model=$model; tier=$tier; prompt=$promptKey; run=$run
                    tok_s=0; tokens_out=0; total_ms=$totalMs
                    load_ms=0; eval_ms=0; prompt_ms=0
                    ram_avg_mb=[math]::Round(($ram1+$ram2)/2,0)
                    vram_before=$gpu1.U; vram_after=$gpu2.U; vram_delta=0
                    gpu_util_pct=$gpu2.G; cpu_util_pct=$cpu2; temp_c=$gpu2.C
                    done_reason=""; response_len=0; error=$errMsg; response_snippet=""
                }
                $Results += $row; $ModelRuns.Add($row)
            }

            # Rafraichir le dashboard apres chaque run
            Update-Dashboard -CurrentModel $model -CurrentPrompt $promptKey `
                -CurrentRun $run -RunTotal $RunTotal -Phase "RUN $run TERMINE"

            Start-Sleep -Seconds 4
        }
    }

    $Done["done_$model"] = "ok"
    $script:ModelesDone++
    $script:ModelesOk.Add($model)
    Save-Progress

    $csvInc = "$ResultsDir\bench_gpu_incremental.csv"
    $Results | Export-Csv $csvInc -NoTypeInformation -Encoding UTF8 -Force

    Show-ModelSummary -Model $model -Tier $tier -ModelResults $ModelRuns

    Update-Dashboard -CurrentModel $model -CurrentPrompt "-" -CurrentRun 0 -RunTotal $RunTotal -Phase "UNLOAD + PAUSE"
    try {
        Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
            -Body (@{ model = $model; prompt = ""; keep_alive = 0 } | ConvertTo-Json) `
            -ContentType "application/json" -TimeoutSec 30 | Out-Null
        Log "  [UNLOAD] $model flushed" "DarkGray"
    } catch { }
    Start-Sleep -Seconds 8
}

# ==========================================
#  EXPORT FINAL
# ==========================================
Remove-Item $ProgressF -Force -ErrorAction SilentlyContinue
$csvFinal = "$ResultsDir\bench_gpu_FINAL_$(Get-Date -Format 'yyyyMMdd_HHmmss').csv"
$Results | Export-Csv $csvFinal -NoTypeInformation -Encoding UTF8

$elapsed    = ([DateTime]::Now - $script:BenchStart)
$elapsedStr = "$([int]$elapsed.TotalHours)h $($elapsed.Minutes.ToString('00'))m $($elapsed.Seconds.ToString('00'))s"

# Dashboard final
Update-Dashboard -CurrentModel "TERMINE" -CurrentPrompt "-" -CurrentRun 0 -RunTotal $RunTotal -Phase "FIN"

Log "" ""
Log ("=" * 70) "Cyan"
Log "  FIN BENCHMARK  $(Get-Date -Format 'yyyy-MM-dd HH:mm')  (duree : $elapsedStr)" "Cyan"
Log "  CSV final   : $csvFinal" "Green"
Log "  Erreurs LLM : $ErrLogFile ($($LLMErrors.Count) entrees)" $(if ($LLMErrors.Count -gt 0) { "Yellow" } else { "Green" })
Log "  Reponses    : $ResponseDir" "Green"
Log ("=" * 70) "Cyan"
Log "" ""

# ==========================================
#  CLASSEMENT FINAL
# ==========================================
Log "=== CLASSEMENT FINAL ===" "Cyan"
$Results | Where-Object { $_.tok_s -gt 0 } | Group-Object model | ForEach-Object {
    $grp = $_.Group
    [PSCustomObject]@{
        Modele  = $_.Name
        Tier    = ($grp | Select-Object -First 1).tier
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

# ==========================================
#  DIAGNOSTICS ERREURS
# ==========================================
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
$emptyNoErr = $Results | Where-Object { $_.response_len -eq 0 -and $_.error -eq "" }
if ($emptyNoErr.Count -eq 0) { Log "  Aucune." "Green" }
else { $emptyNoErr | Select-Object model, prompt, run, tok_s, done_reason, tokens_out | Format-Table -AutoSize }

Log "" ""
Log "=== REPONSES TRONQUEES (done_reason=length) ===" "Yellow"
$truncated = $Results | Where-Object { $_.done_reason -eq "length" }
if ($truncated.Count -eq 0) { Log "  Aucune." "Green" }
else {
    $truncated | Select-Object model, prompt, run, tokens_out, response_len | Format-Table -AutoSize
    Log "  -> Doubler num_predict pour ces modeles/prompts en V6" "DarkYellow"
}
