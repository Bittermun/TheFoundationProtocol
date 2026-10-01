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
    if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed." }
} else {
    Write-Host "Virtual environment already exists at $targetAbs." -ForegroundColor Green
}

$venvPython = "$targetAbs\Scripts\python.exe"

Write-Host "Upgrading pip, setuptools, wheel..." -ForegroundColor Yellow
& $venvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "Packaging tool installation failed." }

# Install from package metadata so CI and local agents share the same dependency contract.
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
Write-Host "Installing runtime, test, fuzz, browser and dev dependencies..." -ForegroundColor Yellow
& $venvPython -m pip install "$repoRoot[test,fuzz,browser,dev]"
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
& $venvPython -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw "Chromium installation failed." }

# Verify critical imports
Write-Host "Verifying environment imports..." -ForegroundColor Yellow
& $venvPython -c "import fastapi, pytest, ruff, mypy, bandit, httpx, numpy, scipy, playwright; print('Environment verified successfully!')"

if ($LASTEXITCODE -ne 0) { throw "Environment import verification failed." }

Write-Host "=== Agent Coding Environment is Ready ===" -ForegroundColor Green
Write-Host "Venv Python: $venvPython"
