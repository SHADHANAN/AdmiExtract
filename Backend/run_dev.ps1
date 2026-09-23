<#
.SYNOPSIS
    AdmiExtract Safe PowerShell Backend Starter
.DESCRIPTION
    Launches or restarts the backend on 0.0.0.0:8000 safely without Errno 10048.
.PARAMETER Restart
    Restart the backend if already running.
.PARAMETER Status
    Check status of backend on port 8000.
#>
param (
    [switch]$Restart,
    [switch]$Status
)

$PSScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$python = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

$script = Join-Path $PSScriptRoot "run_backend.py"

$argsList = @()
if ($Restart) { $argsList += "--restart" }
if ($Status)  { $argsList += "--status" }

& $python $script @argsList
