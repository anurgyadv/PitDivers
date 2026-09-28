$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
Write-Host 'Room map: http://127.0.0.1:8766'
Write-Host 'Keep this terminal open while mapping. Ctrl+C stops the dashboard.'
uv run --with numpy --with scipy --no-project python mapping/dashboard.py --rover http://192.168.0.99
