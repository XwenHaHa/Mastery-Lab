#requires -version 5.1
<#
.SYNOPSIS
    一键启动 Mastery Lab（后端 + 前端）。
.DESCRIPTION
    依次执行环境检查、启动后端、启动前端，最后输出访问地址。任一环节失败立即停止并给出原因。
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -Open
#>
[CmdletBinding()]
param(
    [switch]$Open,
    [switch]$SkipEnvCheck,
    [ValidateRange(1,65535)][int]$ApiPort = 8000,
    [ValidateRange(1,65535)][int]$WebPort = 5173
)

$ErrorActionPreference = 'Stop'
# 中文输出交给控制台自身编码处理（脚本为 UTF-8 BOM，GBK 控制台下也能正常显示）

$scriptsDir = $PSScriptRoot
$root = Split-Path -Parent $scriptsDir

Write-Host ''
Write-Host '==============================================' -ForegroundColor Cyan
Write-Host ' Mastery Lab 启动' -ForegroundColor Cyan
Write-Host '==============================================' -ForegroundColor Cyan

if (-not $SkipEnvCheck) {
    & (Join-Path $scriptsDir 'check-env.ps1') -ApiPort $ApiPort -WebPort $WebPort
    if ($LASTEXITCODE -ne 0) {
        Write-Host '环境检查未通过，已中止启动。' -ForegroundColor Red
        exit 1
    }
}

Write-Host ''
& (Join-Path $scriptsDir 'start-api.ps1') -Port $ApiPort
if ($LASTEXITCODE -ne 0) {
    Write-Host '后端启动失败，已中止（前端未启动）。' -ForegroundColor Red
    exit 1
}

Write-Host ''
& (Join-Path $scriptsDir 'start-web.ps1') -Port $WebPort -ApiPort $ApiPort
if ($LASTEXITCODE -ne 0) {
    Write-Host '前端启动失败，后端仍在运行，可执行 scripts\stop.ps1 清理。' -ForegroundColor Red
    exit 1
}

Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' Mastery Lab 已启动' -ForegroundColor Green
Write-Host "   页面      http://127.0.0.1:$WebPort/" -ForegroundColor Green
Write-Host "   API 文档  http://127.0.0.1:$ApiPort/docs" -ForegroundColor Green
Write-Host '   日志      数据目录下的 run\api.log / web.log' -ForegroundColor Green
Write-Host '   停止      scripts\stop.ps1' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green

if ($Open) { Start-Process "http://127.0.0.1:$WebPort/" }
exit 0
