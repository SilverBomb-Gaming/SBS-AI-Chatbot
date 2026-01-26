param(
    [string]$RunPath,
    [int]$MaxScreenshots = 80,
    [string]$OutDir,
    [switch]$Open,
    [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Info([string]$Message) {
    if (-not $Quiet) {
        Write-Host $Message
    }
}

function Resolve-RepoRoot {
    $here = Get-Location
    return $here.Path
}

function Resolve-LatestRun([string]$ArtifactsRoot) {
    if (-not (Test-Path -LiteralPath $ArtifactsRoot)) {
        return $null
    }
    $latest = Get-ChildItem -LiteralPath $ArtifactsRoot -Directory |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        return $null
    }
    return $latest.FullName
}

function Ensure-Directory([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Copy-IfExists([string]$Source, [string]$Destination) {
    if (Test-Path -LiteralPath $Source) {
        Copy-Item -LiteralPath $Source -Destination $Destination -Force
        return $true
    }
    return $false
}

function Copy-Directory([string]$SourceDir, [string]$DestinationDir) {
    if (-not (Test-Path -LiteralPath $SourceDir)) {
        return $false
    }
    Ensure-Directory $DestinationDir
    Copy-Item -LiteralPath $SourceDir\* -Destination $DestinationDir -Recurse -Force
    return $true
}

$repoRoot = Resolve-RepoRoot
$artifactsRoot = Join-Path $repoRoot "runner_artifacts"

if ([string]::IsNullOrWhiteSpace($RunPath)) {
    $RunPath = Resolve-LatestRun $artifactsRoot
}

if ([string]::IsNullOrWhiteSpace($RunPath) -or -not (Test-Path -LiteralPath $RunPath)) {
    throw "Run path not found. Provide -RunPath or ensure runner_artifacts has runs."
}

$resolvedRunPath = (Resolve-Path -LiteralPath $RunPath).Path
$runName = Split-Path -Leaf $resolvedRunPath

if ([string]::IsNullOrWhiteSpace($OutDir)) {
    $OutDir = $repoRoot
}
Ensure-Directory $OutDir
$resolvedOutDir = (Resolve-Path -LiteralPath $OutDir).Path

$zipName = "handoff_{0}.zip" -f $runName
$zipPath = Join-Path $resolvedOutDir $zipName

$stagingRoot = Join-Path $env:TEMP ("sbs_handoff_{0}" -f [guid]::NewGuid().ToString("N"))
Ensure-Directory $stagingRoot

try {
    Write-Info ("[package] run: {0}" -f $resolvedRunPath)
    Write-Info ("[package] staging: {0}" -f $stagingRoot)

    $metadataDir = Join-Path $resolvedRunPath "metadata"
    $eventsDir = Join-Path $resolvedRunPath "events"
    $inputsDir = Join-Path $resolvedRunPath "inputs"
    $logsDir = Join-Path $resolvedRunPath "logs"
    $screenshotsDir = Join-Path $resolvedRunPath "screenshots"

    $stageMetadata = Join-Path $stagingRoot "metadata"
    $stageEvents = Join-Path $stagingRoot "events"
    $stageInputs = Join-Path $stagingRoot "inputs"
    $stageLogs = Join-Path $stagingRoot "logs"
    $stageScreenshots = Join-Path $stagingRoot "screenshots"

    Ensure-Directory $stageMetadata
    Ensure-Directory $stageEvents
    Ensure-Directory $stageInputs
    Ensure-Directory $stageLogs
    Ensure-Directory $stageScreenshots

    Copy-IfExists (Join-Path $metadataDir "target_process.json") $stageMetadata | Out-Null
    Copy-IfExists (Join-Path $eventsDir "events.log") $stageEvents | Out-Null

    if (Test-Path -LiteralPath $inputsDir) {
        Copy-Item -LiteralPath $inputsDir\* -Destination $stageInputs -Recurse -Force
    }

    if (Test-Path -LiteralPath $logsDir) {
        Copy-Item -LiteralPath $logsDir\* -Destination $stageLogs -Recurse -Force
    }

    $rootFiles = @(
        "episode_payload.json",
        "episode_payload.jsonl",
        "episode_pending.json"
    )
    foreach ($filename in $rootFiles) {
        Copy-IfExists (Join-Path $resolvedRunPath $filename) $stagingRoot | Out-Null
    }

    $healthPath = Join-Path $inputsDir "health_observations.jsonl"
    if (Test-Path -LiteralPath $healthPath) {
        Copy-IfExists $healthPath $stageInputs | Out-Null
    }

    $reportPath = Join-Path $resolvedRunPath "report_last_run.md"
    if (-not (Test-Path -LiteralPath $reportPath)) {
        $globalReport = Join-Path $repoRoot "reports\report_last_run.md"
        if (Test-Path -LiteralPath $globalReport) {
            $reportPath = $globalReport
        }
    }
    if (Test-Path -LiteralPath $reportPath) {
        Copy-IfExists $reportPath $stagingRoot | Out-Null
    }

    if (Test-Path -LiteralPath $screenshotsDir) {
        $shots = Get-ChildItem -LiteralPath $screenshotsDir -File |
            Sort-Object Name
        if ($MaxScreenshots -eq 0) {
            $shots = @()
        } elseif ($MaxScreenshots -gt 0) {
            $shots = $shots | Select-Object -First $MaxScreenshots
        }
        foreach ($shot in $shots) {
            Copy-Item -LiteralPath $shot.FullName -Destination $stageScreenshots -Force
        }
    }

    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    Compress-Archive -Path (Join-Path $stagingRoot "*") -DestinationPath $zipPath -Force
    Write-Info ("[package] zip: {0}" -f $zipPath)

    if ($Open) {
        Start-Process -FilePath "explorer.exe" -ArgumentList "/select,`"$zipPath`""
    }
} finally {
    if (Test-Path -LiteralPath $stagingRoot) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
}
