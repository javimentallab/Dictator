<#
.SYNOPSIS
  Start Dictator automatically when you sign in to Windows (scheduled task).

.DESCRIPTION
  Registers a scheduled task that runs "pythonw -m dictator" from this repository's
  virtual environment when you sign in.

  -Elevated  runs it with administrator rights (no UAC prompt). Needed only if you want to
             dictate into programs that run as administrator: Windows does not let a normal
             program send keystrokes to an elevated one. Registering it requires an
             administrator PowerShell.
  -NoLogon   registers the task without the sign-in trigger (start it by hand or with -Start).
  -Start     starts the task right away.
  -Remove    deletes the task.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\windows\install-autostart.ps1
  powershell -ExecutionPolicy Bypass -File tools\windows\install-autostart.ps1 -Elevated -Start
#>
param(
    [string]$TaskName = 'Dictator',
    [string]$Config = '',
    [switch]$Elevated,
    [switch]$NoLogon,
    [switch]$Start,
    [switch]$Remove
)
$ErrorActionPreference = 'Stop'

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "Task '$TaskName' removed."
    exit 0
}

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$pythonw = Join-Path $repo '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) {
    Write-Error "Not found: $pythonw. Create the virtual environment first (see README)."
}

$arguments = '-m dictator'
if ($Config) { $arguments += " --config `"$Config`"" }

$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $repo
$level = if ($Elevated) { 'Highest' } else { 'Limited' }
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel $level
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)

$params = @{ TaskName = $TaskName; Action = $action; Principal = $principal; Settings = $settings; Force = $true }
if (-not $NoLogon) {
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $trigger.Delay = 'PT10S'
    $params.Trigger = $trigger
}
Register-ScheduledTask @params | Out-Null
Write-Output "Task '$TaskName' registered ($level$(if ($NoLogon) { ', no sign-in trigger' }))."

if ($Start) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Output "Task '$TaskName' started."
}
