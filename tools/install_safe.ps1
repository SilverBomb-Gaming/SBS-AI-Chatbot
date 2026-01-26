Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "[install] upgrading pip"
python -m pip install --upgrade pip

Write-Host "[install] installing requirements (wheels only)"
python -m pip install --only-binary=:all: -r requirements.txt
