# 在本机保存同济 VPN 账号，供 update.ps1 自动连接 VPN 使用。
# 账号写进 .env；密码用 Windows DPAPI 加密后写进 .env，只有你这个 Windows 账户在这台电脑上能解开。
# .env 已被 .gitignore 忽略，不会上传 GitHub。密码只在你这台电脑上输入，不要发到聊天里。
# 用法：powershell -ExecutionPolicy Bypass -File scripts\set_vpn.ps1
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$root = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $root '.env'

# 从 MotionPro 的配置里猜 VPN 地址（只取地址，不读其他内容）
$guess = ''
$ini = Join-Path $env:LOCALAPPDATA 'MotionPro\motionpro.ini'
if (Test-Path $ini) {
    $m = Select-String -Path $ini -Pattern '([A-Za-z0-9-]+\.)+tongji\.(edu\.)?cn' -AllMatches -ErrorAction SilentlyContinue |
        ForEach-Object { $_.Matches } | ForEach-Object { $_.Value } | Select-Object -Unique -First 1
    if ($m) { $guess = $m }
}
if (-not $guess) { $guess = 'vpn.tongji.cn' }

Write-Host "MotionPro 里“同济大学VPN系统”的地址看起来是：$guess"
$vpnHost = Read-Host "直接回车使用这个地址，或输入正确的地址"
if (-not $vpnHost) { $vpnHost = $guess }
$user = (Read-Host '统一身份认证账号（学号或工号）').Trim()
if (-not $user) { throw '没有输入账号' }
$sec = Read-Host '统一身份认证密码（输入时不显示）' -AsSecureString
if ($sec.Length -eq 0) { throw '没有输入密码' }
$enc = ConvertFrom-SecureString $sec

$keep = @()
if (Test-Path $envPath) {
    $keep = @(Get-Content $envPath -Encoding UTF8 | Where-Object { $_ -notmatch '^\s*TONGJI_VPN_(USER|PASS_DPAPI|HOST|PORT)\s*=' })
}
$lines = $keep + @("TONGJI_VPN_HOST=$vpnHost", 'TONGJI_VPN_PORT=443', "TONGJI_VPN_USER=$user", "TONGJI_VPN_PASS_DPAPI=$enc")
[System.IO.File]::WriteAllLines($envPath, [string[]]$lines, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "已保存到 $envPath（仅本机，密码已加密，已被 git 忽略）。" -ForegroundColor Green

$t = Read-Host '要现在测试一次“连接 → 断开”吗？请先确认 VPN 是断开的。(y/N)'
if ($t -match '^[yY]') {
    . (Join-Path $PSScriptRoot 'vpn.ps1')
    if (Connect-TongjiVpn) {
        Write-Host '连接成功，5 秒后断开……'
        Start-Sleep -Seconds 5
        Disconnect-TongjiVpn
    } else {
        Write-Host '连接失败，请检查地址、账号和密码，或把窗口里的提示发给 Claude。' -ForegroundColor Yellow
    }
}
