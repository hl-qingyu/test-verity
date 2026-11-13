param([string]$Address)

$ErrorActionPreference = 'Stop'

# Run Windows networking cmdlets in their native host; some pwsh hosts cannot load CIM.
if ($PSVersionTable.PSEdition -eq 'Core') {
    $windowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $startupArguments = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath)
    if ($Address) { $startupArguments += @('-Address', $Address) }
    & $windowsPowerShell @startupArguments
    if ($LASTEXITCODE -ne 0) { throw "LAN startup failed in Windows PowerShell (exit $LASTEXITCODE). See the error above." }
    return
}

$root = $PSScriptRoot
$backend = Join-Path $root 'backend'
$python = Join-Path $backend '.venv\Scripts\python.exe'

function Resolve-LanAddress([string]$requested) {
    if (-not $requested) {
        $candidates = @(Get-NetIPConfiguration | Where-Object {
            $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up'
        } | ForEach-Object { $_.IPv4Address.IPAddress } | Sort-Object -Unique)
        if ($candidates.Count -ne 1) {
            throw 'Cannot select one LAN IPv4 address. Run .\start-lan.ps1 -Address <this-PC-IPv4>.'
        }
        $requested = $candidates[0]
    }
    $parsed = $null
    if ($requested -notmatch '^\d{1,3}(\.\d{1,3}){3}$' -or
        -not [System.Net.IPAddress]::TryParse($requested, [ref]$parsed) -or
        $parsed.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork -or
        $parsed.GetAddressBytes()[0] -in @(0, 127) -or
        $parsed.GetAddressBytes()[0] -ge 224 -or $requested.StartsWith('169.254.')) {
        throw 'Address must be a usable LAN IPv4 address on this PC.'
    }
    $local = @(Get-NetIPAddress -AddressFamily IPv4 -IPAddress $requested -ErrorAction SilentlyContinue |
        Where-Object AddressState -eq 'Preferred')
    if (-not $local.Count) { throw 'The requested IPv4 address is not active on this PC.' }
    return $parsed.ToString()
}

foreach ($path in @($python, (Join-Path $backend '.env'), (Join-Path $root 'frontend\node_modules\vite\bin\vite.js'))) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing prerequisite: $path. See README.md." }
}
$null = Get-Command node.exe -ErrorAction Stop
$Address = Resolve-LanAddress $Address
$origin = "http://${Address}:5173"

# Preserve credentials and unrelated settings; dotenv's rename can fail on Windows.
$configure = @'
import json
import re
import sys
from pathlib import Path
from app.core.config import Settings

path = Path(sys.argv[1])
origin = sys.argv[2]
try:
    raw = path.read_bytes()
    settings = Settings(_env_file=path)
    origins = list(settings.auth_allowed_origins)
    if origin not in origins:
        origins.append(origin)
    body = raw.decode('utf-8-sig')
    newline = '\r\n' if '\r\n' in body else '\n'
    for key, value in (
        ('AUTH_ALLOWED_ORIGINS', json.dumps(origins, separators=(',', ':'))),
        ('AUTH_COOKIE_SECURE', 'false'),
    ):
        line = key + '=' + value
        pattern = r'(?mi)^[ \t]*(?:export[ \t]+)?' + key + r'[ \t]*=[^\r\n]*'
        if re.search(pattern, body):
            body = re.sub(pattern, lambda _: line, body)
        else:
            body += ('' if not body or body.endswith('\n') else newline) + line + newline
    encoded = body.encode('utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'utf-8')
    if encoded != raw:
        with path.open('r+b') as stream:
            if stream.read() != raw:
                raise RuntimeError('concurrent_configuration_change')
            stream.seek(0)
            stream.write(encoded)
            stream.truncate()
    current = Settings(_env_file=path)
    if origin not in current.auth_allowed_origins or current.auth_cookie_secure:
        raise RuntimeError('environment_override')
except Exception:
    print('Cannot configure HTTP trial. Check .env permissions/format and AUTH_* environment overrides.', file=sys.stderr)
    sys.exit(1)
print('HTTP trial origin configured: ' + origin)
'@
Push-Location $backend
try {
    $configure | & $python - (Join-Path $backend '.env') $origin
    if ($LASTEXITCODE -ne 0) { throw 'LAN configuration failed; services were not changed.' }
} finally {
    Pop-Location
}

& (Join-Path $root 'start-dev.ps1') -Lan
$response = Invoke-WebRequest -UseBasicParsing "$origin/api/health/ready" -TimeoutSec 10
if ($response.StatusCode -ne 200) { throw 'LAN API readiness check failed.' }
try {
    $response = Invoke-WebRequest -UseBasicParsing "$origin/api/auth/password-challenge" -Method Post `
        -Headers @{ Origin = $origin } -ContentType 'application/json' `
        -Body '{"path":"/api/auth/login"}' -TimeoutSec 10
    if ($response.StatusCode -ne 200) { throw 'Origin check failed.' }
} catch {
    throw 'LAN login origin was not accepted. Check API AUTH_* environment overrides and docs/LAN_TRIAL.md.'
}
Write-Host "LAN ready: $origin"
Write-Host 'HTTP trial only. Client browsers need the per-origin secure-context setting; see docs/LAN_TRIAL.md.'
Write-Host 'If another PC cannot connect, check Wi-Fi isolation and Windows Firewall TCP 5173.'
