param(
    [ValidateSet('doctor', 'network-check', 'run')][string]$Command = 'doctor',
    [string]$Workspace,
    [string]$TaskFile,
    [string]$ContinueFrom
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$bridge = Join-Path $PSScriptRoot 'bridge.py'
$arguments = @($bridge, $Command)
if ($Command -eq 'run') {
    if (-not $Workspace -or -not $TaskFile) { throw 'Run requires -Workspace and -TaskFile.' }
    $arguments += @('--workspace', $Workspace, '--task-file', $TaskFile)
    if ($ContinueFrom) { $arguments += @('--continue-from', $ContinueFrom) }
}
& $python @arguments
exit $LASTEXITCODE
