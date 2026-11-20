$AppRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $AppRoot

# Exit codes are checked explicitly: PyInstaller logs to stderr, which "Stop" would treat as failure.
function Invoke-Step($exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "Step failed ($LASTEXITCODE): $exe $arguments" }
}

if (-not (Test-Path .\.venv\Scripts\python.exe)) { Invoke-Step py @('-3', '-m', 'venv', '.venv') }
Invoke-Step .\.venv\Scripts\python.exe @('-m', 'pip', 'install', '--upgrade', 'pip')
Invoke-Step .\.venv\Scripts\python.exe @('-m', 'pip', 'install', '--upgrade', '-r', 'requirements.txt', 'pyinstaller')
Invoke-Step .\.venv\Scripts\python.exe @('tools\make_icon.py')
Invoke-Step .\.venv\Scripts\pyinstaller.exe @('--noconfirm', '--clean', '--onefile', '--windowed',
    '--name', 'ClipAndSave', '--collect-all', 'yt_dlp', '--collect-all', 'yt_dlp_ejs',
    '--collect-all', 'imageio_ffmpeg', '--collect-all', 'PIL', '--collect-all', 'certifi',
    '--icon', 'assets\app.ico', '--add-data', 'assets;assets', '--add-data', 'licenses;licenses', 'app.py')

Write-Host "Built: $AppRoot\dist\ClipAndSave.exe"
