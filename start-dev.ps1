param(
    [ValidateSet('all', 'api', 'worker', 'frontend')]
    [string]$Service = 'all',
    [switch]$Lan
)

$ErrorActionPreference = 'Stop'

if ($PSVersionTable.PSEdition -eq 'Core') {
    $windowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $windowsPowerShell)) {
        throw 'Windows PowerShell is required for the Windows networking cmdlets used by this script.'
    }
    $startupArguments = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath)
    if ($Service -ne 'all') { $startupArguments += @('-Service', $Service) }
    if ($Lan) { $startupArguments += '-Lan' }
    & $windowsPowerShell @startupArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Development startup failed in Windows PowerShell (exit $LASTEXITCODE). See the error above."
    }
    return
}

$root = $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$python = Join-Path $backend '.venv\Scripts\python.exe'
$vite = Join-Path $frontend 'node_modules\vite\bin\vite.js'

$startApi = $Service -in @('all', 'api')
$startWorker = $Service -in @('all', 'worker')
$startFrontend = $Service -in @('all', 'frontend')
$required = @()
if ($startApi -or $startWorker) { $required += $python, (Join-Path $backend '.env') }
if ($startFrontend) { $required += $vite }
foreach ($path in $required) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Missing prerequisite: $path. See README.md for setup."
    }
}
if ($startFrontend) { $node = (Get-Command node.exe -ErrorAction Stop).Source }

function Get-ProcessSnapshot {
    $query = 'Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress'
    @(powershell.exe -NoProfile -NonInteractive -Command $query | ConvertFrom-Json)
}

$processes = Get-ProcessSnapshot

function Test-OwnListener([int]$port, [string]$executable, [string]$signature) {
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        $process = $processes | Where-Object ProcessId -eq $listener.OwningProcess | Select-Object -First 1
        if (-not $process.CommandLine -or
            -not $process.CommandLine.Contains($executable) -or
            -not $process.CommandLine.Contains($signature)) {
            throw "Port $port is already in use by PID $($listener.OwningProcess); nothing was started."
        }
    }
    return $listeners.Count -gt 0
}

if ($startApi) { $apiRunning = Test-OwnListener 8000 $python 'uvicorn app.main:app' }
if ($startFrontend) { $frontendRunning = Test-OwnListener 5173 $node $vite }
if ($startWorker) {
    $workerRunning = @($processes | Where-Object {
        $_.Name -eq 'python.exe' -and
        $_.CommandLine -and $_.CommandLine.Contains($python) -and $_.CommandLine.Contains('-m app.chat_worker')
    }).Count -gt 0
}

if ($Lan -and $startFrontend -and $frontendRunning) {
    $lanListener = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue |
        Where-Object LocalAddress -eq '0.0.0.0'
    if (-not $lanListener) {
        & (Join-Path $root 'stop-dev.ps1') -Service frontend
        $frontendRunning = $false
    }
}

if ($startApi -and -not $apiRunning) {
    $api = Start-Process -FilePath $python -WorkingDirectory $backend -WindowStyle Hidden -PassThru -ArgumentList @(
        '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000', '--no-proxy-headers'
    )
    Write-Host "API started (PID $($api.Id))."
} elseif ($startApi) {
    Write-Host 'API already running on port 8000.'
}

if ($startWorker -and -not $workerRunning) {
    $worker = Start-Process -FilePath $python -WorkingDirectory $backend -WindowStyle Hidden -PassThru -ArgumentList @(
        '-m', 'app.chat_worker'
    )
    Write-Host "Chat worker started (PID $($worker.Id))."
} elseif ($startWorker) {
    Write-Host 'Chat worker already running.'
}

if ($startFrontend -and -not $frontendRunning) {
    $frontendHost = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }
    $web = Start-Process -FilePath $node -WorkingDirectory $frontend -WindowStyle Hidden -PassThru -ArgumentList @(
        "`"$vite`"", '--host', $frontendHost, '--port', '5173', '--strictPort'
    )
    Write-Host "Frontend started (PID $($web.Id))."
} elseif ($startFrontend) {
    Write-Host 'Frontend already running on port 5173.'
}

$checks = @()
if ($startApi) { $checks += @{ Name = 'API'; Url = 'http://127.0.0.1:8000/api/health/ready' } }
if ($startFrontend) { $checks += @{ Name = 'Frontend'; Url = 'http://127.0.0.1:5173/' } }
foreach ($check in $checks) {
    $ready = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing $check.Url -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $ready) { throw "$($check.Name) did not become ready; check the service process and log/." }
}

if ($startFrontend) {
    Write-Host 'Ready: http://127.0.0.1:5173/'
    if ($Lan) { Write-Host 'Frontend also listens on LAN interfaces (HTTP trial).' }
}
