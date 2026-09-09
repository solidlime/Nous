# nous サーバー再起動スクリプト
# 使い方: pwsh -File scripts\restart-nous.ps1
param(
    [string]$Workdir = "D:\Code\Nous",
    [int]$Port = 26262,
    [int]$LogSerial = 16  # ログ世代番号（srv<N>.out.log）
)

$ErrorActionPreference = "Stop"
$out = "$env:TEMP\opencode\nous_srv$LogSerial.out.log"
$err = "$env:TEMP\opencode\nous_srv$LogSerial.err.log"

# 既存プロセス停止
$conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    $conn | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
        Write-Host "Stopping PID $_"
        Stop-Process -Id $_ -Force
    }
    Start-Sleep 1
}

# 起動
$p = Start-Process -FilePath "C:\Python\Python312\python.exe" `
    -ArgumentList "-m", "nous.main" `
    -WorkingDirectory $Workdir `
    -NoNewWindow -PassThru `
    -RedirectStandardOutput $out -RedirectStandardError $err
Write-Host "Started PID $($p.Id) (logs: srv$LogSerial)"

# READY ポーリング（モデル読み込み時間を見て最大60秒）
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep 1
    try {
        $r = Invoke-WebRequest "http://localhost:$Port/" -UseBasicParsing -TimeoutSec 3
        Write-Host "READY ($($r.StatusCode)) after $($i+1)s"
        exit 0
    } catch { }
}
Write-Host "NOT READY after 60s. Last log lines:"
Get-Content $err -Tail 30
exit 1
