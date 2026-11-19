# 同济 VPN（MotionPro）自动连接 / 断开。由 update.ps1 用 . 引入，也可以单独测试：
#   powershell -ExecutionPolicy Bypass -File scripts\vpn.ps1 status|up|down
#
# 原理：Windows 版 MotionPro 有隐藏的命令行模式（参考 github.com/ranranxuejie/tongji-motionpro-vpn 的实测）：
#   MotionPro.exe -connect <地址> <端口> <账号> <密码> 0 0 0 1      连接成功后 MotionPro 退出，vpnd 维持隧道
#   MotionPro.exe -disconnect                                       断开
# 账号和加密后的密码由 scripts\set_vpn.ps1 写进本机 .env（已被 git 忽略）。
# 密码用 Windows DPAPI 加密，只有你这个 Windows 账户在这台电脑上能解开。
param([string]$Action = '')   # status | up | down；被 . 引入时留空

$script:SbhRoot = Split-Path -Parent $PSScriptRoot
$script:SbhMarker = Join-Path $script:SbhRoot 'state\vpn_started_by_sandboxhot.txt'
$script:SbhVpnStarted = $false

function Get-SbhEnv([string]$Name) {
    $envPath = Join-Path $script:SbhRoot '.env'
    if (-not (Test-Path $envPath)) { return '' }
    foreach ($l in Get-Content $envPath -Encoding UTF8) {
        if ($l -match ('^\s*' + [regex]::Escape($Name) + '\s*=\s*(.*)$')) { return $Matches[1].Trim().Trim('"') }
    }
    return ''
}

function Find-MotionPro {
    $c = @('C:\Program Files\Array Networks\MotionPro VPN Client\MotionPro.exe',
           'C:\Program Files (x86)\Array Networks\MotionPro VPN Client\MotionPro.exe')
    foreach ($p in $c) { if (Test-Path $p) { return $p } }
    $keys = @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*')
    $a = Get-ItemProperty $keys -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -eq 'MotionPro' -and $_.UninstallString } | Select-Object -First 1
    if ($a) {
        $p = Join-Path (Split-Path -Parent ($a.UninstallString.Trim('"'))) 'MotionPro.exe'
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Test-InsideTongji {
    # 在校园网或 VPN 里时，agi.tongji.edu.cn 解析到 10.67.x.x；在外网解析到公网地址 202.120.188.x
    try {
        $ips = [System.Net.Dns]::GetHostAddresses('agi.tongji.edu.cn') | ForEach-Object { $_.IPAddressToString }
        return [bool]($ips | Where-Object { $_ -like '10.*' })
    } catch { return $false }
}

function Get-VpnIPv4 {
    # MotionPro 的隧道接口叫 “Array Networks SSL VPN”，只出现在 Get-NetIPInterface 里，Get-NetAdapter 看不到
    $ifs = Get-NetIPInterface -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.InterfaceAlias -like '*Array Networks*' -and $_.ConnectionState -eq 'Connected' }
    foreach ($i in $ifs) {
        $ip = Get-NetIPAddress -InterfaceIndex $i.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1
        if ($ip) { return $ip.IPAddress }
    }
    return $null
}

function Clear-MotionProState {
    # 被强行结束后，注册表里的状态可能停在“已连接”，下次命令行连接会直接退出
    $k = 'HKCU:\Software\VPN\VPN2'
    if (-not (Test-Path $k)) { return }
    foreach ($n in @('VPNstatus', 'status', 'MPCommandLineFlag')) {
        if ($null -ne (Get-ItemProperty -Path $k -Name $n -ErrorAction SilentlyContinue)) {
            Set-ItemProperty -Path $k -Name $n -Value 0 -ErrorAction SilentlyContinue
        }
    }
}

function Stop-MotionProProcesses {
    Get-Process -Name MotionPro, MotionProHttpd, vpnd -ErrorAction SilentlyContinue |
        ForEach-Object { try { $_.Kill() } catch { } }
}

function Format-Arg([string]$a) { '"' + ($a -replace '(\\*)"', '$1$1\"' -replace '(\\+)$', '$1$1') + '"' }

function Connect-TongjiVpn([int]$TimeoutSec = 180) {
    if (Test-InsideTongji) {
        if (Test-Path $script:SbhMarker) { $script:SbhVpnStarted = $true }  # 上次是脚本连的但没来得及断开：这次负责断开
        Write-Host "[VPN] 已经在校园网或 VPN 里，不用连接。"
        return $true
    }
    $user = Get-SbhEnv 'TONGJI_VPN_USER'
    $enc = Get-SbhEnv 'TONGJI_VPN_PASS_DPAPI'
    if (-not $user -or -not $enc) {
        Write-Host "[VPN] 还没有保存 VPN 账号。请运行一次：powershell -ExecutionPolicy Bypass -File scripts\set_vpn.ps1"
        return $false
    }
    $exe = Find-MotionPro
    if (-not $exe) { Write-Host "[VPN] 找不到 MotionPro.exe。"; return $false }
    try {
        $pass = [System.Net.NetworkCredential]::new('', (ConvertTo-SecureString $enc)).Password
    } catch {
        Write-Host "[VPN] 无法解开保存的密码（换了 Windows 账户或电脑？），请重新运行 scripts\set_vpn.ps1"
        return $false
    }
    $vpnHost = Get-SbhEnv 'TONGJI_VPN_HOST'; if (-not $vpnHost) { $vpnHost = 'vpn.tongji.cn' }
    $port = Get-SbhEnv 'TONGJI_VPN_PORT'; if (-not $port) { $port = '443' }

    Write-Host "[VPN] 正在连接 $vpnHost（首次可能要 1–2 分钟）……"
    Stop-MotionProProcesses   # 残留的 vpnd 会让新连接刚建立就被注销
    Start-Sleep -Seconds 3
    Clear-MotionProState
    $argLine = (@('-connect', $vpnHost, $port, $user, $pass, '0', '0', '0', '1') | ForEach-Object { Format-Arg $_ }) -join ' '
    $pass = $null
    try {
        Start-Process -FilePath $exe -ArgumentList $argLine -WindowStyle Hidden | Out-Null
    } catch {
        Write-Host "[VPN] 启动 MotionPro 失败：$($_.Exception.Message)"
        return $false
    }
    $argLine = $null
    $script:SbhVpnStarted = $true
    New-Item -ItemType Directory -Force (Split-Path $script:SbhMarker) | Out-Null
    (Get-Date -Format 's') | Set-Content -Path $script:SbhMarker

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $ipSince = $null
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
        $ip = Get-VpnIPv4
        if (-not $ip) { continue }
        if (-not $ipSince) { $ipSince = Get-Date }
        & ipconfig /flushdns | Out-Null
        if (Test-InsideTongji) { Write-Host "[VPN] 已连接（VPN 地址 $ip）。"; return $true }
        if (((Get-Date) - $ipSince).TotalSeconds -ge 30) {
            Write-Host "[VPN] 已拿到 VPN 地址 $ip，但域名还没解析到校内，先继续。"
            return $true
        }
    }
    $logFile = Join-Path $env:LOCALAPPDATA ("MotionPro\Log\MotionPro_{0}.log" -f (Get-Date -Format 'yyyy_MM_dd'))
    Write-Host "[VPN] $TimeoutSec 秒内没有连上。MotionPro 日志：$logFile"
    Disconnect-TongjiVpn
    return $false
}

function Disconnect-TongjiVpn {
    if (-not $script:SbhVpnStarted) { return }  # 不是脚本连的 VPN，不替你断开
    Write-Host "[VPN] 正在断开……"
    $exe = Find-MotionPro
    if ($exe) {
        try { Start-Process -FilePath $exe -ArgumentList '-disconnect' -WindowStyle Hidden | Out-Null } catch { }
        Start-Sleep -Seconds 8   # -disconnect 有时不会自己退出，不等它
    }
    Stop-MotionProProcesses
    Start-Sleep -Seconds 2
    Clear-MotionProState
    $script:SbhVpnStarted = $false
    Remove-Item -Path $script:SbhMarker -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 5; $i++) {
        if (-not (Get-VpnIPv4)) { Write-Host "[VPN] 已断开。"; return }
        Start-Sleep -Seconds 2
    }
    Write-Host "[VPN] 警告：VPN 似乎还连着，请在 MotionPro 里手动断开。"
}

if ($Action -eq 'status') {
    $ip = Get-VpnIPv4
    Write-Host ("MotionPro：{0}" -f (Find-MotionPro))
    Write-Host ("VPN 地址：{0}" -f $(if ($ip) { $ip } else { '（未连接）' }))
    Write-Host ("校内解析：{0}" -f (Test-InsideTongji))
    Write-Host ("已保存账号：{0}" -f $(if (Get-SbhEnv 'TONGJI_VPN_USER') { '是' } else { '否' }))
} elseif ($Action -eq 'up') {
    if (Connect-TongjiVpn) { exit 0 } else { exit 1 }
} elseif ($Action -eq 'down') {
    $script:SbhVpnStarted = $true
    Disconnect-TongjiVpn
}
