#requires -version 5.1
<#
.SYNOPSIS
    启动 Mastery Lab 后端（FastAPI + Uvicorn）。
.DESCRIPTION
    自动创建虚拟环境、按 requirements.txt 安装/更新依赖、检查端口、后台启动并等待健康检查通过。
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start-api.ps1
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start-api.ps1 -Port 8000 -Reinstall
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$Reinstall
)

$ErrorActionPreference = 'Stop'
# 中文输出交给控制台自身编码处理（脚本为 UTF-8 BOM，GBK 控制台下也能正常显示）

$root = Split-Path -Parent $PSScriptRoot
$apiDir = Join-Path $root 'apps\api'
$dataDir = if ($env:MASTERY_LAB_DATA_DIR) { $env:MASTERY_LAB_DATA_DIR } else { Join-Path $root 'data' }
$runDir = Join-Path $dataDir 'run'
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

$pidFile = Join-Path $runDir 'api.pid'
$logFile = Join-Path $runDir 'api.log'
$errFile = Join-Path $runDir 'api.err.log'

function Fail([string]$Message) {
    Write-Host "[失败] $Message" -ForegroundColor Red
    exit 1
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Fail '未找到 python 命令。请先安装 Python 3.11+ 并加入 PATH。'
}

# ---- 1. 虚拟环境 ----
$venvPython = Join-Path $apiDir '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Host '[1/4] 创建虚拟环境 apps\api\.venv ...' -ForegroundColor Cyan
    Push-Location $apiDir
    try { & python -m venv .venv } finally { Pop-Location }
    if (-not (Test-Path $venvPython)) { Fail '虚拟环境创建失败，请检查 Python 安装是否完整。' }
    $Reinstall = $true
}
else {
    Write-Host '[1/4] 虚拟环境已存在。' -ForegroundColor DarkGray
}

# ---- 2. 依赖 ----
$requirements = Join-Path $apiDir 'requirements.txt'
$hashFile = Join-Path $runDir 'api-deps.hash'
$currentHash = (Get-FileHash $requirements -Algorithm SHA256).Hash
$needInstall = $Reinstall -or -not (Test-Path $hashFile) -or ((Get-Content $hashFile -Raw).Trim() -ne $currentHash)

if ($needInstall) {
    Write-Host '[2/4] 安装后端依赖（首次或 requirements.txt 有变化）...' -ForegroundColor Cyan
    Push-Location $apiDir
    try {
        & $venvPython -m pip install --disable-pip-version-check -q -r requirements.txt
        if ($LASTEXITCODE -ne 0) { Fail '依赖安装失败，请检查网络或 pip 配置。' }
    }
    finally { Pop-Location }
    $currentHash | Set-Content -Path $hashFile -Encoding ASCII
}
else {
    Write-Host '[2/4] 依赖已是最新。' -ForegroundColor DarkGray
}

# ---- 3. 端口 ----
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener -or $Port -in [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners().Port) {
    $owner = ($listener | Select-Object -First 1).OwningProcess
    $hint = if (Test-Path $pidFile) { "（记录的 PID 为 $(Get-Content $pidFile)，可执行 scripts\stop.ps1 停止）" } else { '' }
    Fail "端口 $Port 已被 PID=$owner 占用$hint。"
}

# ---- 4. 启动 ----
Write-Host "[3/4] 启动后端 http://127.0.0.1:$Port ..." -ForegroundColor Cyan
$env:MASTERY_LAB_PORT = [string]$Port
$childId = & python (Join-Path $PSScriptRoot 'launch-local.py') $apiDir $logFile $errFile $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port $Port
if ($LASTEXITCODE -ne 0 -or !$childId) { Fail '无法创建服务进程。' }
$proc = Get-Process -Id $childId
$proc.StartTime.ToUniversalTime().Ticks | Set-Content -LiteralPath "$pidFile.started" -Encoding ASCII

$proc.Id | Set-Content -Path $pidFile -Encoding ASCII

# 等待健康检查（最长 60 秒）
$healthy = $false
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Milliseconds 500
    if ($proc.HasExited) { break }
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/v1/health" -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    }
    catch { }
}

Write-Host '[4/4] 检查服务状态 ...' -ForegroundColor Cyan
if ($healthy) {
    Write-Host ''
    Write-Host "后端已就绪  PID=$($proc.Id)" -ForegroundColor Green
    Write-Host "  API      http://127.0.0.1:$Port/api/v1"
    Write-Host "  文档     http://127.0.0.1:$Port/docs"
    Write-Host "  日志     $logFile"
    Write-Host "  错误日志 $errFile"
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
