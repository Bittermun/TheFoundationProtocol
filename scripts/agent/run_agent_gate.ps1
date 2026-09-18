# SPDX-License-Identifier: Apache-2.0
param(
    [switch]$FullSuite,
    [string]$TargetDir = ".dist_verify/runtime"
)

$ErrorActionPreference = "Stop"
$targetAbs = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($TargetDir)
$venvPython = "$targetAbs\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Error "Runtime python not found at $venvPython. Run bootstrap_env.ps1 first."
}

Write-Host "=== Running Agent Quality & Safety Gate ===" -ForegroundColor Cyan

# 1. Whole-Repo Ruff Check (aligns with repository style rules and excludes unmigrated mockup trees)
Write-Host "`n[1/4] Running Ruff..." -ForegroundColor Yellow
& $venvPython -m ruff check --select E4,E7,E9,F --ignore E731 --exclude "build,dist,.dist_verify,tfp_ui,tfp_testbed,tfp_simulator" .
if ($LASTEXITCODE -ne 0) {
    Write-Error "Ruff check failed."
}

# 2. Configured Mypy on source files (verifying all 172 source files)
Write-Host "`n[2/4] Running Mypy on source packages..." -ForegroundColor Yellow
& $venvPython -m mypy tfp-foundation-protocol --ignore-missing-imports
if ($LASTEXITCODE -ne 0) {
    Write-Error "Mypy type check failed."
}

# 3. Bandit security audit (matching repo bandit.ini)
Write-Host "`n[3/4] Running Bandit security audit..." -ForegroundColor Yellow
& $venvPython -m bandit -c bandit.ini -r tfp-foundation-protocol -x tfp-foundation-protocol/build -ll
if ($LASTEXITCODE -ne 0) {
    Write-Error "Bandit scan found medium/high severity issues."
}

# 4. Pytest Suite
Write-Host "`n[4/4] Running Reliability Tests..." -ForegroundColor Yellow
if ($FullSuite) {
    & $venvPython -m pytest -q --tb=short --timeout=30
} else {
    & $venvPython -m pytest tests/test_demo_reliability.py tests/test_tooling_isolation.py -q --tb=short --timeout=30
}

if ($LASTEXITCODE -ne 0) {
    Write-Error "Pytest suite failed."
}

Write-Host "`n=== All Quality & Safety Gates Passed ===" -ForegroundColor Green
