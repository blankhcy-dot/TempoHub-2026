$ErrorActionPreference = "Stop"
$appDir = (Resolve-Path -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Path)).Path
$resolved = [System.IO.Path]::GetFullPath($appDir)
$marker = Join-Path $resolved ".tempo-nexe-install"

if (-not (Test-Path -LiteralPath $marker)) {
    throw "Refusing to remove a directory without the TempoHub NetEase marker: $resolved"
}

Get-Process -Name "EDIFIER TempoHub" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($resolved, [StringComparison]::OrdinalIgnoreCase) } |
    Stop-Process -Force

$desktop = [Environment]::GetFolderPath("Desktop")
foreach ($name in @(
    "EDIFIER TempoHub - 网易云歌词.lnk",
    "EDIFIER TempoHub - 歌词显示设置.lnk"
)) {
    $shortcut = Join-Path $desktop $name
    if (Test-Path -LiteralPath $shortcut) {
        Remove-Item -LiteralPath $shortcut -Force
    }
}

$cleanup = (
    'Start-Sleep -Milliseconds 500; ' +
    'Remove-Item -LiteralPath "' + $resolved + '" -Recurse -Force'
)
Start-Process `
    -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -ArgumentList @("-NoProfile", "-WindowStyle", "Hidden", "-Command", $cleanup) `
    -WindowStyle Hidden

Write-Host "已移除歌词补丁和快捷方式。官方 TempoHub 未作修改。"
