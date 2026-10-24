param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$runtime = Join-Path $root "runtime39"
$archive = Join-Path $root "python-3.9.13-embed-amd64.zip"

if (-not (Test-Path -LiteralPath $runtime)) {
    if (-not (Test-Path -LiteralPath $archive)) {
        Invoke-WebRequest `
            -Uri "https://www.python.org/ftp/python/3.9.13/python-3.9.13-embed-amd64.zip" `
            -OutFile $archive
    }
    Expand-Archive -LiteralPath $archive -DestinationPath $runtime
}

& (Join-Path $runtime "python.exe") (Join-Path $root "scripts\compile_payload.py")
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.9 payload compilation failed."
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --console `
    --name "TempoHub-NetEase-Installer" `
    --add-data "$root\tools\patch_temphub.py;tools" `
    --add-data "$root\payload;payload" `
    --add-data "$root\ui\lyrics_settings.py;ui" `
    --add-data "$root\scripts\create_shortcuts.ps1;scripts" `
    --add-data "$root\scripts\launch_netease_lyrics.ps1;scripts" `
    --add-data "$root\scripts\uninstall.ps1;scripts" `
    --add-data "$runtime;runtime39" `
    --hidden-import "PyInstaller.archive.readers" `
    --hidden-import "PyInstaller.archive.writers" `
    "$root\installer.py"
if ($LASTEXITCODE -ne 0) {
    throw "Installer build failed."
}
