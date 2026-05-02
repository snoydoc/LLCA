# run_benchmark_full_v4.ps1
# Corrige : streaming avec HttpWebRequest, monitoring via fichier signal, pas de used_memory par processus
# Sauvegarder en UTF-8 avec BOM

[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
$ResultsDir   = "$PSScriptRoot\CPUVsGPU\results"
$ProgressFile = "$ResultsDir\benchmark_progress.json"
$LogFile      = "$ResultsDir\benchmark_$(Get-Date -Format 'yyyyMMdd_HHmm').log"
New-Item -ItemType Directory -Force -Path $ResultsDir | Out-Null

$NumRuns    = 3
$MaxTokens  = 512
$Temp       = 0.0
$Seed       = 42
$PauseEntreRuns = 5
$PauseEntreModeles = 10

$Prompts = @{
    code_simple = "Write a Python function named days_between that takes two date strings (YYYY-MM-DD) and returns the number of days between them. Include a docstring and a usage example."
    debug       = "Here is a buggy Python function:`n`ndef average(lst):`n    return sum(lst) / len(lst)`n`nIt crashes with ZeroDivisionError when the list is empty. Identify the bug and provide a complete fixed version."
}

$AllModels = @(
    "gemma4:e2b","qwen3:4b","phi4-mini","phi4-mini-reasoning","gemma3:4b",
    "deepseek-r1:8b","qwen3:8b","qwen3:14b","deepseek-r1:14b",
    "qwen3-coder:30b-a3b-q4_K_M","qwen3:30b-a3b"
)

function Write-Log {
    param([string]$Msg, [string]$Color = "White")
    $line = "[$(Get-Date -Format 'HH:mm:ss')] $Msg"
    Write-Host $line -ForegroundColor $Color
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Save-ProgressState {
    $script:Done | ConvertTo-Json -Depth 5 | Out-File -FilePath $ProgressFile -Encoding UTF8 -Force
}

function Normalize-ModelName {
    param([string]$Name)
    return ($Name -replace ":latest$", "").Trim().ToLower()
}

# ==========================================
#  NVIDIA-SMI
# ==========================================
function Get-NvidiaSmiPath {
    $candidates = @(
        "C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
        "C:\Windows\System32\nvidia-smi.exe",
        "nvidia-smi"
    )
    foreach ($c in $candidates) {
        if ($c -eq "nvidia-smi") { try { $null = & $c --version 2>$null; return $c } catch {} }
        elseif (Test-Path $c) { return $c }
    }
    return $null
}

$script:NvidiaSmiPath = Get-NvidiaSmiPath
if ($script:NvidiaSmiPath) { Write-Log "nvidia-smi : $($script:NvidiaSmiPath)" "Green" }
else { Write-Log "nvidia-smi introuvable." "Yellow" }

function ParseNum {
    param([string]$Value, [int]$Default = -1)
    $clean = $Value.Trim()
    if ($clean -match "^\d+(\.\d+)?$") {
        if ($clean -match "\.") { return [math]::Round([double]$clean, 1) }
        return [int]$clean
    }
    return $Default
}

function Get-GpuSnapshot {
    if (-not $script:NvidiaSmiPath) {
        return [PSCustomObject]@{ VramUsedMB = -1; VramTotalMB = -1; GpuUtilPct = -1; TempC = -1; Raw = "NOT_FOUND" }
    }
    try {
        $csv = & $script:NvidiaSmiPath --query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader,nounits 2>$null
        $parts = $csv -split ",\s*"
        return [PSCustomObject]@{
            VramUsedMB  = ParseNum -Value $parts[0]
            VramTotalMB = ParseNum -Value $parts[1]
            GpuUtilPct  = ParseNum -Value $parts[2]
            TempC       = ParseNum -Value $parts[3]
            Raw         = $csv
        }
    } catch {
        return [PSCustomObject]@{ VramUsedMB = -1; VramTotalMB = -1; GpuUtilPct = -1; TempC = -1; Raw = "ERROR" }
    }
}

# ==========================================
#  OLLAMA
# ==========================================
function Test-OllamaRunning {
    try { $null = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method GET -TimeoutSec 3; return $true }
    catch { return $false }
}

function Start-OllamaIfNeeded {
    if (Test-OllamaRunning) {
        Write-Log "Ollama actif -- preservation cache." "Green"
        return $null
    }
    Write-Log "Demarrage Ollama..." "Yellow"
    taskkill /F /IM ollama.exe /T 2>$null | Out-Null
    taskkill /F /IM ollama_llm_server.exe /T 2>$null | Out-Null
    Start-Sleep -Seconds 3
    Get-Process | Where-Object { $_.ProcessName -match "ollama" } | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    $env:OLLAMA_NUM_GPU = "99"
    $env:CUDA_VISIBLE_DEVICES = "0"
    $proc = Start-Process -FilePath "ollama" -ArgumentList "serve" -NoNewWindow -PassThru
    for ($i = 0; $i -lt 60; $i++) { Start-Sleep -Seconds 1; if (Test-OllamaRunning) { break } }
    Start-Sleep -Seconds 5
    Write-Log "Ollama pret." "Green"
    return $proc
}

function Get-InstalledModelNames {
    $raw = ollama list 2>$null
    $list = @()
    foreach ($line in ($raw -split "`r?`n" | Select-Object -Skip 1)) {
        $name = ($line -split "\s+")[0]
        if ($name) { $list += (Normalize-ModelName -Name $name) }
    }
    return $list
}

function Test-ModelIsInstalled {
    param([string]$ModelName, [string[]]$InstalledList)
    return $InstalledList -contains (Normalize-ModelName -Name $ModelName)
}

# ==========================================
#  MONITORING SYSTEME (fichier signal)
# ==========================================
function Start-SystemMonitor {
    param([string]$SignalFile)
    return Start-Job -ScriptBlock {
        param($sigFile)
        $samples = @()
        while (-not (Test-Path "$sigFile.stop")) {
            $procs = Get-Process | Where-Object { $_.ProcessName -match "ollama" }
            $ramMB = 0
            foreach ($p in $procs) { $ramMB += [math]::Round($p.WorkingSet64 / 1MB, 1) }
            $cpu = try { [math]::Round((Get-Counter '\Processor(_Total)\% Processor Time' -ErrorAction Stop).CounterSamples.CookedValue, 1) } catch { 0 }
            $samples += [PSCustomObject]@{ Time = Get-Date -Format "HH:mm:ss"; RamMB = $ramMB; CpuPct = $cpu }
            Start-Sleep -Milliseconds 500
        }
        $samples | ConvertTo-Json | Out-File -FilePath $sigFile -Encoding UTF8
    } -ArgumentList $SignalFile
}

function Stop-SystemMonitor {
    param($Job, [string]$SignalFile)
    $null | Out-File -FilePath "$SignalFile.stop" -Encoding UTF8 -Force
    Start-Sleep -Seconds 1
    $data = @()
    if (Test-Path $SignalFile) {
        try { $data = Get-Content $SignalFile -Raw | ConvertFrom-Json } catch {}
        Remove-Item $SignalFile -ErrorAction SilentlyContinue
    }
    Remove-Item "$SignalFile.stop" -ErrorAction SilentlyContinue
    Stop-Job $Job -ErrorAction SilentlyContinue
    Remove-Job $Job -ErrorAction SilentlyContinue
    return $data
}

# ==========================================
#  BENCHMARK 1 RUN (HttpWebRequest pour streaming)
# ==========================================
function Invoke-SingleRun {
    param([string]$ModelName, [string]$PromptName, [int]$RunNumber)

    Write-Log "    [RUN $RunNumber] Debut..." "White"

    $gpuBefore = Get-GpuSnapshot
    Write-Log "      GPU AVANT  : VRAM $($gpuBefore.VramUsedMB)/$($gpuBefore.VramTotalMB) MB | GPU $($gpuBefore.GpuUtilPct)% | Temp $($gpuBefore.TempC)C" "DarkGray"

    $signalFile = "$env:TEMP\bench_monitor_$(Get-Random).json"
    $sysJob = Start-SystemMonitor -SignalFile $signalFile

    # --- HttpWebRequest pour vrai streaming ---
    $body = @{
        model   = $ModelName
        prompt  = $Prompts[$PromptName]
        options = @{ num_predict = $MaxTokens; temperature = $Temp; seed = $Seed }
        stream  = $true
    } | ConvertTo-Json -Depth 5

    $bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
    $req = [System.Net.HttpWebRequest]::Create("http://localhost:11434/api/generate")
    $req.Method = "POST"
    $req.ContentType = "application/json"
    $req.ContentLength = $bytes.Length
    $req.KeepAlive = $false
    $req.Timeout = 600000

    $reqStream = $req.GetRequestStream()
    $reqStream.Write($bytes, 0, $bytes.Length)
    $reqStream.Close()

    $swTotal = [System.Diagnostics.Stopwatch]::StartNew()
    $swTTFT  = [System.Diagnostics.Stopwatch]::StartNew()
    $ttftMs = $null
    $fullResponse = ""
    $doneStats = $null
    $errorMsg = $null
    $chunkCount = 0

    try {
        $resp = $req.GetResponse()
        $stream = $resp.GetResponseStream()
        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)
        $first = $true

        while ($null -ne ($line = $reader.ReadLine())) {
            if ($line -eq "") { continue }
            $chunkCount++
            if ($first) {
                $swTTFT.Stop()
                $ttftMs = [math]::Round($swTTFT.Elapsed.TotalMilliseconds, 2)
                $first = $false
            }
            try {
                $chunk = $line | ConvertFrom-Json
                if ($chunk.response) { $fullResponse += $chunk.response }
                if ($chunk.done) { $doneStats = $chunk }
            } catch {}
        }
        $reader.Close()
        $resp.Close()
    } catch {
        $errorMsg = $_.Exception.Message
    } finally {
        $swTotal.Stop()
    }

    $sysData = Stop-SystemMonitor -Job $sysJob -SignalFile $signalFile

    Start-Sleep -Seconds 2
    $gpuAfter = Get-GpuSnapshot
    Write-Log "      GPU APRES  : VRAM $($gpuAfter.VramUsedMB)/$($gpuAfter.VramTotalMB) MB | GPU $($gpuAfter.GpuUtilPct)% | Temp $($gpuAfter.TempC)C" "DarkGray"

    if ($sysData -and $sysData.Count -gt 0) {
        $ramAvg = [math]::Round(($sysData | Measure-Object -Property RamMB -Average).Average, 0)
        $ramMax = [math]::Round(($sysData | Measure-Object -Property RamMB -Maximum).Maximum, 0)
        $cpuAvg = [math]::Round(($sysData | Measure-Object -Property CpuPct -Average).Average, 1)
        $cpuMax = [math]::Round(($sysData | Measure-Object -Property CpuPct -Maximum).Maximum, 1)
    } else { $ramAvg = $ramMax = $cpuAvg = $cpuMax = 0 }

    $tokensOut = if ($doneStats -and $doneStats.eval_count) { $doneStats.eval_count } else { 0 }
    $totalSec  = [math]::Round($swTotal.Elapsed.TotalSeconds, 2)
    $loadMs    = if ($doneStats -and $doneStats.load_duration) { [math]::Round($doneStats.load_duration / 1000000, 2) } else { 0 }

    $tokPerSec = 0
    if ($doneStats -and $doneStats.eval_rate) {
        $tokPerSec = [math]::Round($doneStats.eval_rate, 2)
    } elseif ($tokensOut -gt 0 -and $totalSec -gt 0 -and $ttftMs -and $ttftMs -gt 0) {
        $genTime = $totalSec - ($ttftMs / 1000)
        if ($genTime -gt 0.1) { $tokPerSec = [math]::Round($tokensOut / $genTime, 2) }
    }

    $vramDelta = $gpuAfter.VramUsedMB - $gpuBefore.VramUsedMB

    $safeModel = $ModelName -replace "[:\/]", "_"
    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    $respFile = "$ResultsDir\resp_${safeModel}_${PromptName}_r${RunNumber}_$ts.txt"
    $fullResponse | Out-File -FilePath $respFile -Encoding UTF8 -Force

    $result = [PSCustomObject]@{
        model = $ModelName; prompt_name = $PromptName; run_number = $RunNumber
        timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        tokens_out = $tokensOut; tok_per_sec = $tokPerSec; total_sec = $totalSec
        ttft_ms = $ttftMs; load_ms = $loadMs; error = $errorMsg; chunk_count = $chunkCount
        ram_avg_mb = $ramAvg; ram_max_mb = $ramMax; cpu_avg_pct = $cpuAvg; cpu_max_pct = $cpuMax
        gpu_vram_before_mb = $gpuBefore.VramUsedMB; gpu_vram_total_mb = $gpuBefore.VramTotalMB
        gpu_util_before_pct = $gpuBefore.GpuUtilPct; gpu_temp_before_c = $gpuBefore.TempC
        gpu_vram_after_mb = $gpuAfter.VramUsedMB; gpu_util_after_pct = $gpuAfter.GpuUtilPct
        gpu_temp_after_c = $gpuAfter.TempC; gpu_vram_delta_mb = $vramDelta
        response_file = $respFile
        response_preview = if ($fullResponse.Length -gt 200) { $fullResponse.Substring(0, 200) } else { $fullResponse }
    }

    if ($errorMsg) {
        Write-Log "    [RUN $RunNumber] ERREUR : $errorMsg" "Red"
    } else {
        Write-Log "    [RUN $RunNumber] OK : ${tokPerSec} tok/s | ${totalSec}s | TTFT ${ttftMs}ms | RAM ${ramAvg} MB | Chunks ${chunkCount} | Delta VRAM ${vramDelta} MB" "Green"
    }
    return $result
}

function Invoke-ModelBenchmark {
    param([string]$ModelName)
    Write-Log "" "White"
    Write-Log "============================================================" "Cyan"
    Write-Log "  BENCHMARK : $ModelName" "Cyan"
    Write-Log "============================================================" "Cyan"

    $allRuns = @()
    $safeModel = $ModelName -replace "[:\/]", "_"

    Write-Log "  [WARMUP] Chargement a chaud..." "DarkGray"
    try {
        $wc = New-Object System.Net.WebClient
        $wc.Encoding = [System.Text.Encoding]::UTF8
        $wc.Headers.Add("Content-Type", "application/json")
        $wb = @{ model = $ModelName; prompt = "Say hello"; options = @{ num_predict = 10; temperature = 0.0; seed = 42 }; stream = $false } | ConvertTo-Json -Depth 5
        [void]$wc.UploadString("http://localhost:11434/api/generate", $wb)
    } catch { Write-Log "  [WARMUP] Echec : $($_.Exception.Message)" "Yellow" }
    Start-Sleep -Seconds 3

    foreach ($promptName in @("code_simple", "debug")) {
        Write-Log "  [PROMPT] $promptName" "White"
        for ($run = 1; $run -le $NumRuns; $run++) {
            $allRuns += Invoke-SingleRun -ModelName $ModelName -PromptName $promptName -RunNumber $run
            Start-Sleep -Seconds $PauseEntreRuns
        }
    }

    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    $jsonFile = "$ResultsDir\benchmark_${safeModel}_$ts.json"
    $allRuns | ConvertTo-Json -Depth 10 | Out-File -FilePath $jsonFile -Encoding UTF8 -Force
    Write-Log "  [SAVE] $jsonFile" "DarkGray"
    return $allRuns
}

function Export-ConsolidatedCsv {
    param($AllResults)
    $csvFile = "$ResultsDir\consolidated_$(Get-Date -Format 'yyyyMMdd_HHmmss').csv"
    $AllResults | Select-Object model, prompt_name, run_number, tok_per_sec, total_sec, ttft_ms, chunk_count, `
        ram_avg_mb, ram_max_mb, cpu_avg_pct, cpu_max_pct, `
        gpu_vram_before_mb, gpu_vram_after_mb, gpu_vram_delta_mb, `
        gpu_util_before_pct, gpu_util_after_pct, gpu_temp_before_c, gpu_temp_after_c, `
        tokens_out, error | Export-Csv -Path $csvFile -NoTypeInformation -Encoding UTF8
    Write-Log "CSV : $csvFile" "Green"
    return $csvFile
}

function Show-FinalReport {
    param($AllResults)
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  RAPPORT FINAL" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    $report = $AllResults | Group-Object -Property model | ForEach-Object {
        $runs = $_.Group
        $avgTok = [math]::Round(($runs | Measure-Object -Property tok_per_sec -Average).Average, 2)
        $avgRam = [math]::Round(($runs | Measure-Object -Property ram_avg_mb -Average).Average, 0)
        $avgVramDelta = [math]::Round(($runs | Measure-Object -Property gpu_vram_delta_mb -Average).Average, 0)
        $hasGpu = ($runs | Where-Object { $_.gpu_vram_delta_mb -ne 0 }).Count -gt 0
        $hasErr = ($runs | Where-Object { $_.error }).Count -gt 0
        [PSCustomObject]@{
            Modele = $_.Name; 'Tok/s moy' = $avgTok; 'RAM avg MB' = $avgRam
            'VRAM delta MB' = $avgVramDelta
            'GPU?' = if ($hasGpu) { "OUI (delta VRAM)" } else { "NON (CPU)" }
            'Erreurs?' = if ($hasErr) { "OUI" } else { "Non" }; Runs = $runs.Count
        }
    }
    $report | Sort-Object -Property 'Tok/s moy' -Descending | Format-Table -AutoSize
    $txtFile = "$ResultsDir\report_final_$(Get-Date -Format 'yyyyMMdd_HHmmss').txt"
    $report | Sort-Object -Property 'Tok/s moy' -Descending | Format-Table -AutoSize | Out-File -FilePath $txtFile -Encoding UTF8
    Write-Log "Rapport : $txtFile" "Green"
}

# ==========================================
#  MAIN
# ==========================================
Write-Log "============================================================" "Cyan"
Write-Log "  BENCHMARK COMPLET OLLAMA + VRAM LOGGING v4" "Cyan"
Write-Log "  Lenovo P50 | Quadro M2000M 4GB | 24GB RAM" "Cyan"
Write-Log "============================================================" "Cyan"
Write-Log "Log : $LogFile" "Gray"
Write-Log "Debut : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" "White"

$script:Done = @{}
if (Test-Path $ProgressFile) {
    try {
        $saved = Get-Content $ProgressFile -Raw | ConvertFrom-Json
        foreach ($e in $saved.PSObject.Properties) { $script:Done[$e.Name] = $e.Value }
        Write-Log "Reprise : $($script:Done.Keys -join ', ')" "Yellow"
    } catch { $script:Done = @{} }
}

$OllamaProc = Start-OllamaIfNeeded
$InstalledList = Get-InstalledModelNames
Write-Log "Modeles installes : $($InstalledList.Count)" "Green"

Write-Log ""
Write-Log "--- Verification ---" "Cyan"
foreach ($model in $AllModels) {
    if (Test-ModelIsInstalled -ModelName $model -InstalledList $InstalledList) {
        Write-Log "  [OK]   $model" "Green"
    } else {
        Write-Log "  [MISS] $model -- PULL..." "Yellow"
        ollama pull $model 2>&1 | ForEach-Object { Add-Content -Path $LogFile -Value $_ -Encoding UTF8 }
        $InstalledList = Get-InstalledModelNames
    }
}

Write-Log ""
Write-Log "--- BENCHMARK ---" "Cyan"
$AllResults = @()
foreach ($model in $AllModels) {
    if ($script:Done["bench_$model"] -eq "ok") {
        Write-Log "[SKIP] $model" "DarkGray"
        continue
    }
    try {
        $res = Invoke-ModelBenchmark -ModelName $model
        $AllResults += $res
        $script:Done["bench_$model"] = "ok"
        Save-ProgressState
    } catch {
        Write-Log "[ERR] $model : $_" "Red"
        Start-Sleep -Seconds 10
    }
    Write-Log "Pause ${PauseEntreModeles}s..." "DarkGray"
    Start-Sleep -Seconds $PauseEntreModeles
}

if ($AllResults.Count -gt 0) {
    $jsonFile = "$ResultsDir\summary_all_$(Get-Date -Format 'yyyyMMdd_HHmmss').json"
    $AllResults | ConvertTo-Json -Depth 10 | Out-File -FilePath $jsonFile -Encoding UTF8 -Force
    Write-Log "JSON : $jsonFile" "Green"
    Export-ConsolidatedCsv -AllResults $AllResults | Out-Null
    Show-FinalReport -AllResults $AllResults
}

Remove-Item $ProgressFile -Force -ErrorAction SilentlyContinue
Write-Log ""
Write-Log "=== FIN ===" "Cyan"
Write-Log "Fin : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" "White"
Write-Log "Resultats : $ResultsDir\" "Green"
