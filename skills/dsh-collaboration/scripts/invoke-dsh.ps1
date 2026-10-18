param(
    [ValidateSet('doctor', 'network-check', 'run')][string]$Command = 'doctor',
    [string]$Workspace,
    [string]$TaskFile,
    [string]$ContinueFrom
)
$ErrorActionPreference = 'Stop'
$skillRoot = Split-Path $PSScriptRoot -Parent
$mapping = Join-Path $skillRoot 'bridge-location.json'
if (Test-Path -LiteralPath $mapping -PathType Leaf) {
    $location = Get-Content -LiteralPath $mapping -Raw | ConvertFrom-Json
    $bridgeRoot = [string]$location.bridge_root
} else {
    # Versioned source skill: installed mappings are local-only.
    $bridgeRoot = [System.IO.Path]::GetFullPath((Join-Path $skillRoot '..\..'))
}
if (-not [System.IO.Path]::IsPathRooted($bridgeRoot)) { throw 'The DSH bridge path must be absolute.' }
$python = Join-Path $bridgeRoot '.venv\Scripts\python.exe'
$bridge = Join-Path $bridgeRoot 'bridge.py'
foreach ($path in @($python, $bridge, (Join-Path $bridgeRoot 'safe-profile.patch.yml'))) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "No automatic reinstall or permission fallback. DSH installation is missing: $path." }
}
$arguments = @($bridge, $Command)
if ($Command -eq 'run') {
    if (-not $Workspace -or -not $TaskFile) { throw 'A paid run requires an explicit workspace and task contract.' }
    $contract = (Resolve-Path -LiteralPath $TaskFile -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath $contract -PathType Leaf)) { throw 'Task contract must be a file.' }
    $arguments += @('--workspace', $Workspace, '--task-file', $contract)
    if ($ContinueFrom) { $arguments += @('--continue-from', $ContinueFrom) }
}
# Preserve the caller's current directory/project. All bridge paths are absolute.
& $python @arguments
exit $LASTEXITCODE
