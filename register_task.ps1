# PowerShell script to register Aura Fitness Sync as a background Windows Scheduled Task
$ScriptPath = Join-Path -Path $PSScriptRoot -ChildPath "sync_all.py"
$WorkingDir = $PSScriptRoot

# Locate python.exe
$PythonPath = Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source

if (-not $PythonPath) {
    # Check default python installations if not in path
    $PythonPath = "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
    if (-not (Test-Path $PythonPath)) {
        $PythonPath = "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
        if (-not (Test-Path $PythonPath)) {
            $PythonPath = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
            if (-not (Test-Path $PythonPath)) {
                $PythonPath = "python"
            }
        }
    }
}

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Registering Aura Fitness Sync Task" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Script path: $ScriptPath"
Write-Host "WorkingDirectory: $WorkingDir"
Write-Host "Using Python: $PythonPath"

# Scheduled task configuration
$Action = New-ScheduledTaskAction -Execute $PythonPath -Argument $ScriptPath -WorkingDirectory $WorkingDir
# Trigger: At log on, then repeat every 2 hours indefinitely
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Trigger.Repetition.Interval = "PT2H"
$Trigger.Repetition.Duration = "P30000D" # Indefinitely (approx 82 years)
# Settings: Allow run on batteries, start when available, run as soon as possible after a schedule is missed
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

try {
    Register-ScheduledTask -TaskName "AuraFitnessSync" -Action $Action -Trigger $Trigger -Settings $Settings -Description "Automatically syncs fitness data from Strava, Google Fit, and FitNotes, then publishes to Google Drive for Gemini App Coach" -Force -ErrorAction Stop
    Write-Host ""
    Write-Host "Success! The scheduled task 'AuraFitnessSync' has been registered." -ForegroundColor Green
    Write-Host "It will execute automatically every 2 hours in the background." -ForegroundColor Green
    Write-Host "Sync logs are saved to: $WorkingDir\sync_history.log" -ForegroundColor Gray
} catch {
    Write-Host ""
    Write-Host "Error: Could not register scheduled task." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Note: You might need to run this command prompt / script as Administrator to register a Scheduled Task." -ForegroundColor Yellow
}
