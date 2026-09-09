# チャットプローブ: SSE購読 → POST(debug:true) → done待ち → SSE保存
# 使い方: pwsh -File scripts\probe-chat.ps1 -Message "..." -Out probe1
param(
    [Parameter(Mandatory=$true)][string]$Message,
    [string]$Persona = "herta",
    [string]$Out = "probe",
    [int]$TimeoutSec = 180
)
$ErrorActionPreference = "Stop"
$dir = "$env:TEMP\opencode"
$evt = "$dir\$Out.events"
$body = "$dir\$Out.body.json"

if (Test-Path $evt) { Remove-Item $evt -Force }
Set-Content -Path $body -Value (@{message=$Message; debug=$true} | ConvertTo-Json -Compress) -Encoding utf8

# SSE 購読をバックグラウンド起動（バッファ・リプレイ last_seq=0 は過去ターンも拾うが debug_info は直近のみ有効）
$curl = Start-Process curl.exe -ArgumentList "-s","-N","-m","$TimeoutSec","http://localhost:26262/api/chat/$Persona/events?last_seq=0","-o",$evt -WindowStyle Hidden -PassThru
Start-Sleep 1

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$resp = curl.exe -s -X POST "http://localhost:26262/api/chat/$Persona" -H "Content-Type: application/json" --data-binary "@$body"
$sw.Stop()
Write-Host "POST: $resp ($([math]::Round($sw.Elapsed.TotalSeconds,1))s)"

# done を待つ
for ($i = 0; $i -lt $TimeoutSec; $i++) {
    Start-Sleep 1
    if (Test-Path $evt) {
        $txt = Get-Content $evt -Raw -ErrorAction SilentlyContinue
        if ($txt -match '"type":"done"' -or $txt -match '"type":"error"') { break }
    }
}
Stop-Process -Id $curl.Id -Force -ErrorAction SilentlyContinue
Write-Host "events: $evt ($((Get-Item $evt -ErrorAction SilentlyContinue).Length) bytes)"
