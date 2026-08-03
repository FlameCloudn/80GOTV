param()

$ErrorActionPreference = "SilentlyContinue"
$projectRoot = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $PSScriptRoot "start_fixed_tunnel.ps1"
$tunnelConfig = Join-Path $projectRoot "deploy\cloudflare-config.yml"

$processes = @(Get-CimInstance Win32_Process)
$launcherProcesses = @(
    $processes | Where-Object {
        $_.Name -match '^powershell(?:\.exe)?$' -and
        $_.CommandLine -and
        $_.CommandLine.Contains($startScript)
    }
)
$launcherParentIds = @($launcherProcesses | ForEach-Object { [int]$_.ParentProcessId })

$tunnelProcesses = @(
    $processes | Where-Object {
        $_.Name -ieq "cloudflared.exe" -and
        $_.CommandLine -and
        ($_.CommandLine.Contains($tunnelConfig) -or $_.CommandLine -match 'tunnel\s+.*run\s+80gotv')
    }
)

$websiteProcessIds = @()
$listeners = @(Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue)
foreach ($listener in $listeners) {
    $candidate = $processes | Where-Object { $_.ProcessId -eq $listener.OwningProcess } | Select-Object -First 1
    if ($candidate -and $candidate.CommandLine -match 'waitress' -and $candidate.CommandLine -match 'wsgi:app') {
        $websiteProcessIds += [int]$candidate.ProcessId
    }
}

$stoppedSomething = $false
foreach ($process in $tunnelProcesses) {
    Stop-Process -Id $process.ProcessId -Force
    $stoppedSomething = $true
}
foreach ($processId in ($websiteProcessIds | Select-Object -Unique)) {
    Stop-Process -Id $processId -Force
    $stoppedSomething = $true
}
foreach ($process in $launcherProcesses) {
    Stop-Process -Id $process.ProcessId -Force
    $stoppedSomething = $true
}
foreach ($parentId in ($launcherParentIds | Select-Object -Unique)) {
    $parent = $processes | Where-Object { $_.ProcessId -eq $parentId } | Select-Object -First 1
    if ($parent -and $parent.Name -ieq "cmd.exe") {
        Stop-Process -Id $parentId -Force
    }
}

Start-Sleep -Milliseconds 700
$siteStillRunning = @(Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue).Count -gt 0
$tunnelStillRunning = @(
    Get-CimInstance Win32_Process | Where-Object {
        $_.Name -ieq "cloudflared.exe" -and $_.CommandLine -and
        ($_.CommandLine.Contains($tunnelConfig) -or $_.CommandLine -match 'tunnel\s+.*run\s+80gotv')
    }
).Count -gt 0

if ($siteStillRunning -or $tunnelStillRunning) {
    Write-Host "80GOTV 没有完全关闭，请再运行一次。" -ForegroundColor Red
    exit 1
}

if ($stoppedSomething) {
    Write-Host "80GOTV 网站和固定域名隧道已完全关闭。" -ForegroundColor Green
} else {
    Write-Host "80GOTV 当前没有运行。" -ForegroundColor Yellow
}
