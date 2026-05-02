# run_overnightV2.ps1
# Corrections v2.1 :
#   - GpuSnap via GPU Intel (GPU0) en lisant les compteurs Windows, pas nvidia-smi
#   - Fallback : si eval_rate absent, calcule tok/s depuis eval_count + eval_duration
#   - Retry automatique si 500 Internal Server Error (redemarrage Ollama)
#   - Log du GPU Intel via Get-Counter (utilisation) + WMI (VRAM dediee)
# ASCII pur - pas d accents dans ce fichier

$ErrorActionPreference = "Continue"
$ResultsDir = "$PSScriptRoot\CPUVsGPU\results"
$LogFile    = "$ResultsDir\bench_v5_$(Get-Date -Format 'yyyyMMdd_HHmm').log"
New-Item -ItemType Directory -Force -Path $ResultsDir | Out-Null

function Log { 
    param([string]$M, [string]$C = "White")
    $L = "[$(Get-Date -Format 'HH:mm:ss')] $M"
    Write-Host $L -ForegroundColor $C
    Add-Content $LogFile $L -Encoding UTF8
}

# ==========================================
#  GPU SNAP : Intel iGPU (GPU0) via WMI
#  nvidia-smi ne voit que le GPU Nvidia (GPU1) qui est a 0%.
#  On utilise les compteurs Windows pour le GPU Intel.
# ==========================================
function GpuSnap {
    try {
        # Utilisation GPU Intel via compteur de performance Windows
        $counter = "\GPU Engine(*engtype_3D*)\Utilization Percentage"
        $samples = Get-Counter -Counter $counter -ErrorAction SilentlyContinue
        $gpuUtil = 0
        if ($samples) {
            $vals = $samples.CounterSamples | Where-Object { $_.CookedValue -gt 0 }
            if ($vals) { $gpuUtil = [int]($vals | Measure-Object CookedValue -Sum).Sum }
        }

        # VRAM Intel : memoire video dediee via WMI VideoController
        $vcs = Get-WmiObject Win32_VideoController -ErrorAction SilentlyContinue
        $intel = $vcs | Where-Object { $_.Name -match "Intel" } | Select-Object -First 1
        $vramUsed  = 0
        $vramTotal = 0
        if ($intel) {
            # AdapterRAM = VRAM totale en octets (souvent capped a 4GB en WMI)
            $vramTotal = [int]($intel.AdapterRAM / 1MB)
        }

        return @{ U = $vramUsed; T = $vramTotal; G = $gpuUtil; C = 0 }
    }
    catch {
        return @{ U = -1; T = -1; G = -1; C = -1 }
    }
}

# ==========================================
#  RESTART OLLAMA si crash 500
# ==========================================
function Restart-Ollama {
    Log "  [RESTART] Redemarrage Ollama apres erreur 500..." "Yellow"
    taskkill /F /IM ollama.exe /T 2>$null | Out-Null
    taskkill /F /IM ollama_llm_server.exe /T 2>$null | Out-Null
    Start-Sleep -Seconds 5
    Start-Process -FilePath "ollama" -ArgumentList "serve" -NoNewWindow
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 2
        $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 11434 -WarningAction SilentlyContinue
        if ($tcp.TcpTestSucceeded) { $ready = $true; break }
    }
    if ($ready) { Log "  [RESTART] Ollama OK" "Green" }
    else        { Log "  [RESTART] Echec redemarrage Ollama" "Red" }
    Start-Sleep -Seconds 5
}

# ==========================================
#  CALCUL tok/s robuste
#  eval_rate est absent sur certains modeles Gemma4.
#  On le recalcule depuis eval_count + eval_duration si besoin.
# ==========================================
function Calc-TokPerSec {
    param($resp)
    if ($resp.eval_rate -and $resp.eval_rate -gt 0) {
        return [math]::Round($resp.eval_rate, 2)
    }
    # Fallback : eval_count tokens / eval_duration nanosecondes
    if ($resp.eval_count -and $resp.eval_duration -and $resp.eval_duration -gt 0) {
        $tps = $resp.eval_count / ($resp.eval_duration / 1e9)
        return [math]::Round($tps, 2)
    }
    return 0
}

# ==========================================
#  MODELES ET PROMPTS
# ==========================================
$Models = @(
    "gemma4:e2b",
    "qwen3:4b",
    "phi4-mini",
    "phi4-mini-reasoning",
    "gemma3:4b",
    "deepseek-r1:8b",
    "qwen3:8b",
    "qwen3:14b",
    "deepseek-r1:14b",
    "qwen3-coder:30b-a3b-q4_K_M",
    "qwen3:30b-a3b"
)

$Prompts = @{
    code_simple = "Write a Python function named days_between that takes two date strings (YYYY-MM-DD) and returns the number of days between them. Include a docstring and a usage example."
    debug       = "Here is a buggy Python function:`n`ndef average(lst):`n    return sum(lst) / len(lst)`n`nIt crashes with ZeroDivisionError when the list is empty. Identify the bug and provide a complete fixed version."
}

$Results = @()

# ==========================================
#  BOUCLE PRINCIPALE
# ==========================================
foreach ($model in $Models) {
    Log ""
    Log "============================================================" "Cyan"
    Log "  BENCHMARK : $model" "Cyan"
    Log "============================================================" "Cyan"

    # WARMUP avec retry
    Log "  [WARMUP] Chargement a chaud..." "DarkGray"
    $warmupOk = $false
    for ($w = 1; $w -le 2; $w++) {
        try {
            Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
                -Body (@{ model = $model; prompt = "hi"; stream = $false; options = @{ num_predict = 10 } } | ConvertTo-Json) `
                -ContentType "application/json" -TimeoutSec 120 | Out-Null
            $warmupOk = $true
            break
        }
        catch {
            Log "  [WARMUP] Echec tentative $w : $_" "Yellow"
            if ($w -eq 1) { Restart-Ollama }
        }
    }
    if (-not $warmupOk) {
        Log "  [SKIP] $model : warmup echec x2 -- modele ignore" "Red"
        continue
    }
    Start-Sleep -Seconds 3

    $modelHadError = $false

    foreach ($prompt in @("code_simple", "debug")) {
        Log "  [PROMPT] $prompt" "White"

        for ($run = 1; $run -le 3; $run++) {
            Log "    [RUN $run] Debut..." "White"

            $gpu1 = GpuSnap
            Log "      GPU AVANT  : VRAM $($gpu1.U)/$($gpu1.T) MB | GPU $($gpu1.G)% | Temp $($gpu1.C)C" "DarkGray"

            $ram1 = (Get-Process | Where-Object { $_.ProcessName -match "ollama" } | Measure-Object WorkingSet64 -Sum).Sum / 1MB

            $sw   = [System.Diagnostics.Stopwatch]::StartNew()
            $resp = $null
            $errMsg = $null

            try {
                $resp = Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
                    -Body (@{
                        model   = $model
                        prompt  = $Prompts[$prompt]
                        stream  = $false
                        options = @{ num_predict = 512; temperature = 0; seed = 42 }
                    } | ConvertTo-Json) `
                    -ContentType "application/json" -TimeoutSec 300
            }
            catch {
                $errMsg = "$_"
                Log "    [RUN $run] ERREUR : $errMsg" "Red"
                if ($errMsg -match "500") {
                    $modelHadError = $true
                    Restart-Ollama
                    # Re-warmup apres restart
                    try {
                        Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post `
                            -Body (@{ model = $model; prompt = "hi"; stream = $false; options = @{ num_predict = 10 } } | ConvertTo-Json) `
                            -ContentType "application/json" -TimeoutSec 120 | Out-Null
                    } catch {}
                    Start-Sleep -Seconds 5
                }
            }
            $sw.Stop()

            $ram2  = (Get-Process | Where-Object { $_.ProcessName -match "ollama" } | Measure-Object WorkingSet64 -Sum).Sum / 1MB
            $gpu2  = GpuSnap
            $chunks = if ($resp -and $resp.response) { $resp.response.Split("`n").Count } else { 0 }

            Log "      GPU APRES  : VRAM $($gpu2.U)/$($gpu2.T) MB | GPU $($gpu2.G)% | Temp $($gpu2.C)C" "DarkGray"

            if ($resp) {
                $tok     = Calc-TokPerSec $resp
                $tokOut  = if ($resp.eval_count)    { $resp.eval_count }                                   else { 0 }
                $loadMs  = if ($resp.load_duration) { [math]::Round($resp.load_duration  / 1000000, 2) }   else { 0 }
                $evalMs  = if ($resp.eval_duration) { [math]::Round($resp.eval_duration  / 1000000, 2) }   else { 0 }
                $promptMs= if ($resp.prompt_eval_duration) { [math]::Round($resp.prompt_eval_duration / 1000000, 2) } else { 0 }
                $totalMs = [math]::Round($sw.Elapsed.TotalMilliseconds, 2)
                $ramAvg  = [math]::Round(($ram1 + $ram2) / 2, 0)

                Log "    [RUN $run] OK : $tok tok/s | ${totalMs}ms total | Load ${loadMs}ms | Eval ${evalMs}ms | Tokens $tokOut | RAM avg ${ramAvg} MB | Chunks $chunks | Delta VRAM $($gpu2.U - $gpu1.U) MB" "Green"

                $Results += [PSCustomObject]@{
                    model        = $model
                    prompt       = $prompt
                    run          = $run
                    tok_s        = $tok
                    tokens_out   = $tokOut
                    total_ms     = $totalMs
                    load_ms      = $loadMs
                    eval_ms      = $evalMs
                    prompt_ms    = $promptMs
                    ram_avg_mb   = $ramAvg
                    vram_before  = $gpu1.U
                    vram_after   = $gpu2.U
                    vram_delta   = ($gpu2.U - $gpu1.U)
                    gpu_util_pct = $gpu2.G
                    temp_c       = $gpu2.C
                    response     = if ($resp.response) { $resp.response.Substring(0, [Math]::Min(200, $resp.response.Length)) } else { "" }
                    error        = ""
                }
            } else {
                $Results += [PSCustomObject]@{
                    model        = $model; prompt = $prompt; run = $run
                    tok_s        = 0; tokens_out = 0; total_ms = [math]::Round($sw.Elapsed.TotalMilliseconds, 2)
                    load_ms      = 0; eval_ms = 0; prompt_ms = 0
                    ram_avg_mb   = [math]::Round(($ram1 + $ram2) / 2, 0)
                    vram_before  = $gpu1.U; vram_after = $gpu2.U; vram_delta = 0
                    gpu_util_pct = $gpu2.G; temp_c = $gpu2.C; response = ""; error = $errMsg
                }
            }
            Start-Sleep -Seconds 5
        }
    }
    Start-Sleep -Seconds 10
}

# ==========================================
#  EXPORT CSV + RESUME
# ==========================================
$csv = "$ResultsDir\v5_results_$(Get-Date -Format 'yyyyMMdd_HHmmss').csv"
$Results | Export-Csv $csv -NoTypeInformation -Encoding UTF8
Log ""
Log "CSV : $csv" "Green"
Log ""
Log "=== RESUME PAR MODELE ===" "Cyan"
$Results | Where-Object { $_.tok_s -gt 0 } | Group-Object model | ForEach-Object {
    [PSCustomObject]@{
        Model      = $_.Name
        'Tok/s'    = ([math]::Round(($_.Group | Measure-Object tok_s    -Average).Average, 2))
        'RAM MB'   = ([math]::Round(($_.Group | Measure-Object ram_avg_mb -Average).Average, 0))
        'GPU%'     = ([math]::Round(($_.Group | Measure-Object gpu_util_pct -Average).Average, 0))
        'Erreurs'  = ($Results | Where-Object { $_.model -eq $_.Name -and $_.error -ne "" }).Count
        Runs       = $_.Group.Count
    }
} | Sort-Object 'Tok/s' -Descending | Format-Table -AutoSize
