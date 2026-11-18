#requires -version 5.1
<#
.SYNOPSIS
    启动 Mastery Lab 前端（Vite + Vue 3）。
.DESCRIPTION
    首次运行会自动安装前端依赖；端口固定 5173，使用严格端口模式，冲突时直接报错而不是静默换端口。
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start-web.ps1
#>
[CmdletBinding()]
param(
    [ValidateRange(1,65535)][int]$Port = 5173,
    [ValidateRange(1,65535)][int]$ApiPort = 8000
)

$ErrorActionPreference = 'Stop'
# 中文输出交给控制台自身编码处理（脚本为 UTF-8 BOM，GBK 控制台下也能正常显示）

$root = Split-Path -Parent $PSScriptRoot
$webDir = Join-Path $root 'apps\web'
$dataDir = if ($env:MASTERY_LAB_DATA_DIR) { $env:MASTERY_LAB_DATA_DIR } else { Join-Path $root 'data' }
$runDir = Join-Path $dataDir 'run'
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

$pidFile = Join-Path $runDir 'web.pid'
$logFile = Join-Path $runDir 'web.log'
$errFile = Join-Path $runDir 'web.err.log'

function Fail([string]$Message) {
    Write-Host "[失败] $Message" -ForegroundColor Red
    exit 1
}

$nodeExe = (Get-Command node -ErrorAction SilentlyContinue).Source
if (-not $nodeExe) { Fail '未找到 node 命令。请先安装 Node.js 18+ 并加入 PATH。' }

$pnpm = (Get-Command pnpm -ErrorAction SilentlyContinue).Source
$npm = (Get-Command npm -ErrorAction SilentlyContinue).Source
if (-not $pnpm -and -not $npm) { Fail '未找到 pnpm / npm，请安装其中之一。' }

# ---- 1. 依赖 ----
$nodeModules = Join-Path $webDir 'node_modules'
if (-not (Test-Path $nodeModules)) {
    $manager = if ($pnpm) { 'pnpm' } else { 'npm' }
    Write-Host "[1/3] 首次运行，使用 $manager 安装前端依赖（可能需要几分钟）..." -ForegroundColor Cyan
    Push-Location $webDir
    try {
        if ($pnpm) { & pnpm install } else { & npm install }
        if ($LASTEXITCODE -ne 0) { Fail '前端依赖安装失败，请检查网络或 npm 源配置。' }
    }
    finally { Pop-Location }
}
else {
    Write-Host '[1/3] 前端依赖已存在。' -ForegroundColor DarkGray
}

# ---- 2. 端口 ----
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener -or $Port -in [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners().Port) {
    $owner = ($listener | Select-Object -First 1).OwningProcess
    $hint = if (Test-Path $pidFile) { "（记录的 PID 为 $(Get-Content $pidFile)，可执行 scripts\stop.ps1 停止）" } else { '' }
    Fail "端口 $Port 已被 PID=$owner 占用$hint。"
}

# ---- 3. 启动 ----
$viteBin = Join-Path $webDir 'node_modules\vite\bin\vite.js'
if (-not (Test-Path $viteBin)) { Fail "找不到 Vite（$viteBin），请删除 apps\web\node_modules 后重试。" }

Write-Host "[2/3] 启动前端 http://127.0.0.1:$Port ..." -ForegroundColor Cyan
$env:MASTERY_LAB_PROXY_PORT = [string]$ApiPort
$childId = & python (Join-Path $PSScriptRoot 'launch-local.py') $webDir $logFile $errFile $nodeExe $viteBin --host 127.0.0.1 --port $Port --strictPort
if ($LASTEXITCODE -ne 0 -or !$childId) { Fail '无法创建服务进程。' }
$proc = Get-Process -Id $childId
$proc.StartTime.ToUniversalTime().Ticks | Set-Content -LiteralPath "$pidFile.started" -Encoding ASCII

$proc.Id | Set-Content -Path $pidFile -Encoding ASCII

$ready = $false
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Milliseconds 500
    if ($proc.HasExited) { break }
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -eq 200) { $ready = $true; break }
    }
    catch { }
}

Write-Host '[3/3] 检查页面状态 ...' -ForegroundColor Cyan
if ($ready) {
    Write-Host ''
    Write-Host "前端已就绪  PID=$($proc.Id)" -ForegroundColor Green
    Write-Host "  页面     http://127.0.0.1:$Port/"
    Write-Host "  日志     $logFile"
    exit 0
}

Write-Host '启动失败，下面是最近的输出：' -ForegroundColor Red
foreach ($file in @($errFile, $logFile)) {
    if (Test-Path $file) {
        Write-Host "--- $file ---" -ForegroundColor Yellow
        Get-Content $file -Tail 25
    }
}
if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
Remove-Item $pidFile -ErrorAction SilentlyContinue
exit 1
