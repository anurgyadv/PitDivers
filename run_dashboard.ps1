$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectPython = Join-Path $projectRoot "vision\.venv\Scripts\python.exe"
$userProfilePath = [Environment]::GetFolderPath("UserProfile")
$bundledPython = Join-Path $userProfilePath ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$pythonExecutable = $null

foreach ($candidatePath in @($projectPython, $bundledPython)) {
    if (Test-Path -LiteralPath $candidatePath) {
        & $candidatePath --version 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $pythonExecutable = $candidatePath
            break
        }
    }
}

if ($null -eq $pythonExecutable) {
    Write-Host "No working Python 3.12 runtime was found." -ForegroundColor Red
    Write-Host "Expected the project environment or Codex bundled runtime."
    Read-Host "Press Enter to close"
    exit 1
}

Set-Location -LiteralPath $projectRoot
& $pythonExecutable (Join-Path $projectRoot "webapp\bootstrap.py")

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "The dashboard stopped with an error." -ForegroundColor Red
    Read-Host "Press Enter to close"
}
