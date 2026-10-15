# Start EndlessChrome in the background and open the dashboard. Safe to run twice.
$root = Split-Path $PSScriptRoot -Parent
$port = 8790
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
    $m = Select-String -Path $envFile -Pattern '^\s*ENDLESS_PORT\s*=\s*(\d+)' | Select-Object -First 1
    if ($m) { $port = [int]$m.Matches[0].Groups[1].Value }
}

$running = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
if (-not $running) {
    New-Item -ItemType Directory -Force (Join-Path $root "data") | Out-Null
    Start-Process python -ArgumentList "endlesschrome.py" -WorkingDirectory $root -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $root "data\dashboard.log") -RedirectStandardError (Join-Path $root "data\dashboard.err.log")
    foreach ($i in 1..30) {
        Start-Sleep -Milliseconds 500
        if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { break }
    }
}

# Public tunnel only when asked for in .env (ENDLESS_NGROK=1) and ngrok is installed.
$wantNgrok = (Test-Path $envFile) -and (Select-String -Path $envFile -Pattern '^\s*ENDLESS_NGROK\s*=\s*1' -Quiet)
if ($wantNgrok -and (Get-Command ngrok -ErrorAction SilentlyContinue) -and -not (Get-Process ngrok -ErrorAction SilentlyContinue)) {
    Start-Process ngrok -ArgumentList "http $port" -WindowStyle Hidden
}

Start-Process "http://localhost:$port"
