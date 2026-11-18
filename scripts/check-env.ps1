#requires -version 5.1
<#
.SYNOPSIS
    检查 Mastery Lab 的运行环境（Node.js / pnpm / Python / Git / 端口 / 依赖）。
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\check-env.ps1
#>
[CmdletBinding()]
param([int]$ApiPort = 8000, [int]$WebPort = 5173)

$ErrorActionPreference = 'Stop'
# 中文输出交给控制台自身编码处理（脚本为 UTF-8 BOM，GBK 控制台下也能正常显示）

$root = Split-Path -Parent $PSScriptRoot
$apiDir = Join-Path $root 'apps\api'
$webDir = Join-Path $root 'apps\web'
$problems = New-Object System.Collections.Generic.List[string]

function Write-Check {
    param([string]$Name, [bool]$Ok, [string]$Detail)
    $mark = if ($Ok) { '[ OK ]' } else { '[FAIL]' }
    Write-Host ("{0} {1,-14} {2}" -f $mark, $Name, $Detail)
}

Write-Host ''
Write-Host 'Mastery Lab 环境检查' -ForegroundColor Cyan
Write-Host ('-' * 60)

# ---- 工具链 ----
$nodePath = (Get-Command node -ErrorAction SilentlyContinue).Source
$nodeVersion = if ($nodePath) { (& node -v) } else { '' }
Write-Check 'Node.js' ([bool]$nodePath) ($(if ($nodePath) { "$nodeVersion  $nodePath" } else { '未安装，请安装 Node.js 18+' }))
if (-not $nodePath) { $problems.Add('缺少 Node.js') }

$pnpmPath = (Get-Command pnpm -ErrorAction SilentlyContinue).Source
$npmPath = (Get-Command npm -ErrorAction SilentlyContinue).Source
$pkgManager = if ($pnpmPath) { 'pnpm' } elseif ($npmPath) { 'npm' } else { '' }
Write-Check '包管理器' ([bool]$pkgManager) ($(if ($pnpmPath) { "pnpm $(& pnpm -v)" } elseif ($npmPath) { "npm $(& npm -v)（也可以，脚本会退回 npm）" } else { '未安装 pnpm / npm' }))
if (-not $pkgManager) { $problems.Add('缺少包管理器') }

$pythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
$pythonVersion = if ($pythonPath) { (& python --version 2>&1) } else { '' }
Write-Check 'Python' ([bool]$pythonPath) ($(if ($pythonPath) { "$pythonVersion  $pythonPath" } else { '未安装，请安装 Python 3.11+' }))
if (-not $pythonPath) { $problems.Add('缺少 Python') }

$gitPath = (Get-Command git -ErrorAction SilentlyContinue).Source
Write-Check 'Git' ([bool]$gitPath) ($(if ($gitPath) { & git --version } else { '未安装（不影响运行，仅影响版本管理）' }))

# ---- 依赖状态 ----
$venvPython = Join-Path $apiDir '.venv\Scripts\python.exe'
$venvOk = Test-Path $venvPython
Write-Check '后端虚拟环境' $venvOk ($(if ($venvOk) { '.venv 已就绪' } else { '未创建，scripts\start-api.ps1 会自动创建' }))

$nodeModules = Join-Path $webDir 'node_modules'
$modulesOk = Test-Path $nodeModules
Write-Check '前端依赖' $modulesOk ($(if ($modulesOk) { 'node_modules 已就绪' } else { '未安装，scripts\start-web.ps1 会自动安装' }))

# ---- 端口 ----
foreach ($item in @(@{ Port = $ApiPort; Name = 'API 端口' }, @{ Port = $WebPort; Name = '前端端口' })) {
    $listener = Get-NetTCPConnection -LocalPort $item.Port -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        $problems.Add("端口 $($item.Port) 已被占用")
        $procId = ($listener | Select-Object -First 1).OwningProcess
        Write-Check $item.Name $false "被占用 PID=$procId"
    }
    elseif ($item.Port -in [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners().Port) {
        $problems.Add("端口 $($item.Port) 已被占用")
        Write-Check $item.Name $false '被占用'
    }
    else {
        Write-Check $item.Name $true '空闲'
    }
}

# ---- 数据目录 ----
$dataDir = if ($env:MASTERY_LAB_DATA_DIR) { $env:MASTERY_LAB_DATA_DIR } else { Join-Path $root 'data' }
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
Write-Check '数据目录' (Test-Path $dataDir) $dataDir
$db = Join-Path $dataDir 'mastery_lab.db'
Write-Check 'SQLite 数据库' $true ($(if (Test-Path $db) { "已存在（$((Get-Item $db).Length) 字节）" } else { '尚未创建，首次启动后端时自动创建' }))

Write-Host ('-' * 60)
if ($problems.Count -eq 0) {
    Write-Host '结论：环境满足运行要求。执行 scripts\dev.ps1 一键启动前后端。' -ForegroundColor Green
    exit 0
}

Write-Host ('结论：暂不能启动 -> ' + ($problems -join '、')) -ForegroundColor Red
exit 1
