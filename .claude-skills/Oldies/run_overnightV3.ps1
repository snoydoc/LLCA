# run_overnightV3.ps1
# Benchmark GPU-ready : Quadro M2000M (4GB VRAM CUDA)
# Lancer via prepare_and_launch.ps1 -- ne pas lancer directement
# ASCII pur - pas d accents dans ce fichier
#
# V3.1 (2026-04-26) :
#   - qwen2.5-coder:3b ajoute (modele prod LCCA manquant du run precedent)
#   - Prompt coding_lcca : tache reelle style LCCA (refacto Python)
#   - Reponses completes sauvegardees dans responses\ (un .txt par run)
#   - Snippet CSV porte a 500 chars (etait 150)
#   - Warmup mesure en ms
#   - Colonnes supplementaires : done_reason, response_len, vides

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

function Restart-Ollama {
    Log "  [RESTART] Redemarrage Ollama..." "Yellow"
    taskkill /F /IM ollama.exe /T 2>$null | Out-Null
    taskkill /F /IM ollama_llm_server.exe /T 2>$null | Out-Null
    Start-Sleep -Seconds 6
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
#  PRIORITE 1 : qwen2.5-coder:3b -- modele prod LCCA absent du run precedent
# ==========================================
$ModelsTierGPU = @(
    "qwen2.5-coder:3b",
    "gemma4:e2b",
    "qwen3:4b",
    "phi4-mini-reasoning",
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
#  PROMPTS
#  coding_lcca = tache reelle LCCA : refacto classe Python avec regles LCCA
# ==========================================
$Prompts = [ordered]@{
    code_simple = "Write a Python function named days_between that takes two date strings (YYYY-MM-DD) and returns the number of days between them. Include a docstring and a usage example."

    debug = "Here is a buggy Python function:`n`ndef average(lst):`n    return sum(lst) / len(lst)`n`nIt crashes with ZeroDivisionError when the list is empty. Identify the bug and provide a complete fixed version."

    coding_lcca = "You are a Python code assistant. Refactor the following class. Rules: use pathlib.Path not os.path, PascalCase for classes, snake_case for functions, docstring on every function, handle edge cases, return complete file without truncation.`n`nCode:`n`nimport os`n`nclass fileManager:`n    def __init__(self, base):`n        self.base = base`n    def ReadFile(self, name):`n        p = os.path.join(self.base, name)`n        return open(p).read()`n    def WriteFile(self, name, data):`n        p = os.path.join(self.base, name)`n        open(p, 'w').write(data)`n    def listfiles(self):`n        return os.listdir(self.base)"
}

$Results   = @()
$ProgressF = "$ResultsDir\overnight_v3_progress.json"

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
Log "=== BENCHMARK GPU V3.1 -- DEBUT $(Get-Date -Format 'yyyy-MM-dd HH:mm') ===" "Cyan"
Log "  GPU : Quadro M2000M | VRAM : 4 GB | CUDA : 12.1" "Gray"
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

    $isCPU = $ModelsTierCPU -contains $model
    $tier  = if ($isCPU) { "CPU" } else { "GPU" }

    Log "" ""
    Log "============================================================" "Cyan"
    Log "  BENCHMARK : $model  [$tier]" "Cyan"
    Log "============================================================" "Cyan"

    Log "  [WARMUP] Loading $model ..." "DarkGray"
    $warmupOk = $false
    for ($w = 1; $w -le 2; $w++) {
        try {
            $swW = [System.Diagnostics.Stopwatch]::StartNew()
            Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
                -Body (@{ model=$model; prompt="hi"; stream=$false; options=@{num_predict=5} } | ConvertTo-Json) `
                -ContentType "application/json" -TimeoutSec 180 | Out-Null
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

        for ($run = 1; $run -le 3; $run++) {
            Log "    [RUN $run/3]" "White"

            $gpu1 = GpuSnap
            $ram1 = (Get-Process | Where-Object { $_.ProcessName -match "ollama" } |
                     Measure-Object WorkingSet64 -Sum).Sum / 1MB
            Log "      GPU before : $($gpu1.U)/$($gpu1.T) MB | $($gpu1.G)% | $($gpu1.C)C" "DarkGray"

            $opts = @{ num_predict = 512; temperature = 0; seed = 42 }
            Log "      opts : num_predict=$($opts.num_predict) temperature=$($opts.temperature) seed=$($opts.seed)" "DarkGray"

            $sw      = [System.Diagnostics.Stopwatch]::StartNew()
            $resp    = $null
            $errMsg  = $null

            try {
                $resp = Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
                    -Body (@{
                        model   = $model
                        prompt  = $Prompts[$promptKey]
                        stream  = $false
                        options = $opts
                    } | ConvertTo-Json -Depth 5) `
                    -ContentType "application/json" -TimeoutSec 600
            } catch {
                $errMsg = "$_"
                Log "    [RUN $run] ERROR : $errMsg" "Red"
                if ($errMsg -match "500|terminated") { Restart-Ollama }
            }
            $sw.Stop()

            $ram2 = (Get-Process | Where-Object { $_.ProcessName -match "ollama" } |
                     Measure-Object WorkingSet64 -Sum).Sum / 1MB
            $gpu2 = GpuSnap
            Log "      GPU after : $($gpu2.U)/$($gpu2.T) MB | $($gpu2.G)% | $($gpu2.C)C | delta $($gpu2.U - $gpu1.U) MB" "DarkGray"

            if ($resp) {
                $tok      = Calc-TokPerSec $resp
                $tokOut   = if ($resp.eval_count)           { $resp.eval_count }                                          else { 0 }
                $loadMs   = if ($resp.load_duration)        { [math]::Round($resp.load_duration        / 1e6, 1) }        else { 0 }
                $evalMs   = if ($resp.eval_duration)        { [math]::Round($resp.eval_duration        / 1e6, 1) }        else { 0 }
                $promptMs = if ($resp.prompt_eval_duration) { [math]::Round($resp.prompt_eval_duration / 1e6, 1) }        else { 0 }
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
                    gpu_util_pct = $gpu2.G; temp_c       = $gpu2.C
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
        TokS      = [math]::Round(($grp | Measure-Object tok_s       -Average).Average, 1)
        VRAM_MB   = [math]::Round(($grp | Measure-Object vram_after  -Average).Average, 0)
        GPU_pct   = [math]::Round(($grp | Measure-Object gpu_util_pct -Average).Average, 0)
        RAM_MB    = [math]::Round(($grp | Measure-Object ram_avg_mb  -Average).Average, 0)
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
