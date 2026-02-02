param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Babylon', 'AIE')]
    [string]$Source,

    [Parameter(Mandatory = $true)]
    [ValidateSet('Raw', 'Zip')]
    [string]$Mode,

    [Parameter(Mandatory = $true)]
    [string]$Destination,

    [string[]]$IncludeExtra = @(),
    [switch]$UseTimestamp,
    [switch]$Force,

    [string]$BabylonRoot = "E:\AI projects 2025\BABYLON VER 2",
    [string]$AIEHarnessRoot = "E:\Documents old and new\Documents 2026\SBS-AI-Chatbot\AIE-TestHarness\TestHarness"
)

$baseWhitelist = @('Assets', 'ProjectSettings', 'Packages')
$includeList = New-Object System.Collections.Generic.List[string]
$baseWhitelist | ForEach-Object { $includeList.Add($_) }
$IncludeExtra | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { $includeList.Add($_) }
$entries = $includeList | Select-Object -Unique

$sourceRoot = if ($Source -eq 'Babylon') { $BabylonRoot } else { $AIEHarnessRoot }
if (-not (Test-Path $sourceRoot)) {
    throw "Source root not found: $sourceRoot"
}

$Destination = Resolve-DestinationPath -Path $Destination -Mode $Mode -UseTimestamp:$UseTimestamp

if ($Mode -eq 'Raw') {
    Invoke-RawExport -SourceRoot $sourceRoot -Destination $Destination -Entries $entries -Force:$Force
}
else {
    Invoke-ZipExport -SourceRoot $sourceRoot -Destination $Destination -Entries $entries -Force:$Force
}

function Resolve-DestinationPath {
    param(
        [string]$Path,
        [string]$Mode,
        [switch]$UseTimestamp
    )

    $resolved = [System.IO.Path]::GetFullPath($Path)
    if ($UseTimestamp) {
        $timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
        if ($Mode -eq 'Zip') {
            $dir = Split-Path $resolved -Parent
            if (-not $dir) { $dir = (Get-Location).Path }
            $file = Split-Path $resolved -Leaf
            $filename = [System.IO.Path]::GetFileNameWithoutExtension($file)
            $ext = [System.IO.Path]::GetExtension($file)
            if (-not $ext) { $ext = '.zip' }
            $resolved = Join-Path $dir ("{0}_{1}{2}" -f $filename, $timestamp, $ext)
        }
        else {
            $trimmed = $resolved.TrimEnd('\')
            if (-not $trimmed) { $trimmed = (Get-Location).Path }
            $resolved = "{0}_{1}" -f $trimmed, $timestamp
        }
    }

    if ($Mode -eq 'Zip' -and -not $resolved.EndsWith('.zip')) {
        $resolved = "$resolved.zip"
    }

    return $resolved
}

function Invoke-RawExport {
    param(
        [string]$SourceRoot,
        [string]$Destination,
        [string[]]$Entries,
        [switch]$Force
    )

    if ((Test-Path $Destination) -and -not $Force) {
        throw "Destination already exists: $Destination (use -Force to overwrite)"
    }

    New-Item -ItemType Directory -Path $Destination -Force | Out-Null

    foreach ($entry in $Entries) {
        $sourcePath = Join-Path $SourceRoot $entry
        if (-not (Test-Path $sourcePath)) {
            Write-Warning "Skipping missing entry: $entry"
            continue
        }

        $destPath = Join-Path $Destination $entry
        $destParent = Split-Path $destPath -Parent
        if (-not (Test-Path $destParent)) {
            New-Item -ItemType Directory -Path $destParent -Force | Out-Null
        }

        $item = Get-Item $sourcePath
        if ($item.PSIsContainer) {
            Copy-Item -Path $sourcePath -Destination $destPath -Recurse -Force
        }
        else {
            Copy-Item -Path $sourcePath -Destination $destParent -Force
        }
        Write-Host "Exported $entry"
    }

    Write-Host "Raw export completed: $Destination" -ForegroundColor Green
}

function Invoke-ZipExport {
    param(
        [string]$SourceRoot,
        [string]$Destination,
        [string[]]$Entries,
        [switch]$Force
    )

    $destDir = Split-Path $Destination -Parent
    if (-not $destDir) { $destDir = Get-Location }
    if (-not (Test-Path $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }

    if ((Test-Path $Destination) -and -not $Force) {
        throw "Destination zip already exists: $Destination (use -Force to overwrite)"
    }

    if (Test-Path $Destination) {
        Remove-Item $Destination -Force
    }

    $pathsToZip = @()
    foreach ($entry in $Entries) {
        $sourcePath = Join-Path $SourceRoot $entry
        if (-not (Test-Path $sourcePath)) {
            Write-Warning "Skipping missing entry: $entry"
            continue
        }
        $pathsToZip += $sourcePath
        Write-Host "Queued $entry for archive"
    }

    if ($pathsToZip.Count -eq 0) {
        throw "No valid entries found to export."
    }

    Compress-Archive -Path $pathsToZip -DestinationPath $Destination -Force
    Write-Host "Zip export completed: $Destination" -ForegroundColor Green
}
