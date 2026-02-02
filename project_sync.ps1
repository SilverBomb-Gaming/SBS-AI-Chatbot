param(
    [Parameter(ParameterSetName = 'Transfer', Mandatory = $true)]
    [ValidateSet('BabylonToAIE', 'AIEToBabylon')]
    [string]$Direction,

    [Parameter(ParameterSetName = 'Transfer', Mandatory = $true)]
    [string[]]$RelativePaths,

    [Parameter(ParameterSetName = 'Transfer')]
    [switch]$Copy,

    [Parameter(ParameterSetName = 'Mirror', Mandatory = $true)]
    [switch]$Mirror,

    [Parameter(ParameterSetName = 'Mirror')]
    [ValidateSet('BabylonToAIE')]
    [string]$MirrorDirection = 'BabylonToAIE',

    [Parameter(ParameterSetName = 'Mirror')]
    [string]$MirrorRoot = 'Assets',

    [Parameter(ParameterSetName = 'Transfer')]
    [Parameter(ParameterSetName = 'Mirror')]
    [switch]$DryRun,

    [Parameter(ParameterSetName = 'Transfer')]
    [Parameter(ParameterSetName = 'Mirror')]
    [string]$BabylonRoot = "E:\AI projects 2025\BABYLON VER 2",

    [Parameter(ParameterSetName = 'Transfer')]
    [Parameter(ParameterSetName = 'Mirror')]
    [string]$AIEHarnessRoot = "E:\Documents old and new\Documents 2026\SBS-AI-Chatbot\AIE-TestHarness\TestHarness"
)

$allowedPrefixes = @(
    'Assets\Scripts',
    'Assets\Resources',
    'Assets\Settings'
)

function Normalize-RelativePath {
    param([string]$Path)

    $normalized = $Path -replace '/', '\'
    $normalized = $normalized.TrimStart('\')
    return $normalized
}

function Validate-AllowedPrefix {
    param([string]$NormalizedPath)

    foreach ($prefix in $allowedPrefixes) {
        if ($NormalizedPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }

    Write-Warning "Path '$NormalizedPath' is outside allowed prefixes: $($allowedPrefixes -join ', ')"
    return $false
}

if (-not (Test-Path $BabylonRoot)) {
    throw "Babylon root not found: $BabylonRoot"
}

if (-not (Test-Path $AIEHarnessRoot)) {
    throw "AIE harness root not found: $AIEHarnessRoot"
}

switch ($PSCmdlet.ParameterSetName) {
    'Mirror' { Invoke-MirrorSync; break }
    default   { Invoke-FileTransfer; break }
}

function Invoke-FileTransfer {
    $sourceRoot = if ($Direction -eq 'BabylonToAIE') { $BabylonRoot } else { $AIEHarnessRoot }
    $destRoot = if ($Direction -eq 'BabylonToAIE') { $AIEHarnessRoot } else { $BabylonRoot }

    Write-Host "Project Sync" -ForegroundColor Cyan
    Write-Host " Direction : $Direction"
    Write-Host " Source    : $sourceRoot"
    Write-Host " Destination: $destRoot"
    Write-Host " Mode      : $(if ($Copy) { 'Copy' } else { 'Move' }) $(if ($DryRun) { '(Dry Run)' })"

    foreach ($path in $RelativePaths) {
        $normalized = Normalize-RelativePath -Path $path
        if (-not (Validate-AllowedPrefix -NormalizedPath $normalized)) {
            continue
        }

        $sourceFile = Join-Path $sourceRoot $normalized
        $destFile = Join-Path $destRoot $normalized

        if (-not (Test-Path $sourceFile)) {
            Write-Warning "Source missing: $sourceFile"
            continue
        }

        $destDir = Split-Path $destFile -Parent
        if (-not $DryRun -and -not (Test-Path $destDir)) {
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        }

        if ($DryRun) {
            Write-Host "[DRY RUN] Would $(if ($Copy) { 'copy' } else { 'move' }) '$sourceFile' -> '$destFile'"
            continue
        }

        if ($Copy) {
            Copy-Item -Path $sourceFile -Destination $destFile -Force
        }
        else {
            Move-Item -Path $sourceFile -Destination $destFile -Force
        }

        if (Test-Path $destFile) {
            $size = (Get-Item $destFile).Length
            Write-Host "Transferred '$normalized' ($size bytes)"
        }
        else {
            Write-Warning "Destination missing after transfer: $destFile"
        }
    }
}

function Invoke-MirrorSync {
    if ($MirrorDirection -ne 'BabylonToAIE') {
        throw "Mirror mode only supports BabylonToAIE."
    }

    $sourcePath = Join-Path $BabylonRoot $MirrorRoot
    $destPath = Join-Path $AIEHarnessRoot $MirrorRoot

    if (-not (Test-Path $sourcePath)) {
        throw "Mirror source missing: $sourcePath"
    }

    if (-not (Test-Path (Split-Path $destPath -Parent))) {
        New-Item -ItemType Directory -Path (Split-Path $destPath -Parent) -Force | Out-Null
    }

    Write-Host "Project Mirror" -ForegroundColor Cyan
    Write-Host " Source      : $sourcePath"
    Write-Host " Destination : $destPath"
    Write-Host " Dry Run     : $DryRun"

    $excludeDirs = @('Library', 'Temp', 'Logs', 'UserSettings', 'obj', 'Build', 'Builds', '.git', '.vs')
    $roboArgs = @(
        $sourcePath,
        $destPath,
        '/MIR',
        '/COPY:DAT',
        '/R:2',
        '/W:2',
        '/NFL',
        '/NDL',
        '/NJH',
        '/NJS',
        '/NP'
    )

    foreach ($dir in $excludeDirs) {
        $roboArgs += '/XD'
        $roboArgs += (Join-Path $BabylonRoot $dir)
    }

    if ($DryRun) {
        $roboArgs += '/L'
        Write-Host "Running robocopy in dry-run mode..."
    }
    else {
        Write-Host "Mirroring files..."
    }

    & robocopy @roboArgs | Write-Host
    $exitCode = $LASTEXITCODE

    if ($exitCode -lt 8) {
        Write-Host "Mirror completed with robocopy code $exitCode" -ForegroundColor Green
    }
    else {
        Write-Warning "Robocopy reported error code $exitCode"
    }
}
