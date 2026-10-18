$ErrorActionPreference = "SilentlyContinue"

$appDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$tempoHub = Join-Path $appDir "EDIFIER TempoHub.exe"
$netease = "C:\Program Files\NetEase\CloudMusic\cloudmusic.exe"

function Test-LyricBridge {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $connection = $client.BeginConnect("127.0.0.1", 9222, $null, $null)
        if (-not $connection.AsyncWaitHandle.WaitOne(700)) {
            return $false
        }
        $client.EndConnect($connection)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

if (-not (Test-LyricBridge)) {
    $running = Get-Process -Name "cloudmusic" -ErrorAction SilentlyContinue
    if ($running) {
        $shell = New-Object -ComObject WScript.Shell
        $answer = $shell.Popup(
            "网易云音乐需要重启一次，才能向 TempoHub 提供精确播放进度。`n`n" +
            "现在重启网易云音乐吗？正在播放的歌曲会中断。",
            20,
            "网易云歌词同步",
            4 + 48
        )
        if ($answer -ne 6) {
            Start-Process -FilePath $tempoHub -WorkingDirectory $appDir
            return
        }
        $running | Stop-Process -Force
        Start-Sleep -Milliseconds 800
    }

    if (Test-Path -LiteralPath $netease) {
        Start-Process `
            -FilePath $netease `
            -ArgumentList "--remote-debugging-port=9222" `
            -WorkingDirectory (Split-Path -Parent $netease)
        for ($i = 0; $i -lt 20 -and -not (Test-LyricBridge); $i++) {
            Start-Sleep -Milliseconds 250
        }
    }
}

Start-Process -FilePath $tempoHub -WorkingDirectory $appDir
