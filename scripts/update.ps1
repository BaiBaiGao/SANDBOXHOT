# 一键更新：拉取最新代码 → 采集与精选 → 密钥检查 → 提交并推送到 GitHub。
# 用法：powershell -ExecutionPolicy Bypass -File scripts\update.ps1 [-NoLLM] [-NoPush]
param([switch]$NoLLM, [switch]$NoPush)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONUTF8 = '1'
$state = Join-Path $root 'state'
New-Item -ItemType Directory -Force $state | Out-Null
$log = Join-Path $state 'last_update.log'

$py = if (Get-Command py -ErrorAction SilentlyContinue) { 'py' } else { 'python' }
function Invoke-Git { git @args; if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' ') 失败" } }

# 1) 只要最新代码
Invoke-Git pull --ff-only --quiet

# 2) 采集、精选、生成网站
$pyArgs = @('run.py', 'update')
if ($NoLLM) { $pyArgs += '--no-llm' }
$ErrorActionPreference = 'Continue'   # Windows PowerShell 5.1 会把 stderr 当错误，这里放宽
& $py @pyArgs 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $log
$code = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($code -ne 0) { throw "更新失败，日志见 $log" }

# 3) 提交前检查：发现 API Key 立即中止
& $py run.py guard
if ($LASTEXITCODE -ne 0) { throw '发现疑似 API Key，已中止提交。' }

# 4) 只提交网站与数据目录
Invoke-Git add docs data
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    Invoke-Git commit --quiet -m "data: update $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    if (-not $NoPush) { Invoke-Git push --quiet }
}

# 5) 每 7 天把本地仓库瘦身成“只有最新版本”（GitHub 上保留完整历史；.env 与 state\ 不受影响）
$stamp = Join-Path $state 'last_slim.txt'
$last = if (Test-Path $stamp) { [datetime](Get-Content $stamp) } else { [datetime]::MinValue }
$pending = git status --porcelain --untracked-files=no
$ahead = git rev-list --count '@{u}..HEAD'
if (-not $NoPush -and -not $pending -and $ahead -eq '0' -and ((Get-Date) - $last).TotalDays -ge 7) {
    $upstream = git rev-parse --abbrev-ref --symbolic-full-name '@{u}'
    $branch = $upstream.Substring($upstream.IndexOf('/') + 1)
    Invoke-Git fetch --quiet --depth 1 origin $branch
    Invoke-Git reset --quiet --hard FETCH_HEAD
    Invoke-Git reflog expire --expire=now --all
    Invoke-Git gc --quiet --prune=now
    (Get-Date -Format 's') | Set-Content $stamp
    Write-Host '本地仓库已瘦身为最新版本。'
}
Write-Host '完成。'
