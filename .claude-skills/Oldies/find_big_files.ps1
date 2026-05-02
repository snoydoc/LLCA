# find_big_files.ps1
# Analyse D:\ et liste les gros fichiers
# Usage : .\find_big_files.ps1 [-Root D:\] [-TopN 50] [-MinGB 1] [-ExportCsv]
# ASCII pur - pas d accents dans les strings critiques

param(
    [string]$Root    = "D:\",
    [int]   $TopN    = 50,
    [double]$MinGB   = 0.5,
    [switch]$ExportCsv
)

$ErrorActionPreference = "SilentlyContinue"

function Format-Size {
    param([long]$Bytes)
    if ($Bytes -ge 1GB) { return "{0:N2} GB" -f ($Bytes / 1GB) }
    if ($Bytes -ge 1MB) { return "{0:N2} MB" -f ($Bytes / 1MB) }
    return "{0:N2} KB" -f ($Bytes / 1KB)
}

$minBytes = [long]($MinGB * 1GB)
$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm"

Write-Host ""
Write-Host ("=" * 70) -ForegroundColor DarkCyan
Write-Host "  BIG FILE FINDER -- Racine : $Root" -ForegroundColor Cyan
Write-Host "  Seuil minimum : $(Format-Size $minBytes) | Top $TopN fichiers" -ForegroundColor Gray
Write-Host "  Debut : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Gray
Write-Host ("=" * 70) -ForegroundColor DarkCyan
Write-Host ""

$spinner = @('|','/','-','\')
$spinIdx  = 0
$count    = 0
$skipped  = 0

$results = [System.Collections.Generic.List[PSCustomObject]]::new()

Get-ChildItem -Path $Root -Recurse -File -Force -ErrorAction SilentlyContinue |
    ForEach-Object {
        $count++
        if ($count % 500 -eq 0) {
            Write-Host "`r  Scan... $($spinner[$spinIdx % 4])  $count fichiers analyses  " -NoNewline -ForegroundColor DarkGray
            $spinIdx++
        }
        if ($_.Length -ge $minBytes) {
            $results.Add([PSCustomObject]@{
                SizeBytes  = $_.Length
                SizeHuman  = Format-Size $_.Length
                FullPath   = $_.FullName
                FileName   = $_.Name
                Extension  = $_.Extension.ToLower()
                FolderPath = $_.DirectoryName
                LastWrite  = $_.LastWriteTime
            })
        }
    }

Write-Host "`r  Scan termine : $count fichiers analyses, $($results.Count) au-dessus du seuil.     " -ForegroundColor Green
Write-Host ""

# Trier par taille desc, garder top N
$top = $results | Sort-Object SizeBytes -Descending | Select-Object -First $TopN

if ($top.Count -eq 0) {
    Write-Host "  Aucun fichier trouve au-dessus de $(Format-Size $minBytes)." -ForegroundColor Yellow
    exit 0
}

# --- Affichage tableau ---
Write-Host ("=" * 70) -ForegroundColor DarkCyan
Write-Host ("  {0,-10}  {1,-6}  {2}" -f "TAILLE", "EXT", "CHEMIN") -ForegroundColor White
Write-Host ("=" * 70) -ForegroundColor DarkCyan

$rank = 1
foreach ($f in $top) {
    $color = if ($f.SizeBytes -ge 10GB) { "Red" }
             elseif ($f.SizeBytes -ge 4GB)  { "Yellow" }
             elseif ($f.SizeBytes -ge 1GB)  { "White" }
             else                            { "DarkGray" }

    $ext = if ($f.Extension) { $f.Extension } else { "(none)" }
    $path = $f.FullPath
    if ($path.Length -gt 80) { $path = "..." + $path.Substring($path.Length - 77) }

    Write-Host ("{0,3}. {1,-10}  {2,-6}  {3}" -f $rank, $f.SizeHuman, $ext, $path) -ForegroundColor $color
    $rank++
}

Write-Host ("=" * 70) -ForegroundColor DarkCyan

# --- Stats par extension ---
Write-Host ""
Write-Host "  TOP EXTENSIONS (par volume total) :" -ForegroundColor Cyan
$byExt = $results |
    Group-Object Extension |
    Select-Object Name,
        @{N="TotalBytes"; E={ ($_.Group | Measure-Object SizeBytes -Sum).Sum }},
        @{N="Count";      E={ $_.Count }} |
    Sort-Object TotalBytes -Descending |
    Select-Object -First 10

foreach ($e in $byExt) {
    $extLabel = if ($e.Name) { $e.Name } else { "(aucune)" }
    Write-Host ("    {0,-10}  {1,9}  x{2}" -f $extLabel, (Format-Size $e.TotalBytes), $e.Count) -ForegroundColor DarkGray
}

# --- Stats par dossier racine ---
Write-Host ""
Write-Host "  TOP DOSSIERS RACINE (par volume total) :" -ForegroundColor Cyan
$byFolder = $results | ForEach-Object {
    $parts = $_.FullPath -split [regex]::Escape([IO.Path]::DirectorySeparatorChar)
    $root2 = if ($parts.Count -ge 3) { $parts[0] + "\" + $parts[1] + "\" + $parts[2] } else { $_.FolderPath }
    [PSCustomObject]@{ Root2 = $root2; SizeBytes = $_.SizeBytes }
} |
    Group-Object Root2 |
    Select-Object Name,
        @{N="TotalBytes"; E={ ($_.Group | Measure-Object SizeBytes -Sum).Sum }},
        @{N="Count";      E={ $_.Count }} |
    Sort-Object TotalBytes -Descending |
    Select-Object -First 10

foreach ($d in $byFolder) {
    Write-Host ("    {0,-45}  {1,9}  x{2}" -f $d.Name, (Format-Size $d.TotalBytes), $d.Count) -ForegroundColor DarkGray
}

# --- Export CSV optionnel ---
if ($ExportCsv) {
    $csvPath = "$Root\big_files_$timestamp.csv"
    $results | Sort-Object SizeBytes -Descending |
        Select-Object SizeHuman, SizeBytes, FileName, Extension, FolderPath, LastWrite, FullPath |
        Export-Csv -Path $csvPath -NoTypeInformation -Encoding UTF8
    Write-Host ""
    Write-Host "  Export CSV : $csvPath" -ForegroundColor Green
}

Write-Host ""
Write-Host "  Fin : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Gray
Write-Host ("=" * 70) -ForegroundColor DarkCyan
Write-Host ""
