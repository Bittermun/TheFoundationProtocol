<#
.SYNOPSIS
    Runs The Foundation Protocol disposable verification lab inside an isolated Docker sandbox.
.DESCRIPTION
    Uses docker-compose.disposable.yml to execute tests on tmpfs RAM mounts without polluting host files or databases.
#>
[CmdletBinding()]
param(
    [string]$Scenario = "all",
    [switch]$Preserve
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

Push-Location $RepoRoot
try {
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  The Foundation Protocol: Disposable Verification Sandbox" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  Scenario : $Scenario"
    Write-Host "  Mounts   : Read-only code, tmpfs RAM database (/tmp)"
    Write-Host "============================================================" -ForegroundColor Cyan

    $cmd = @("compose", "-f", "docker-compose.disposable.yml", "run", "--rm", "disposable-lab", "python", "scripts/run_experiment.py", "--scenario", $Scenario)
    if ($Preserve) {
        $cmd += "--preserve"
    }

    & docker $cmd
}
finally {
    Pop-Location
}
