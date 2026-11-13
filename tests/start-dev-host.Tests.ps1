$root = Split-Path $PSScriptRoot -Parent
$pwsh = (Get-Command pwsh.exe -ErrorAction Stop).Source
$windowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

function New-HostProbe([string]$name, [string]$handoff) {
    $directory = Join-Path $TestDrive $name
    $null = New-Item -ItemType Directory -Path $directory -Force
    $script = Join-Path $directory 'probe script with spaces.ps1'
    Set-Content -LiteralPath $script -Value @"
param(
    [ValidateSet('all', 'api', 'worker', 'frontend')]
    [string]`$Service = 'all',
    [switch]`$Lan
)
`$ErrorActionPreference = 'Stop'
$handoff
[PSCustomObject]@{
    Edition = `$PSVersionTable.PSEdition
    Service = `$Service
    Lan = `$Lan.IsPresent
    Script = `$PSCommandPath
} | ConvertTo-Json -Compress
"@
    return $script
}

Describe 'start-dev PowerShell host compatibility' {
    It 'executes once in Windows PowerShell and preserves service flags' {
        $handoff = @'
if ($PSVersionTable.PSEdition -eq 'Core') {
    $windowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $startupArguments = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath)
    if ($Service -ne 'all') { $startupArguments += @('-Service', $Service) }
    if ($Lan) { $startupArguments += '-Lan' }
    & $windowsPowerShell @startupArguments
    if ($LASTEXITCODE -ne 0) { throw "handoff failed: $LASTEXITCODE" }
    return
}
'@
        $script = New-HostProbe 'start-dev' $handoff
        $output = & $pwsh -NoProfile -NonInteractive -File $script -Service frontend -Lan
        $LASTEXITCODE | Should Be 0
        @($output).Count | Should Be 1
        $result = $output | ConvertFrom-Json
        $result.Edition | Should Be 'Desktop'
        $result.Service | Should Be 'frontend'
        $result.Lan | Should Be $true
        $result.Script | Should Be $script
    }

    It 'propagates a native child failure' {
        $handoff = @'
if ($PSVersionTable.PSEdition -eq 'Core') {
    $windowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    & $windowsPowerShell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $PSCommandPath
    if ($LASTEXITCODE -ne 0) { throw "Development startup failed in Windows PowerShell (exit $LASTEXITCODE). See the error above." }
    return
}
throw 'synthetic-start-dev-failure'
'@
        $script = New-HostProbe 'start-dev-failure' $handoff
        $savedPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $output = & $pwsh -NoProfile -NonInteractive -File $script 2>&1
            $LASTEXITCODE | Should Not Be 0
            ($output -join "`n") | Should Match 'synthetic-start-dev-failure'
            ($output -join "`n") | Should Match 'Development startup failed in Windows PowerShell'
        } finally {
            $ErrorActionPreference = $savedPreference
        }
    }
}

Describe 'stop-dev PowerShell host compatibility' {
    It 'executes once in Windows PowerShell and preserves service flags' {
        $handoff = @'
if ($PSVersionTable.PSEdition -eq 'Core') {
    $windowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $startupArguments = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath)
    if ($Service -ne 'all') { $startupArguments += @('-Service', $Service) }
    & $windowsPowerShell @startupArguments
    if ($LASTEXITCODE -ne 0) { throw "handoff failed: $LASTEXITCODE" }
    return
}
'@
        $script = New-HostProbe 'stop-dev' $handoff
        $output = & $pwsh -NoProfile -NonInteractive -File $script -Service worker
        $LASTEXITCODE | Should Be 0
        @($output).Count | Should Be 1
        $result = $output | ConvertFrom-Json
        $result.Edition | Should Be 'Desktop'
        $result.Service | Should Be 'worker'
        $result.Lan | Should Be $false
        $result.Script | Should Be $script
    }
}

Describe 'stop-dev LAN process cleanup' {
    It 'uses a process-tree kill and waits for the owned port to close' {
        $source = Get-Content (Join-Path $root 'stop-dev.ps1') -Raw
        $source | Should Match 'taskkill\.exe'
        $source | Should Match "-Wait"
        $source | Should Match 'Get-NetTCPConnection -LocalPort \$port'
        $source | Should Match 'did not stop'
    }
}
