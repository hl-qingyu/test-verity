param(
    [ValidateSet('all', 'api', 'worker', 'frontend')]
    [string]$Service = 'all'
)

$ErrorActionPreference = 'Stop'

if ($PSVersionTable.PSEdition -eq 'Core') {
    $windowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $windowsPowerShell)) {
        throw 'Windows PowerShell is required for the Windows process inspection used by this script.'
    }
    $startupArguments = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath)
    if ($Service -ne 'all') { $startupArguments += @('-Service', $Service) }
    & $windowsPowerShell @startupArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Development stop failed in Windows PowerShell (exit $LASTEXITCODE). See the error above."
    }
    return
}

$root = $PSScriptRoot
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
$vite = Join-Path $root 'frontend\node_modules\vite\bin\vite.js'

function Get-ProcessSnapshot {
    $query = 'Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress'
    @(powershell.exe -NoProfile -NonInteractive -Command $query | ConvertFrom-Json)
}

function Stop-ProjectService([string]$name, [string]$processName, [string]$path, [string]$command, [int]$port = 0) {
    $processes = Get-ProcessSnapshot
    $targets = @($processes | Where-Object {
        $_.Name -eq $processName -and
        $_.CommandLine -and $_.CommandLine.Contains($path) -and $_.CommandLine.Contains($command)
    })
    if (-not $targets.Count) {
        Write-Host "$name is not running."
        return
    }
    $ids = @($targets | ForEach-Object ProcessId)
    foreach ($entry in ($targets | Sort-Object @{ Expression = { if ($ids -contains $_.ParentProcessId) { 0 } else { 1 } } })) {
        if ($entry.Name -eq $processName -and $entry.CommandLine -and
            $entry.CommandLine.Contains($path) -and $entry.CommandLine.Contains($command)) {
            $taskkill = Join-Path $env:SystemRoot 'System32\taskkill.exe'
            Start-Process -FilePath $taskkill -ArgumentList @('/PID', [string]$entry.ProcessId, '/T', '/F') -Wait -WindowStyle Hidden | Out-Null
            for ($attempt = 0; $attempt -lt 20; $attempt++) {
                $remaining = Get-ProcessSnapshot | Where-Object ProcessId -eq $entry.ProcessId | Select-Object -First 1
                $listeners = @()
                if ($port -gt 0) {
                    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
                    foreach ($listener in $listeners) {
                        $listenerProcess = Get-ProcessSnapshot | Where-Object ProcessId -eq $listener.OwningProcess | Select-Object -First 1
                        if ($listenerProcess -and $listenerProcess.Name -eq $processName -and
                            $listenerProcess.CommandLine -and $listenerProcess.CommandLine.Contains($path) -and
                            $listenerProcess.CommandLine.Contains($command)) {
                            Start-Process -FilePath $taskkill -ArgumentList @('/PID', [string]$listener.OwningProcess, '/T', '/F') -Wait -WindowStyle Hidden | Out-Null
                        }
                    }
                    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
                }
                if (-not $remaining -and -not $listeners.Count) { break }
                Start-Sleep -Milliseconds 100
            }
            if ($remaining -or $listeners.Count) { throw "$name process $($entry.ProcessId) did not stop." }
        }
    }
    Write-Host "$name stopped (project processes only)."
}

if ($Service -in @('all', 'worker')) {
    Write-Host 'Stopping the worker can interrupt an in-flight AI call; upstream charges may still apply.'
    Stop-ProjectService 'Chat worker' 'python.exe' $python '-m app.chat_worker'
}
if ($Service -in @('all', 'frontend')) {
    Stop-ProjectService 'Frontend' 'node.exe' $vite '--port 5173' 5173
}
if ($Service -in @('all', 'api')) {
    Stop-ProjectService 'API' 'python.exe' $python '-m uvicorn app.main:app' 8000
}
