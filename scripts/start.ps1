# One-command dev start for Windows: API (uvicorn), job worker, and the frontend dev server.
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\start.ps1
# Stop:  Ctrl+C, or close the window (stops all three; background solver runs the worker already
#        launched keep going and are picked up again next time the worker starts, per CLAUDE.md
#        rule 14).
#
# Note: D-Flow FM and DualSPHysics in this project are run from WSL (docs/dflowfm_kernel_build.md,
# CLAUDE.md "Simulation tools"). This script only starts the API/worker/frontend dev loop; it does
# not require WSL unless you trigger a real M3/M4 solver run.

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

New-Item -ItemType Directory -Force -Path logs | Out-Null

if (-not (Test-Path .env)) {
    Write-Warning "No .env found - copying .env.example. Fill in real values before using GEE/OpenTopography."
    Copy-Item .env.example .env
}

# --- pick a Python for the API + worker ----------------------------------------------------------
$PythonCmd = $null
if ($env:SIH26_PYTHON) {
    $PythonCmd = $env:SIH26_PYTHON
} elseif (Get-Command conda -ErrorAction SilentlyContinue) {
    $envs = & conda env list
    if ($envs -match '^\s*sih26\s') {
        $PythonCmd = "conda run -n sih26 --no-capture-output python"
    }
}
if (-not $PythonCmd) {
    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $PythonCmd = $venvPython
    }
}
if (-not $PythonCmd) {
    Write-Error @"
No Python environment found. Create one first:
  conda env create -f environment.yml ; conda activate sih26
  # or: python -m venv .venv ; .venv\Scripts\pip install -r requirements.txt
"@
    exit 1
}

if (-not (Test-Path frontend\node_modules)) {
    Write-Host "Installing frontend dependencies (first run only)..."
    Push-Location frontend
    npm install
    Pop-Location
}

function Start-Logged($Name, $FilePath, $ArgumentList) {
    $log = "logs\$Name.log"
    return Start-Process -FilePath $FilePath -ArgumentList $ArgumentList `
        -NoNewWindow -PassThru `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err"
}

$pythonParts = $PythonCmd -split ' '
$pythonExe = $pythonParts[0]
if ($pythonParts.Length -gt 1) {
    $pythonBaseArgs = $pythonParts[1..($pythonParts.Length - 1)]
} else {
    $pythonBaseArgs = @()
}

Write-Host "Starting API on http://localhost:8000 (logs\api.log)..."
$apiProc = Start-Logged "api" $pythonExe ($pythonBaseArgs + @("-m", "uvicorn", "backend.m0_api.main:app", "--reload", "--port", "8000"))

Write-Host "Starting job worker (logs\worker.log)..."
$workerProc = Start-Logged "worker" $pythonExe ($pythonBaseArgs + @("-m", "backend.m0_api.worker"))

Write-Host "Starting frontend on http://localhost:5173 (logs\frontend.log)..."
$frontendProc = Start-Process -FilePath "npm" -ArgumentList @("run", "dev") -WorkingDirectory "$RepoRoot\frontend" `
    -NoNewWindow -PassThru `
    -RedirectStandardOutput "logs\frontend.log" -RedirectStandardError "logs\frontend.log.err"

Write-Host ""
Write-Host "All three are starting. Tail logs\*.log for progress."
Write-Host "  API health:  http://localhost:8000/api/v1/health"
Write-Host "  Frontend:    http://localhost:5173"
Write-Host "Press Ctrl+C to stop everything."

try {
    Wait-Process -Id $apiProc.Id, $workerProc.Id, $frontendProc.Id
} finally {
    Write-Host "Stopping API, worker, frontend..."
    foreach ($p in @($apiProc, $workerProc, $frontendProc)) {
        if ($p -and -not $p.HasExited) {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
