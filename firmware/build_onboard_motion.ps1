param([switch]$Upload, [string]$Port)
$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
$sketch = Join-Path $PSScriptRoot 'SKETCHES/freenove_room_mapping'
$output = Join-Path $project 'data/build-onboard-motion'
$cli = Join-Path $env:LOCALAPPDATA 'Programs/Arduino IDE/resources/app/lib/backend/resources/arduino-cli.exe'
if (!(Test-Path -LiteralPath $cli)) {
    $cli = (Get-Command arduino-cli -ErrorAction Stop).Source
}
$config = Join-Path $env:USERPROFILE '.arduinoIDE/arduino-cli.yaml'
$fqbn = 'esp32:esp32:esp32s3:FlashSize=8M,PSRAM=opi'
if ($Upload -and [string]::IsNullOrWhiteSpace($Port)) { throw 'Supply -Port COMn when using -Upload' }
if (!(Test-Path -LiteralPath (Join-Path $sketch 'secrets.h'))) { throw 'The local secrets.h with Wi-Fi settings is missing' }
& $cli compile --config-file $config --fqbn $fqbn --output-dir $output $sketch
if ($LASTEXITCODE -ne 0) { throw 'Firmware build failed; nothing was flashed' }
$sources = Get-ChildItem -LiteralPath $sketch -File | Where-Object { $_.Name -ne 'secrets.h' }
$manifest = @{
    built_at = (Get-Date).ToString('o')
    fqbn = $fqbn
    protocol = 1
    sources = @($sources | ForEach-Object { @{name=$_.Name; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash} })
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $output 'build-manifest.json') -Encoding utf8
if ($Upload) {
    & $cli upload --config-file $config --fqbn $fqbn --port $Port --input-dir $output $sketch
    if ($LASTEXITCODE -ne 0) { throw 'Upload failed; check USB port and close Serial Monitor' }
    Write-Host 'Uploaded. Start LiDAR and run Calibrate turns before Go. Navigation never starts at boot.'
} else {
    Write-Host "Built firmware in $output. Nothing flashed and no motor commands sent."
}
