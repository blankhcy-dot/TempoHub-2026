param(
    [Parameter(Mandatory = $true)]
    [string]$AppDir
)

$ErrorActionPreference = "Stop"
$appDirPath = (Resolve-Path -LiteralPath $AppDir).Path
$exe = Join-Path $appDirPath "EDIFIER TempoHub.exe"
$pythonw = Join-Path $appDirPath "runtime\pythonw.exe"
$launcher = Join-Path $appDirPath "launch_netease_lyrics.ps1"
$settings = Join-Path $appDirPath "lyrics_settings.py"

if (-not (Test-Path -LiteralPath $exe)) {
    throw "Patched TempoHub executable is missing."
}
if (-not (Test-Path -LiteralPath $pythonw)) {
    throw "Python runtime is missing."
}

$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath("Desktop")

$mainLink = Join-Path $desktop "EDIFIER TempoHub - 网易云歌词.lnk"
$main = $shell.CreateShortcut($mainLink)
$main.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$main.Arguments = (
    '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' +
    $launcher +
    '"'
)
$main.WorkingDirectory = $appDirPath
$main.IconLocation = "$exe,0"
$main.Description = "启动网易云精确同步和 EDIFIER TempoHub 歌词补丁"
$main.Save()

$settingsLink = Join-Path $desktop "EDIFIER TempoHub - 歌词显示设置.lnk"
$settingsShortcut = $shell.CreateShortcut($settingsLink)
$settingsShortcut.TargetPath = $pythonw
$settingsShortcut.Arguments = '"' + $settings + '"'
$settingsShortcut.WorkingDirectory = $appDirPath
$settingsShortcut.IconLocation = "$exe,0"
$settingsShortcut.Description = "Halo PixelBar 歌词控制台"
$settingsShortcut.Save()
