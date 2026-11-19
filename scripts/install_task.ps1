# 注册 Windows 计划任务：每 4 小时自动运行一次 update.ps1（仅在你登录时运行，无需保存密码）。
# 用法：powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 [-Hours 4]
# 删除：Unregister-ScheduledTask -TaskName SANDBOXHOT -Confirm:$false
param([int]$Hours = 4)
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'update.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`"" `
    -WorkingDirectory (Split-Path -Parent $PSScriptRoot)
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) `
    -RepetitionInterval (New-TimeSpan -Hours $Hours)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'SANDBOXHOT' -Action $action -Trigger $trigger -Settings $settings `
    -Description 'SANDBOXHOT 定时采集与发布' -Force | Out-Null
Write-Host "已注册计划任务 SANDBOXHOT：每 $Hours 小时运行一次（电脑开机并登录时）。"
