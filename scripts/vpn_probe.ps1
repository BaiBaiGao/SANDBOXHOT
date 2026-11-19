# SANDBOXHOT：MotionPro / 同济 VPN 只读检测脚本（第二版）
# 只读取信息：不点击、不连接 VPN、不修改设置、不读取任何文件内容和密码。
# 唯一的动作：会再启动一次 MotionPro.exe，把缩在托盘里的主窗口调出来，方便读取窗口控件。
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
function Save { $lines | Set-Content -Path $out -Encoding UTF8 }

$installDir = 'C:\Program Files\Array Networks\MotionPro VPN Client'
$mpExe = Join-Path $installDir 'MotionPro.exe'
$procPattern = '^(MotionPro|MotionProHttpd|vpnd|VPNService|VPNInstallManager)$'

function Test-Dns([string]$hostName) {
    try { return ([System.Net.Dns]::GetHostAddresses($hostName) | ForEach-Object { $_.IPAddressToString }) -join ', ' }
    catch { return "FAIL: $($_.Exception.Message)" }
}

function Probe-Network([string]$label) {
    Say ""
    Say "===== 网络状态（$label） ====="
    Say ("agi.tongji.edu.cn DNS = {0}" -f (Test-Dns 'agi.tongji.edu.cn'))
    Say "-- 默认路由 --"
    try {
        Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop |
            ForEach-Object { Say ("via {0,-16} ifIndex={1,-4} alias={2} metric={3}" -f $_.NextHop, $_.ifIndex, $_.InterfaceAlias, $_.RouteMetric) }
    } catch { Say "（无法读取路由）" }
    Say "-- 名称含 Array 的 IP 接口 --"
    try {
        Get-NetIPInterface -ErrorAction Stop | Where-Object { $_.InterfaceAlias -match 'Array|本地连接$|以太网 2' } |
            ForEach-Object { Say ("ifIndex={0,-4} alias={1} family={2} state={3}" -f $_.ifIndex, $_.InterfaceAlias, $_.AddressFamily, $_.ConnectionState) }
        Get-NetIPConfiguration -All -ErrorAction Stop | Where-Object { $_.InterfaceAlias -match 'Array' -or $_.InterfaceDescription -match 'Array' } |
            ForEach-Object { Say ("配置 alias={0} desc={1} ipv4={2} gw={3} dns={4}" -f $_.InterfaceAlias, $_.InterfaceDescription,
                (($_.IPv4Address | ForEach-Object { $_.IPAddress }) -join ','), (($_.IPv4DefaultGateway | ForEach-Object { $_.NextHop }) -join ','),
                (($_.DNSServer | Where-Object { $_.AddressFamily -eq 2 } | ForEach-Object { $_.ServerAddresses }) -join ',')) }
    } catch { Say "（无法读取 IP 接口：$($_.Exception.Message)）" }
}

function Probe-Ports([string]$label) {
    Say ""
    Say "===== 本地监听端口（$label） ====="
    $procs = Get-Process | Where-Object { $_.ProcessName -match $procPattern }
    foreach ($p in $procs) {
        $conns = Get-NetTCPConnection -State Listen -OwningProcess $p.Id -ErrorAction SilentlyContinue
        if (-not $conns) { Say ("{0} (PID {1})：没有 TCP 监听端口" -f $p.ProcessName, $p.Id); continue }
        foreach ($c in $conns) {
            Say ("{0} (PID {1}) 监听 {2}:{3}" -f $p.ProcessName, $p.Id, $c.LocalAddress, $c.LocalPort)
            if ($p.ProcessName -eq 'MotionProHttpd' -and $c.LocalAddress -in @('127.0.0.1', '0.0.0.0', '::', '::1')) {
                foreach ($scheme in @('http', 'https')) {
                    try {
                        $r = Invoke-WebRequest -UseBasicParsing -Method Get -Uri ("{0}://127.0.0.1:{1}/" -f $scheme, $c.LocalPort) -TimeoutSec 4
                        $body = ($r.Content -replace '\s+', ' ')
                        if ($body.Length -gt 300) { $body = $body.Substring(0, 300) }
                        Say ("   GET {0}://127.0.0.1:{1}/ -> {2}  {3}" -f $scheme, $c.LocalPort, $r.StatusCode, $body)
                    } catch {
                        $code = try { [int]$_.Exception.Response.StatusCode } catch { '' }
                        Say ("   GET {0}://127.0.0.1:{1}/ -> 失败 {2} {3}" -f $scheme, $c.LocalPort, $code, $_.Exception.Message)
                    }
                }
            }
        }
    }
}

function Probe-Windows([string]$label) {
    Say ""
    Say "===== MotionPro 窗口控件（$label） ====="
    try {
        Add-Type -AssemblyName UIAutomationClient
        Add-Type -AssemblyName UIAutomationTypes
    } catch { Say "无法加载 UI Automation：$($_.Exception.Message)"; return $false }
    $ids = @(Get-Process -Name MotionPro -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
    foreach ($p in Get-Process -Name MotionPro -ErrorAction SilentlyContinue) {
        Say ("MotionPro PID {0} 主窗口句柄={1} 标题='{2}'" -f $p.Id, $p.MainWindowHandle, $p.MainWindowTitle)
    }
    if (-not $ids) { Say "MotionPro 没有在运行。"; return $false }
    $rootEl = [System.Windows.Automation.AutomationElement]::RootElement
    $tops = $rootEl.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)
    $walker = [System.Windows.Automation.TreeWalker]::RawViewWalker
    $script:count = 0
    function Dump($el, [int]$depth) {
        if ($depth -gt 14 -or $script:count -gt 800) { return }
        $script:count++
        try {
            $cur = $el.Current
            $pats = ($el.GetSupportedPatterns() | ForEach-Object { $_.ProgrammaticName -replace 'PatternIdentifiers\.Pattern', '' }) -join ','
            $r = $cur.BoundingRectangle
            $name = $cur.Name
            if ($name.Length -gt 80) { $name = $name.Substring(0, 80) + '…' }
            Say ("{0}{1} | name='{2}' | id='{3}' | class='{4}' | patterns=[{5}] | rect={6},{7},{8}x{9} | enabled={10} | offscreen={11}" -f (' ' * ($depth * 2)),
                ($cur.ControlType.ProgrammaticName -replace 'ControlType\.', ''), $name, $cur.AutomationId, $cur.ClassName, $pats,
                [int]$r.X, [int]$r.Y, [int]$r.Width, [int]$r.Height, $cur.IsEnabled, $cur.IsOffscreen)
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
            Say ("--- 顶层窗口：'{0}' class='{1}'" -f $w.Current.Name, $w.Current.ClassName)
            Dump $w 0
        }
    }
    if (-not $found) { Say "没有读到 MotionPro 的可见窗口。" }
    return $found
}

function Show-MotionPro {
    if (Test-Path $mpExe) {
        Say "（再次启动 MotionPro.exe，把主窗口调到前台）"
        Start-Process -FilePath $mpExe -WorkingDirectory $installDir
        Start-Sleep -Seconds 6
    }
}

Say "SANDBOXHOT VPN 检测（第二版）  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

Say ""
Say "===== 安装目录里的非程序文件（只列文件名） ====="
Get-ChildItem $installDir -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -notin @('.exe', '.dll', '.sys', '.cat', '.inf', '.png', '.ico', '.jpg', '.gif', '.bmp', '.svg', '.ttf', '.woff', '.woff2') } |
    Select-Object -First 120 | ForEach-Object { Say ("  {0}  {1:N0} 字节" -f $_.FullName.Replace($installDir, '.'), $_.Length) }
Say "-- dll 数量：$((Get-ChildItem $installDir -Recurse -Filter *.dll -ErrorAction SilentlyContinue | Measure-Object).Count)，其中名字含 Qt/Chrome/Electron/CEF/WebView 的："
Get-ChildItem $installDir -Recurse -Filter *.dll -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'qt|chrome|electron|cef|webview|libcef|ffmpeg|icu' } |
    Select-Object -First 20 | ForEach-Object { Say ("  {0}" -f $_.FullName.Replace($installDir, '.')) }
foreach ($d in @("$env:LOCALAPPDATA\MotionPro", "$env:APPDATA\MotionPro", "$env:APPDATA\Array Networks", "$env:LOCALAPPDATA\Array Networks")) {
    if (Test-Path $d) {
        Say "-- 用户数据目录 $d（只列文件名）"
        Get-ChildItem $d -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 60 |
            ForEach-Object { Say ("  {0}  {1:N0} 字节  {2}" -f $_.FullName.Replace($d, '.'), $_.Length, $_.LastWriteTime.ToString('yyyy-MM-dd HH:mm')) }
    }
}

Say ""
Say "===== 程序里的命令行线索（可读字符串） ====="
$kw = 'usage|--[a-z]|/[a-z]+ |connect|disconnect|logout|logon|profile|127\.0\.0\.1|localhost:|cmdline|command'
foreach ($name in @('vpnd.exe', 'MotionPro.exe', 'MotionProHttpd.exe')) {
    $f = Join-Path $installDir $name
    if (-not (Test-Path $f)) { continue }
    $size = (Get-Item $f).Length
    Say "-- $name（$([math]::Round($size / 1MB, 1)) MB）"
    if ($size -gt 60MB) { Say "   文件太大，跳过"; continue }
    $bytes = [System.IO.File]::ReadAllBytes($f)
    $found = New-Object System.Collections.Generic.List[string]
    foreach ($text in @([System.Text.Encoding]::ASCII.GetString($bytes), [System.Text.Encoding]::Unicode.GetString($bytes))) {
        foreach ($m in [regex]::Matches($text, '[\x20-\x7e]{6,160}')) {
            $v = $m.Value
            if ($v -match $kw -and -not $found.Contains($v)) { $found.Add($v) }
            if ($found.Count -ge 40) { break }
        }
        if ($found.Count -ge 40) { break }
    }
    foreach ($v in $found) { Say "   $v" }
}

Write-Host ""
Write-Host "第 1 步：请确认 VPN 处于【未连接】状态，然后按回车。脚本会自动把 MotionPro 主窗口调出来……" -ForegroundColor Yellow
[void](Read-Host)
Show-MotionPro
Probe-Network '未连接'
Probe-Ports '未连接'
if (-not (Probe-Windows '未连接')) {
    Write-Host "没读到主窗口。请从右下角托盘图标手动打开 MotionPro 主窗口，然后按回车重试……" -ForegroundColor Yellow
    [void](Read-Host)
    [void](Probe-Windows '未连接-重试')
}
Save

Write-Host ""
Write-Host "第 2 步：请在 MotionPro 里手动双击“同济大学VPN系统”连上 VPN，连接成功后【保持主窗口打开】，按回车……" -ForegroundColor Yellow
[void](Read-Host)
Probe-Network '已连接'
Probe-Ports '已连接'
if (-not (Probe-Windows '已连接')) { Show-MotionPro; [void](Probe-Windows '已连接-重试') }
Save

Write-Host ""
Write-Host "第 3 步：请在 MotionPro 里手动【断开】VPN，然后按回车……" -ForegroundColor Yellow
[void](Read-Host)
Probe-Network '断开后'
Save
Write-Host ""
Write-Host "完成。结果已保存到 $out ，请把这个文件的全部内容发给 Claude。" -ForegroundColor Green
