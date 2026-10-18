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

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --console `
    --name "TempoHub-NetEase-Installer" `
    --add-data "$root\tools;tools" `
    --add-data "$root\payload;payload" `
    --add-data "$root\ui;ui" `
    --add-data "$root\scripts;scripts" `
    --add-data "$runtime;runtime39" `
    --hidden-import "PyInstaller.archive.readers" `
    --hidden-import "PyInstaller.archive.writers" `
    "$root\installer.py"
