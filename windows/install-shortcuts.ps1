# Put "Endless On" and "Endless OFF" shortcuts on the desktop.
$desktop = [Environment]::GetFolderPath("Desktop")
$shell = New-Object -ComObject WScript.Shell
foreach ($s in @(@{ Name = "Endless On"; Script = "endless-on.ps1"; Icon = "endless-on.ico" },
                 @{ Name = "Endless OFF"; Script = "endless-off.ps1"; Icon = "endless-off.ico" })) {
    $lnk = $shell.CreateShortcut((Join-Path $desktop "$($s.Name).lnk"))
    $lnk.TargetPath = "powershell.exe"
    $lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$(Join-Path $PSScriptRoot $s.Script)`""
    $lnk.WorkingDirectory = Split-Path $PSScriptRoot -Parent
    $lnk.IconLocation = Join-Path $PSScriptRoot $s.Icon
    $lnk.Save()
    "Created $($s.Name) on $desktop"
}
