# Close every profile cleanly (logins and cookies saved), then stop the dashboard and ngrok.
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
python endlesschrome.py --stop-all
Pop-Location

Get-CimInstance Win32_Process -Filter "name like 'python%'" |
    Where-Object CommandLine -match 'endlesschrome\.py' |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Get-Process ngrok -ErrorAction SilentlyContinue | Stop-Process -Force
