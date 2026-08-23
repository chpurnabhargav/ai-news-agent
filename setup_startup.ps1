$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = (Get-Command python).Source
$Pythonw = Join-Path (Split-Path $Python) "pythonw.exe"

$StartupDir = [Environment]::GetFolderPath("Startup")
$Desktop = [Environment]::GetFolderPath("Desktop")

$ws = New-Object -ComObject WScript.Shell

$startupShortcut = $ws.CreateShortcut((Join-Path $StartupDir "AI News Agent.lnk"))
$startupShortcut.TargetPath = $Pythonw
$startupShortcut.Arguments = "`"$ProjectDir\watcher.py`""
$startupShortcut.WorkingDirectory = $ProjectDir
$startupShortcut.Description = "AI News Agent watcher - fetches latest AI news once per day when internet is available"
$startupShortcut.Save()

$desktopShortcut = $ws.CreateShortcut((Join-Path $Desktop "AI News Agent.lnk"))
$desktopShortcut.TargetPath = $Pythonw
$desktopShortcut.Arguments = "`"$ProjectDir\app.py`""
$desktopShortcut.WorkingDirectory = $ProjectDir
$desktopShortcut.Description = "Open AI News Agent"
$desktopShortcut.Save()

Write-Host "Created:"
Write-Host "  Desktop shortcut -> $Desktop\AI News Agent.lnk"
Write-Host "  Startup watcher  -> $StartupDir\AI News Agent.lnk"
