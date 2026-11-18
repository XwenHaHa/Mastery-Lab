#requires -version 5.1
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dataDir = if ($env:MASTERY_LAB_DATA_DIR) { $env:MASTERY_LAB_DATA_DIR } else { Join-Path $root 'data' }
$runDir = Join-Path $dataDir 'run'
$failed = $false
foreach ($name in 'api','web') {
    $record = Join-Path $runDir "$name.pid"
    if (!(Test-Path -LiteralPath $record)) { Write-Host "[跳过] $name 无启动记录。"; continue }
    $started = "$record.started"
    $childId = 0
    if (![int]::TryParse((Get-Content -LiteralPath $record -Raw).Trim(), [ref]$childId) -or $childId -le 0) {
        Write-Warning "$name PID 记录无效，未结束进程。"; $failed = $true; continue
    }
    $proc = Get-Process -Id $childId -ErrorAction SilentlyContinue
    if ($proc) {
        if (!(Test-Path -LiteralPath $started) -or [string]$proc.StartTime.ToUniversalTime().Ticks -ne (Get-Content -LiteralPath $started -Raw).Trim()) {
            Write-Warning "$name 无法确认 PID=$childId 的归属，未结束进程。"; $failed = $true; continue
        }
        & taskkill.exe /PID $childId /T /F
        if ($LASTEXITCODE -ne 0) { Write-Warning "$name 未成功停止。"; $failed = $true; continue }
        Write-Host "[已停止] $name PID=$childId"
    } else { Write-Host "[已退出] $name PID=$childId" }
    Remove-Item -LiteralPath $record
    if (Test-Path -LiteralPath $started) { Remove-Item -LiteralPath $started }
}
if ($failed) { exit 1 }
exit 0
