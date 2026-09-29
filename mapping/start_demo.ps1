$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$logDirectory = Join-Path $projectRoot 'data/demo'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
function Start-DemoService($port, $script, $extraArgs, $name) {
    try { Invoke-WebRequest "http://127.0.0.1:$port/" -TimeoutSec 2 -UseBasicParsing | Out-Null; return } catch {}
    Start-Process -FilePath 'python' -ArgumentList (@($script) + $extraArgs) -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory "$name-out.log") -RedirectStandardError (Join-Path $logDirectory "$name-error.log")
}
Start-DemoService 8767 'mapping/dashboard.py' @('--host','0.0.0.0','--rover','http://192.168.0.99','--port','8767') 'collector'
Start-DemoService 8768 'mapping/demo_server.py' @() 'demo'
Write-Host 'Open http://127.0.0.1:8768/ — scanning starts only when you press Start new room scan.'
