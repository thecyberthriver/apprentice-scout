# Registers "ApprenticeScout" to run TWICE A WEEK (Mon + Thu, 8:00 AM),
# SILENTLY, via Task Scheduler — a film-ready TikTok brief of PAID apprenticeships,
# rotational programs, and early-career cyber/tech roles posted in the last week.
# Silent = launched with pythonw.exe (no console window).
# Run this ONCE:  .\register_task.ps1   (elevate if it reports an access error)
# Re-running updates the existing task.

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$scout     = Join-Path $scriptDir "apprentice_scout.py"

# Prefer pythonw.exe (windowless). Fall back to python.exe if not found.
$python  = (Get-Command python).Source
$pythonw = Join-Path (Split-Path -Parent $python) "pythonw.exe"
$exe     = if (Test-Path $pythonw) { $pythonw } else { $python }

$action = New-ScheduledTaskAction -Execute $exe -Argument "`"$scout`"" -WorkingDirectory $scriptDir

# Monday and Thursday at 8:00 AM — two fresh content batches a week.
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Thursday -At 8:00AM

# Start when available (catch up if the PC was asleep), run on battery (critical
# for laptops: default power conditions leave the task stuck "Queued"), hidden.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopOnIdleEnd -RunOnlyIfNetworkAvailable -Hidden `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -MultipleInstances IgnoreNew

# Run as the current user, only when logged on (no stored password needed).
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "ApprenticeScout" `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Mon+Thu 8AM: scrapes LinkedIn + Google Jobs directly for PAID apprenticeships, rotational/LDP programs, and early-career cyber/tech roles posted in the last 7 days; sends a film-ready TikTok brief to Telegram. Runs silently." `
    -Force | Out-Null

Write-Host "Registered 'ApprenticeScout' (Mon + Thu 8:00 AM, silent via $([System.IO.Path]::GetFileName($exe)))."
Write-Host "Manage it in Task Scheduler, or run:  Get-ScheduledTask ApprenticeScout | Get-ScheduledTaskInfo"
Write-Host "Test now (console, no Telegram):  python `"$scout`" --preview"
Write-Host "Test now (real Telegram send):    python `"$scout`""
