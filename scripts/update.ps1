# 笔记本定时任务：用同济 API 给云端（GitHub Actions）采集的条目补模型精选、速读卡和日报。
# 只提交 data\enrichments.json，不碰云端写的文件，所以不会和 Actions 冲突。
# 需要校园网或学校 VPN；连不上时直接结束，不消耗积分。
# 用法：powershell -ExecutionPolicy Bypass -File scripts\update.ps1 [-NoPush]
param([switch]$NoPush)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONUTF8 = '1'
# Python 输出 UTF-8；让 PowerShell 按 UTF-8 解码管道输出，避免窗口和日志里的中文乱码
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$OutputEncoding = [System.Text.Encoding]::UTF8
$state = Join-Path $root 'state'
New-Item -ItemType Directory -Force $state | Out-Null
$log = Join-Path $state 'last_update.log'
$py = if (Get-Command py -ErrorAction SilentlyContinue) { 'py' } else { 'python' }
function Invoke-Git { git @args; if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' ') 失败" } }

# 1) 丢弃本地对网站/数据文件的临时改动（例如本地预览生成的），再拉取云端最新数据
Invoke-Git checkout --quiet -- docs data
Invoke-Git pull --ff-only --quiet

# 2) 只做模型加工
$ErrorActionPreference = 'Continue'   # Windows PowerShell 5.1 会把 stderr 当错误，这里放宽
& $py run.py enrich 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $log
$code = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($code -ne 0) { Write-Host "本次没有调用模型（见 $log）。"; exit 0 }

# 3) 提交前检查：发现 API Key 立即中止
& $py run.py guard
if ($LASTEXITCODE -ne 0) { throw '发现疑似 API Key，已中止提交。' }

# 4) 只提交 enrichments.json；推送被拒（Actions 刚推送过）就重新拉取再推
Invoke-Git add data/enrichments.json
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    Invoke-Git commit --quiet -m "enrich: model picks $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    if (-not $NoPush) {
        for ($i = 0; $i -lt 3; $i++) {
            git push --quiet
            if ($LASTEXITCODE -eq 0) { break }
            Invoke-Git pull --rebase --quiet
        }
        if ($LASTEXITCODE -ne 0) { throw '推送失败，下次运行会重试。' }
    }
}
# 本地预览用的 docs\ 与 data\ 改动不保留，保证电脑上只有最新版本
git checkout --quiet -- docs data 2>$null

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
