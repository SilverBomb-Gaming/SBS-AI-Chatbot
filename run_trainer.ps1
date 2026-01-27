$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPy = Join-Path $repo ".venv\\Scripts\\python.exe"

if (-not (Test-Path $venvPy)) {
  throw "Missing venv python at: $venvPy"
}

$env:PYTHONPATH = $repo

& $venvPy ".\\trainer.py" `
  --capture-mode window `
  --debug-hud `
  @args
