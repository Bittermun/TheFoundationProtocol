# SPDX-License-Identifier: Apache-2.0
param(
    [string]$TargetDir = ".dist_verify/runtime"
)

$ErrorActionPreference = "Stop"

Write-Host "=== Bootstrapping Agent Coding Environment for TheFoundationProtocol ===" -ForegroundColor Cyan

# Locate Python 3.11+
$candidatePaths = @(
    $env:PYTHON_EXECUTABLE,
    "C:\Users\msunw\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
)

$basePython = $null
foreach ($path in $candidatePaths) {
    if ($path -and (Test-Path $path)) {
        $basePython = $path
        break
    }
}

if (-not $basePython) {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch "WindowsApps") {
        $basePython = $cmd.Source
    }
}

if (-not $basePython) {
    Write-Error "Could not find a valid base Python (3.11+) executable."
}

Write-Host "Using Base Python: $basePython" -ForegroundColor Green
& $basePython --version

# Create virtualenv inside gitignored .dist_verify
$targetAbs = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($TargetDir)
if (-not (Test-Path "$targetAbs\Scripts\python.exe")) {
    Write-Host "Creating virtual environment at $targetAbs..." -ForegroundColor Yellow
    $parentDir = Split-Path $targetAbs
    if (-not (Test-Path $parentDir)) {
        New-Item -ItemType Directory -Force -Path $parentDir | Out-Null
    }
    & $basePython -m venv $targetAbs
} else {
    Write-Host "Virtual environment already exists at $targetAbs." -ForegroundColor Green
}

$venvPython = "$targetAbs\Scripts\python.exe"

Write-Host "Upgrading pip, setuptools, wheel..." -ForegroundColor Yellow
& $venvPython -m pip install --upgrade pip setuptools wheel

Write-Host "Installing production dependencies from requirements.txt..." -ForegroundColor Yellow
& $venvPython -m pip install -r requirements.txt

Write-Host "Installing testing & dev tooling..." -ForegroundColor Yellow
& $venvPython -m pip install pytest pytest-asyncio pytest-timeout httpx fakeredis hypothesis ruff mypy bandit black build

# Verify critical imports
Write-Host "Verifying environment imports..." -ForegroundColor Yellow
& $venvPython -c "import fastapi, pytest, ruff, mypy, bandit, httpx; print('Environment verified successfully!')"

Write-Host "=== Agent Coding Environment is Ready ===" -ForegroundColor Green
Write-Host "Venv Python: $venvPython"
