# 在本机保存同济 API Key（只写入仓库根目录的 .env，该文件已被 .gitignore 忽略，不会上传 GitHub）
# 用法：在仓库目录打开 PowerShell，运行  powershell -ExecutionPolicy Bypass -File scripts\set_key.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$secret = Read-Host '请输入同济 API Key（输入时不显示）' -AsSecureString
$plain = [System.Net.NetworkCredential]::new('', $secret).Password.Trim()
if (-not $plain) { throw '没有输入密钥' }
if (-not $plain.StartsWith('sk-')) { Write-Warning '密钥通常以 sk- 开头，请确认输入无误。' }
$envPath = Join-Path $root '.env'
# ASCII 无 BOM 写入；只保留当前用户的读写权限
Set-Content -Path $envPath -Value "TONGJI_API_KEY=$plain" -Encoding ascii
icacls $envPath /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null
$plain = $null
Write-Host "已保存到 $envPath（仅本机，已被 git 忽略）。"
Write-Host '下一步：连上校园网或学校 VPN 后运行  py run.py check  验证。'
