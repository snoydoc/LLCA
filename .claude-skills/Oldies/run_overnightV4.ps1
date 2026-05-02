# run_overnightV4.ps1
# Benchmark GPU/CPU hybride - Quadro M2000M (4GB VRAM CUDA)
# Lancer via prepare_and_launch.ps1 -- ne pas lancer directement
# ASCII pur - pas d accents dans ce fichier
#
# V4 (2026-04-26) :
#   - num_gpu force : 0=CPU, -1=GPU auto (fix critique tiering)
#   - num_predict adaptatif par prompt x type modele (fix reponses vides)
#   - keep_alive=0 entre modeles pour vider VRAM (fix saturation 4GB)
#   - Verification modele pull avant benchmark (skip propre)
#   - PrivateMemorySize64 au lieu de WorkingSet64 (RAM reelle)
#   - CpuSnap pour modeles CPU (metrique manquante)
#   - Temperature 0.6 pour modeles reasoning (fix blocage deepseek/qwen3)
#   - Unload explicite + tuer ollama_app.exe (restart robuste)
#   - Restart-Ollama reinjecte OLLAMA_MODELS (fix store perdu apres crash)
#   - TimeoutSec 3600 pour modeles CPU (fix timeout gros modeles)
#   - WindowStyle Hidden retire (incompatible avec NoNewWindow)

$ErrorActionPreference = "Continue"
$ResultsDir  = "$PSScriptRoot\CPUVsGPU\results"
$ResponseDir = "$ResultsDir\responses"
$LogFile     = "$ResultsDir\bench_gpu_$(Get-Date -Format 'yyyyMMdd_HHmm').log"
New-Item -ItemType Directory -Force -Path $ResultsDir  | Out-Null
New-Item -ItemType Directory -Force -Path $ResponseDir | Out-Null

function Log {
    param([string]$M, [string]$C = "White")
    $L = "[$(Get-Date -Format 'HH:mm:ss')] $M"
    Write-Host $L -ForegroundColor $C
    Add-Content $LogFile $L -Encoding UTF8
}

$Nsmi = "C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
if (-not (Test-Path $Nsmi)) { $Nsmi = "nvidia-smi" }

function GpuSnap {
    try {
        $raw = & $Nsmi --query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu `
            --format=csv,noheader,nounits 2>$null
        $p = ($raw -split ",\s*")
        return @{ U = [int]$p[0]; T = [int]$p[1]; G = [int]$p[2]; C = [int]$p[3] }
    } catch {
        return @{ U = -1; T = -1; G = -1; C = -1 }
    }
}

function CpuSnap {
    try {
        $c = (Get-Counter "\Processor(_Total)\% Processor Time" -SampleInterval 1 -MaxSamples 1 -ErrorAction Stop)
        return [math]::Round($c.CounterSamples.CookedValue, 1)
    } catch {
        return -1
    }
}

function Calc-TokPerSec {
    param($resp)
    if ($resp.eval_rate -and $resp.eval_rate -gt 0) {
        return [math]::Round($resp.eval_rate, 2)
    }
    if ($resp.eval_count -and $resp.eval_duration -and $resp.eval_duration -gt 0) {
        return [math]::Round($resp.eval_count / ($resp.eval_duration / 1e9), 2)
    }
    return 0
}

function Get-ModelInfo {
    param([string]$ModelName)
    try {
        $info = Invoke-RestMethod -Uri "http://localhost:11434/api/show" -Method Post `
            -Body (@{ name = $ModelName } | ConvertTo-Json) `
            -ContentType "application/json" -TimeoutSec 30
        $fam   = $info.details.family
        $size  = $info.details.parameter_size
        $quant = $info.details.quantization_level
        return "family=$fam size=$size quant=$quant"
    } catch {
        return "info unavailable"
    }
}

function Test-ModelExists {
    param([string]$Name)
    try {
        $list = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get -TimeoutSec 10
        return ($list.models | Where-Object { $_.name -eq $Name }) -ne $null
    } catch {
        return $false
    }
}

function Restart-Ollama {
    Log "  [RESTART] Redemarrage Ollama..." "Yellow"
    taskkill /F /IM ollama.exe /T 2>$null | Out-Null
    taskkill /F /IM ollama_llm_server.exe /T 2>$null | Out-Null
    taskkill /F /IM ollama_app.exe /T 2>$null | Out-Null
    Start-Sleep -Seconds 6

    # Reinjecter OLLAMA_MODELS pour que le nouveau process trouve les modeles
    $env:OLLAMA_MODELS = "D:\Continue\Ollama\models"
    Start-Process -FilePath "ollama" -ArgumentList "serve" -NoNewWindow

    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 2
        $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 11434 -WarningAction SilentlyContinue
        if ($tcp.TcpTestSucceeded) { Log "  [RESTART] Ollama OK" "Green"; Start-Sleep 5; return }
    }
    Log "  [RESTART] Echec" "Red"
}

function Save-Response {
    param([string]$Model, [string]$Prompt, [int]$Run, [string]$Content)
    $safe  = $Model -replace "[:\\\/]", "_"
    $fname = "${safe}__${Prompt}__run${Run}.txt"
    $fpath = "$ResponseDir\$fname"
    $hdr   = "MODEL: $Model | PROMPT: $Prompt | RUN: $Run"
    $bar   = "=" * 80
    Set-Content -Path $fpath -Value ($bar + "`n" + $hdr + "`n" + $bar + "`n`n" + $Content) -Encoding UTF8
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

$AllModels = $ModelsTierGPU + $ModelsTierCPU

# ==========================================
#  PROMPTS (text + base token budget)
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

$Results   = @()
$ProgressF = "$ResultsDir\overnight_v4_progress.json"

$Done = @{}
if (Test-Path $ProgressF) {
    try {
        $saved = Get-Content $ProgressF -Raw | ConvertFrom-Json
        foreach ($e in $saved.PSObject.Properties) { $Done[$e.Name] = $e.Value }
        Log "=== REPRISE : $($Done.Keys.Count) modeles deja traites ===" "Yellow"
    } catch { $Done = @{} }
}

function Save-Progress { $Done | ConvertTo-Json | Out-File $ProgressF -Encoding UTF8 -Force }

# ==========================================
#  BOUCLE PRINCIPALE
# ==========================================
Log "=== BENCHMARK GPU V4 -- DEBUT $(Get-Date -Format 'yyyy-MM-dd HH:mm') ===" "Cyan"
Log "  GPU : Quadro M2000M | VRAM : 4 GB" "Gray"
Log "  GPU models : $($ModelsTierGPU.Count) | CPU models : $($ModelsTierCPU.Count)" "Gray"
Log "  Prompts : $($Prompts.Keys -join ', ')" "Gray"
Log "  Responses : $ResponseDir" "Gray"
Log "" ""

$gpuInit = GpuSnap
Log "  GPU at start : $($gpuInit.U)/$($gpuInit.T) MB VRAM | $($gpuInit.G)% util" "White"
Log "" ""

foreach ($model in $AllModels) {

    if ($Done["done_$model"] -eq "ok") {
        Log "[SKIP resume] $model" "DarkGray"
        continue
    }

    # --- Verification modele present ---
    if (-not (Test-ModelExists $model)) {
        Log "  [SKIP] $model not pulled locally" "Red"
        $Done["done_$model"] = "skip"
        Save-Progress
        continue
    }

    $isCPU       = $ModelsTierCPU -contains $model
    $tier        = if ($isCPU) { "CPU" } else { "GPU" }
    $isReasoning = $model -match "^qwen3:|deepseek-r1|reasoning"
    $temperature = if ($isReasoning) { 0.6 } else { 0 }
    # Timeout adaptatif : gros modeles CPU peuvent prendre >20min sur coding_lcca
    $timeoutSec  = if ($isCPU) { 3600 } else { 600 }

    Log "" ""
    Log "============================================================" "Cyan"
    Log "  BENCHMARK : $model  [$tier]" "Cyan"
    Log "  Reasoning : $isReasoning | Temp : $temperature | Timeout : ${timeoutSec}s" "Gray"
    Log "============================================================" "Cyan"

    # --- Unload precedent pour liberer VRAM ---
    try {
        Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
            -Body (@{ model = $model; prompt = ""; keep_alive = 0 } | ConvertTo-Json) `
            -ContentType "application/json" -TimeoutSec 30 | Out-Null
        Log "  [UNLOAD] keep_alive=0 sent" "DarkGray"
    } catch {
        Log "  [UNLOAD] soft unload failed, will hard restart if needed" "DarkGray"
    }
    Start-Sleep -Seconds 3

    # --- Warmup ---
    Log "  [WARMUP] Loading $model ..." "DarkGray"
    $warmupOk = $false
    for ($w = 1; $w -le 2; $w++) {
        try {
            $swW = [System.Diagnostics.Stopwatch]::StartNew()
            $warmupBody = @{
                model   = $model
                prompt  = "hi"
                stream  = $false
                options = @{
                    num_predict = 5
                    num_gpu     = if ($isCPU) { 0 } else { -1 }
                }
            } | ConvertTo-Json
            Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
                -Body $warmupBody -ContentType "application/json" -TimeoutSec 180 | Out-Null
            $swW.Stop()
            Log "  [WARMUP] OK in $([math]::Round($swW.Elapsed.TotalMilliseconds,0)) ms" "Green"
            $warmupOk = $true
            break
        } catch {
            Log "  [WARMUP] Fail $w : $_" "Yellow"
            if ($w -eq 1) { Restart-Ollama }
        }
    }
    if (-not $warmupOk) {
        Log "  [SKIP] $model warmup failed x2" "Red"
        $Done["done_$model"] = "skip"
        Save-Progress
        continue
    }

    $modelInfo = Get-ModelInfo $model
    Log "  [INFO] $modelInfo" "Gray"
    $gpuL = GpuSnap
    Log "  [GPU after load] $($gpuL.U) MB VRAM | $($gpuL.G)% util" "Gray"

    Start-Sleep -Seconds 3

    foreach ($promptKey in $Prompts.Keys) {
        Log "  [PROMPT] $promptKey" "White"

        $basePredict = $Prompts[$promptKey].tokens
        $numPredict  = if ($isReasoning) { $basePredict * 2 } else { $basePredict }
        Log "    base_predict=$basePredict final_predict=$numPredict (reasoning=$isReasoning)" "DarkGray"

        for ($run = 1; $run -le 3; $run++) {
            Log "    [RUN $run/3]" "White"

            $gpu1  = GpuSnap
            $cpu1  = if ($isCPU) { CpuSnap } else { -1 }
            $ram1  = (Get-Process | Where-Object { $_.ProcessName -match "ollama" } |
                      Measure-Object PrivateMemorySize64 -Sum).Sum / 1MB
            Log "      GPU before : $($gpu1.U)/$($gpu1.T) MB | $($gpu1.G)% | $($gpu1.C)C | CPU=$cpu1%" "DarkGray"

            $opts = @{
                num_predict = $numPredict
                temperature = $temperature
                seed        = 42
                num_gpu     = if ($isCPU) { 0 } else { -1 }
            }
            Log "      opts : num_predict=$numPredict temperature=$temperature seed=42 num_gpu=$($opts.num_gpu)" "DarkGray"

            $sw      = [System.Diagnostics.Stopwatch]::StartNew()
            $resp    = $null
            $errMsg  = $null

            try {
                $reqBody = @{
                    model   = $model
                    prompt  = $Prompts[$promptKey].text
                    stream  = $false
                    options = $opts
                } | ConvertTo-Json -Depth 5

                $resp = Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
                    -Body $reqBody -ContentType "application/json" -TimeoutSec $timeoutSec
            } catch {
                $errMsg = "$_"
                Log "    [RUN $run] ERROR : $errMsg" "Red"
                if ($errMsg -match "500|terminated") { Restart-Ollama }
            }
            $sw.Stop()

            $ram2  = (Get-Process | Where-Object { $_.ProcessName -match "ollama" } |
                      Measure-Object PrivateMemorySize64 -Sum).Sum / 1MB
            $gpu2  = GpuSnap
            $cpu2  = if ($isCPU) { CpuSnap } else { -1 }
            Log "      GPU after : $($gpu2.U)/$($gpu2.T) MB | $($gpu2.G)% | $($gpu2.C)C | delta $($gpu2.U - $gpu1.U) MB | CPU=$cpu2%" "DarkGray"

            if ($resp) {
                $tok      = Calc-TokPerSec $resp
                $tokOut   = if ($resp.eval_count)           { $resp.eval_count }                                   else { 0 }
                $loadMs   = if ($resp.load_duration)        { [math]::Round($resp.load_duration        / 1e6, 1) } else { 0 }
                $evalMs   = if ($resp.eval_duration)        { [math]::Round($resp.eval_duration        / 1e6, 1) } else { 0 }
                $promptMs = if ($resp.prompt_eval_duration) { [math]::Round($resp.prompt_eval_duration / 1e6, 1) } else { 0 }
                $totalMs  = [math]::Round($sw.Elapsed.TotalMilliseconds, 1)
                $ramAvg   = [math]::Round(($ram1 + $ram2) / 2, 0)
                $doneRsn  = if ($resp.done_reason) { $resp.done_reason } else { "" }
                $rtext    = if ($resp.response)    { $resp.response }    else { "" }

                if ($rtext.Length -eq 0) {
                    Log "    [RUN $run] !!! RESPONSE EMPTY !!! eval_count=$tokOut done_reason=$doneRsn" "Red"
                } elseif ($rtext.Length -lt 50) {
                    Log "    [RUN $run] WARNING short response ($($rtext.Length) chars) : $rtext" "Yellow"
                }

                if ($rtext.Length -gt 0) {
                    Save-Response -Model $model -Prompt $promptKey -Run $run -Content $rtext
                }

                $color = if ($tok -ge 20) { "Green" } elseif ($tok -ge 8) { "Yellow" } else { "DarkYellow" }
                Log "    [RUN $run] $tok tok/s | ${totalMs}ms | load ${loadMs}ms | eval ${evalMs}ms | $tokOut tok | RAM ${ramAvg}MB | resp_len=$($rtext.Length) | done=$doneRsn" $color

                $Results += [PSCustomObject]@{
                    model            = $model
                    tier             = $tier
                    prompt           = $promptKey
                    run              = $run
                    tok_s            = $tok
                    tokens_out       = $tokOut
                    total_ms         = $totalMs
                    load_ms          = $loadMs
                    eval_ms          = $evalMs
                    prompt_ms        = $promptMs
                    ram_avg_mb       = $ramAvg
                    vram_before      = $gpu1.U
                    vram_after       = $gpu2.U
                    vram_delta       = ($gpu2.U - $gpu1.U)
                    gpu_util_pct     = $gpu2.G
                    cpu_util_pct     = $cpu2
                    temp_c           = $gpu2.C
                    done_reason      = $doneRsn
                    response_len     = $rtext.Length
                    error            = ""
                    response_snippet = if ($rtext.Length -gt 0) { $rtext.Substring(0, [Math]::Min(500, $rtext.Length)) } else { "" }
                }
            } else {
                $Results += [PSCustomObject]@{
                    model        = $model;  tier         = $tier
                    prompt       = $promptKey; run        = $run
                    tok_s        = 0;       tokens_out   = 0
                    total_ms     = [math]::Round($sw.Elapsed.TotalMilliseconds, 1)
                    load_ms      = 0;       eval_ms      = 0;  prompt_ms = 0
                    ram_avg_mb   = [math]::Round(($ram1 + $ram2) / 2, 0)
                    vram_before  = $gpu1.U; vram_after   = $gpu2.U; vram_delta = 0
                    gpu_util_pct = $gpu2.G; cpu_util_pct = $cpu2
                    temp_c       = $gpu2.C
                    done_reason  = "";      response_len = 0
                    error        = $errMsg; response_snippet = ""
                }
            }
            Start-Sleep -Seconds 4
        }
    }

    $Done["done_$model"] = "ok"
    Save-Progress

    $csvInc = "$ResultsDir\bench_gpu_incremental.csv"
    $Results | Export-Csv $csvInc -NoTypeInformation -Encoding UTF8 -Force

    # --- Unload explicite avant modele suivant ---
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

Log "" ""
Log "=== END $(Get-Date -Format 'yyyy-MM-dd HH:mm') ===" "Cyan"
Log "CSV final    : $csvFinal" "Green"
Log "Responses    : $ResponseDir" "Green"
Log "" ""
Log "=== FINAL RANKING ===" "Cyan"

$Results | Where-Object { $_.tok_s -gt 0 } | Group-Object model | ForEach-Object {
    $grp = $_.Group
    [PSCustomObject]@{
        Modele    = $_.Name
        Tier      = ($grp | Select-Object -First 1).tier
        TokS      = [math]::Round(($grp | Measure-Object tok_s        -Average).Average, 1)
        VRAM_MB   = [math]::Round(($grp | Measure-Object vram_after   -Average).Average, 0)
        GPU_pct   = [math]::Round(($grp | Measure-Object gpu_util_pct -Average).Average, 0)
        CPU_pct   = if (($grp | Select-Object -First 1).cpu_util_pct -eq -1) { "N/A" } `
                    else { [math]::Round(($grp | Where-Object { $_.cpu_util_pct -ge 0 } | Measure-Object cpu_util_pct -Average).Average, 0) }
        RAM_MB    = [math]::Round(($grp | Measure-Object ram_avg_mb   -Average).Average, 0)
        RespAvg   = [math]::Round(($grp | Measure-Object response_len -Average).Average, 0)
        Vides     = ($grp | Where-Object { $_.response_len -eq 0 }).Count
        Runs      = $grp.Count
    }
} | Sort-Object TokS -Descending | Format-Table -AutoSize

Log "" ""
Log "=== EMPTY RESPONSES (diagnostic) ===" "Yellow"
$Results | Where-Object { $_.response_len -eq 0 -and $_.error -eq "" } |
    Select-Object model, prompt, run, tok_s, done_reason, tokens_out |
    Format-Table -AutoSize
