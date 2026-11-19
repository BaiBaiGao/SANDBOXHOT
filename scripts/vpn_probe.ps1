# SANDBOXHOT：MotionPro / 同济 VPN 只读检测脚本
# 只读取信息：不连接 VPN、不点击任何按钮、不修改任何设置，也不读取密码。
# 结果写到 state\vpn_probe.txt，请把这个文件的全部内容发给 Claude。
# 用法（在 SANDBOXHOT 文件夹里）：powershell -ExecutionPolicy Bypass -File scripts\vpn_probe.ps1
$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$root = Split-Path -Parent $PSScriptRoot
$stateDir = Join-Path $root 'state'
New-Item -ItemType Directory -Force $stateDir | Out-Null
$out = Join-Path $stateDir 'vpn_probe.txt'
$lines = New-Object System.Collections.Generic.List[string]
function Say([string]$s) { $lines.Add($s); Write-Host $s }

function Test-Tcp([string]$hostName, [int]$port) {
    $c = New-Object System.Net.Sockets.TcpClient
    try {
        $ar = $c.BeginConnect($hostName, $port, $null, $null)
        if ($ar.AsyncWaitHandle.WaitOne(4000) -and $c.Connected) { return 'OK' }
        return 'TIMEOUT'
    } catch { return "FAIL: $($_.Exception.Message)" } finally { $c.Close() }
}
function Test-Dns([string]$hostName) {
    try { return ([System.Net.Dns]::GetHostAddresses($hostName) | ForEach-Object { $_.IPAddressToString }) -join ', ' }
    catch { return "FAIL: $($_.Exception.Message)" }
}

function Probe-Network([string]$label) {
    Say ""
    Say "===== 网络状态（$label） ====="
    foreach ($h in @('agi.tongji.edu.cn', 'github.com', 'api.github.com')) {
        Say ("{0,-20} DNS={1}  TCP443={2}" -f $h, (Test-Dns $h), (Test-Tcp $h 443))
    }
    Say "-- 网络适配器 --"
    try {
        Get-NetAdapter -IncludeHidden -ErrorAction Stop | Sort-Object Status |
            ForEach-Object { Say ("{0,-30} | {1,-45} | {2}" -f $_.Name, $_.InterfaceDescription, $_.Status) }
    } catch {
        Get-WmiObject Win32_NetworkAdapter | Where-Object { $_.NetConnectionID } |
            ForEach-Object { Say ("{0,-30} | {1,-45} | status={2}" -f $_.NetConnectionID, $_.Name, $_.NetConnectionStatus) }
    }
    Say "-- 默认路由 --"
    try {
        Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop |
            ForEach-Object { Say ("via {0,-16} ifIndex={1,-4} alias={2} metric={3}" -f $_.NextHop, $_.ifIndex, $_.InterfaceAlias, $_.RouteMetric) }
    } catch { Say "（无法读取路由）" }
}

function Probe-Windows([string]$label) {
    Say ""
    Say "===== MotionPro 窗口控件（$label） ====="
    try {
        Add-Type -AssemblyName UIAutomationClient
        Add-Type -AssemblyName UIAutomationTypes
    } catch { Say "无法加载 UI Automation：$($_.Exception.Message)"; return }
    $procs = Get-Process | Where-Object { $_.ProcessName -match 'motion|array|vpn' }
    if (-not $procs) { Say "没有找到 MotionPro 进程。请先打开 MotionPro 的主窗口（不要最小化到托盘）。"; return }
    $ids = @($procs | ForEach-Object { $_.Id })
    $rootEl = [System.Windows.Automation.AutomationElement]::RootElement
    $tops = $rootEl.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)
    $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
    $script:count = 0
    function Dump($el, [int]$depth) {
        if ($depth -gt 12 -or $script:count -gt 600) { return }
        $script:count++
        try {
            $cur = $el.Current
            $pats = ($el.GetSupportedPatterns() | ForEach-Object { $_.ProgrammaticName -replace 'Identifiers.Pattern', '' -replace 'PatternIdentifiers', '' }) -join ','
            $r = $cur.BoundingRectangle
            Say ("{0}{1} | name='{2}' | id='{3}' | class='{4}' | patterns=[{5}] | rect={6},{7},{8}x{9} | enabled={10}" -f (' ' * ($depth * 2)),
                ($cur.ControlType.ProgrammaticName -replace 'ControlType\.', ''), $cur.Name, $cur.AutomationId, $cur.ClassName, $pats,
                [int]$r.X, [int]$r.Y, [int]$r.Width, [int]$r.Height, $cur.IsEnabled)
        } catch { Say ("{0}(读取失败)" -f (' ' * ($depth * 2))) }
        $child = $walker.GetFirstChild($el)
        while ($child -ne $null) {
            Dump $child ($depth + 1)
            $child = $walker.GetNextSibling($child)
        }
    }
    $found = $false
    foreach ($w in $tops) {
        if ($ids -contains $w.Current.ProcessId) {
            $found = $true
            Say ("--- 窗口：'{0}'  进程={1}" -f $w.Current.Name, (Get-Process -Id $w.Current.ProcessId).ProcessName)
            Dump $w 0
        }
    }
    if (-not $found) { Say "MotionPro 正在运行，但没有可见窗口。请从托盘图标打开它的主窗口后重新运行。" }
}

Say "SANDBOXHOT VPN 检测  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Say "Windows: $([Environment]::OSVersion.VersionString)  PowerShell: $($PSVersionTable.PSVersion)"

Say ""
Say "===== 安装信息 ====="
$keys = @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
          'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
          'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*')
$apps = Get-ItemProperty $keys -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -match 'motion|array' }
foreach ($a in $apps) { Say ("{0} | 版本 {1} | 位置 {2} | 卸载 {3}" -f $a.DisplayName, $a.DisplayVersion, $a.InstallLocation, $a.UninstallString) }
$dirs = @($apps | ForEach-Object { $_.InstallLocation } | Where-Object { $_ })
$dirs += @("$env:ProgramFiles", "${env:ProgramFiles(x86)}", "$env:LOCALAPPDATA", "$env:APPDATA") |
    ForEach-Object { Get-ChildItem $_ -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'motion|array' } | ForEach-Object { $_.FullName } }
$dirs = $dirs | Sort-Object -Unique
foreach ($d in $dirs) {
    Say "-- 目录 $d"
    Get-ChildItem $d -Recurse -Include *.exe, *.cmd, *.bat -ErrorAction SilentlyContinue | Select-Object -First 40 |
        ForEach-Object { Say ("   {0}  ({1})" -f $_.FullName, $_.VersionInfo.FileVersion) }
}
$lnk = Get-ChildItem "$env:ProgramData\Microsoft\Windows\Start Menu", "$env:APPDATA\Microsoft\Windows\Start Menu", "$env:USERPROFILE\Desktop", "$env:PUBLIC\Desktop" -Recurse -Filter *.lnk -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match 'motion|array' }
$sh = New-Object -ComObject WScript.Shell
foreach ($l in $lnk) { $t = $sh.CreateShortcut($l.FullName); Say ("快捷方式 {0} -> {1} {2}" -f $l.FullName, $t.TargetPath, $t.Arguments) }

Say ""
Say "===== 进程与服务 ====="
Get-Process | Where-Object { $_.ProcessName -match 'motion|array|vpn' } | ForEach-Object {
    $p = $_; $path = try { $p.Path } catch { '' }; Say ("进程 {0} (PID {1}) {2}" -f $p.ProcessName, $p.Id, $path) }
Get-Service | Where-Object { $_.Name -match 'motion|array|vpn' -or $_.DisplayName -match 'motion|array' } |
    ForEach-Object { Say ("服务 {0} | {1} | {2} | {3}" -f $_.Name, $_.DisplayName, $_.Status, $_.StartType) }

Write-Host ""
Write-Host "第 1 步：请打开 MotionPro 主窗口，保持【未连接】VPN，然后按回车……" -ForegroundColor Yellow
[void](Read-Host)
Probe-Network '未连接'
Probe-Windows '未连接'

Write-Host ""
Write-Host "第 2 步：请在 MotionPro 里手动连上“同济大学VPN系统”，等连接成功、主窗口仍然打开时按回车……" -ForegroundColor Yellow
[void](Read-Host)
Probe-Network '已连接'
Probe-Windows '已连接'

Write-Host ""
Write-Host "第 3 步：请在 MotionPro 里手动【断开】VPN，然后按回车……" -ForegroundColor Yellow
[void](Read-Host)
Probe-Network '断开后'

$lines | Set-Content -Path $out -Encoding UTF8
Write-Host ""
Write-Host "完成。结果已保存到 $out ，请把这个文件的全部内容发给 Claude。" -ForegroundColor Green
