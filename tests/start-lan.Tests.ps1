$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
$tokens = $null
$parseErrors = $null
$lanAst = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $root 'start-lan.ps1'), [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'start-lan.ps1 has syntax errors.' }
$resolver = $lanAst.Find({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Resolve-LanAddress'
}, $true)
Invoke-Expression $resolver.Extent.Text
$configure = $lanAst.Find({ param($node)
    $node -is [System.Management.Automation.Language.StringConstantExpressionAst] -and
        $node.Value.StartsWith('import json')
}, $true).Value

Describe 'PowerShell host compatibility' {
    $pwsh = (Get-Command pwsh.exe -ErrorAction Stop).Source
    $handoff = $lanAst.Find({ param($node)
        $node -is [System.Management.Automation.Language.IfStatementAst] -and
            $node.Extent.Text.StartsWith('if ($PSVersionTable.PSEdition')
    }, $true).Extent.Text
    $fixture = Join-Path $TestDrive 'LAN host check'
    $null = New-Item -ItemType Directory -Path $fixture -Force
    $probe = Join-Path $fixture 'start-lan.ps1'
    $tail = '[PSCustomObject]@{ Edition = $PSVersionTable.PSEdition; Address = $Address; Script = $PSCommandPath } | ConvertTo-Json -Compress'
    $prefix = "param([string]`$Address)`r`n`$ErrorActionPreference = 'Stop'`r`n" + $handoff + "`r`n"

    It 'runs once in the Windows host without requiring caller switches' {
        Set-Content -LiteralPath $probe -Value ($prefix + $tail)
        $output = & $pwsh -NoProfile -NonInteractive -File $probe
        $LASTEXITCODE | Should Be 0
        @($output).Count | Should Be 1
        $result = $output | ConvertFrom-Json
        $result.Edition | Should Be 'Desktop'
        $result.Address | Should Be ''
        $result.Script | Should Be $probe
    }
    It 'preserves the explicit address and a script path containing spaces' {
        $output = & $pwsh -NoProfile -NonInteractive -File $probe -Address '192.168.0.63'
        $LASTEXITCODE | Should Be 0
        $result = $output | ConvertFrom-Json
        $result.Edition | Should Be 'Desktop'
        $result.Address | Should Be '192.168.0.63'
        $result.Script | Should Be $probe
    }
    It 'propagates native startup errors instead of reporting success' {
        Set-Content -LiteralPath $probe -Value ($prefix + "throw 'synthetic-native-startup-failure'")
        $savedPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $output = & $pwsh -NoProfile -NonInteractive -File $probe 2>&1
            $LASTEXITCODE | Should Not Be 0
            ($output -join "`n") | Should Match 'synthetic-native-startup-failure'
            ($output -join "`n") | Should Match 'LAN startup failed in Windows PowerShell'
        } finally {
            $ErrorActionPreference = $savedPreference
        }
    }
}

Describe 'LAN address selection' {
    Mock Get-NetIPConfiguration {
        [PSCustomObject]@{
            IPv4DefaultGateway = '192.168.0.1'
            NetAdapter = [PSCustomObject]@{ Status = 'Up' }
            IPv4Address = [PSCustomObject]@{ IPAddress = '192.168.0.63' }
        }
    }
    Mock Get-NetIPAddress { [PSCustomObject]@{ AddressState = 'Preferred' } }

    It 'uses the single connected IPv4 address' {
        Resolve-LanAddress '' | Should Be '192.168.0.63'
    }
    It 'requires an explicit address when multiple networks are connected' {
        Mock Get-NetIPConfiguration {
            foreach ($ip in @('192.168.0.63', '10.0.0.3')) {
                [PSCustomObject]@{
                    IPv4DefaultGateway = 'gateway'
                    NetAdapter = [PSCustomObject]@{ Status = 'Up' }
                    IPv4Address = [PSCustomObject]@{ IPAddress = $ip }
                }
            }
        }
        { Resolve-LanAddress '' } | Should Throw
        Resolve-LanAddress '192.168.0.63' | Should Be '192.168.0.63'
    }
    It 'rejects invalid, loopback, wildcard, link-local and multicast addresses' {
        foreach ($ip in @('not-an-ip', '192.168.0.999', '127.0.0.1', '0.0.0.0', '169.254.1.2', '224.0.0.1')) {
            { Resolve-LanAddress $ip } | Should Throw
        }
    }
    It 'rejects an address not assigned to this computer' {
        Mock Get-NetIPAddress { @() }
        { Resolve-LanAddress '192.168.0.99' } | Should Throw
    }
}

Describe 'HTTP trial configuration' {
    It 'adds missing HTTP settings to an LF file without changing its other values' {
        $path = Join-Path $TestDrive 'minimal.env'
        $original = "# unchanged`nAI_ENCRYPTION_KEY=FAKE_KEY"
        [IO.File]::WriteAllText($path, $original, (New-Object Text.UTF8Encoding $false))
        $savedPythonPath = $env:PYTHONPATH
        $env:PYTHONPATH = Join-Path $root 'backend'
        try {
            $null = $configure | & $python - $path 'http://10.0.0.8:5173'
            $LASTEXITCODE | Should Be 0
            $body = [IO.File]::ReadAllText($path)
            $body.StartsWith($original + "`n") | Should Be $true
            $body | Should Match 'http://127.0.0.1:5173'
            $body | Should Match 'http://localhost:5173'
            $body | Should Match 'http://10.0.0.8:5173'
            $body | Should Match 'AUTH_COOKIE_SECURE=false'
            $body.Contains("`r") | Should Be $false
        } finally {
            $env:PYTHONPATH = $savedPythonPath
        }
    }
    It 'preserves unrelated settings and BOM, merges origins, and is repeatable' {
        $path = Join-Path $TestDrive '.env'
        $original = "# preserved comment`r`nDATABASE_URL=postgresql+psycopg://user:FAKE_PASSWORD@host/db`r`nAI_ENCRYPTION_KEY=FAKE_KEY`r`nAUTH_ALLOWED_ORIGINS=['https://example.invalid']`r`nAUTH_COOKIE_SECURE=true`r`n"
        # dotenv JSON uses double quotes.
        $original = $original.Replace("['https://example.invalid']", '["https://example.invalid"]')
        [IO.File]::WriteAllText($path, $original, (New-Object Text.UTF8Encoding $true))
        $savedPythonPath = $env:PYTHONPATH
        $env:PYTHONPATH = Join-Path $root 'backend'
        try {
            $output = $configure | & $python - $path 'http://192.168.0.63:5173'
            $LASTEXITCODE | Should Be 0
            $output | Should Not Match 'FAKE_PASSWORD|FAKE_KEY'
            $body = [IO.File]::ReadAllText($path)
            $body | Should Match 'AI_ENCRYPTION_KEY=FAKE_KEY'
            $body | Should Match 'DATABASE_URL=postgresql\+psycopg://user:FAKE_PASSWORD@host/db'
            $body | Should Match '# preserved comment'
            $body | Should Match 'AUTH_COOKIE_SECURE=false'
            $body | Should Match 'AUTH_ALLOWED_ORIGINS=\["https://example.invalid","http://192.168.0.63:5173"\]'
            [IO.File]::ReadAllBytes($path)[0] | Should Be 239
            $null = $configure | & $python - $path 'http://192.168.0.63:5173'
            $LASTEXITCODE | Should Be 0
            [IO.File]::ReadAllText($path) | Should Be $body
        } finally {
            $env:PYTHONPATH = $savedPythonPath
        }
    }
}

Describe 'Frontend mode switching' {
    $fixture = Join-Path $TestDrive 'project'
    $null = New-Item -ItemType Directory -Path (Join-Path $fixture 'frontend\node_modules\vite\bin') -Force
    Copy-Item (Join-Path $root 'start-dev.ps1') (Join-Path $fixture 'start-dev.ps1')
    Set-Content (Join-Path $fixture 'frontend\node_modules\vite\bin\vite.js') ''
    Set-Content (Join-Path $fixture 'stop-dev.ps1') 'param($Service) Set-Content (Join-Path $PSScriptRoot "stopped") $Service'
    $nodePath = (Get-Command node.exe).Source
    $vitePath = Join-Path $fixture 'frontend\node_modules\vite\bin\vite.js'
    Mock powershell.exe {
        [PSCustomObject]@{ ProcessId = 123; CommandLine = "$nodePath $vitePath --port 5173" } | ConvertTo-Json -Compress
    }
    Mock Invoke-WebRequest { [PSCustomObject]@{ StatusCode = 200 } }
    Mock Start-Process { [PSCustomObject]@{ Id = 456 } }
    Mock Get-NetTCPConnection { [PSCustomObject]@{ LocalAddress = '127.0.0.1'; OwningProcess = 123 } }

    It 'switches the owned loopback frontend to LAN without restarting backend services' {
        & (Join-Path $fixture 'start-dev.ps1') -Service frontend -Lan
        Get-Content (Join-Path $fixture 'stopped') | Should Be 'frontend'
        Assert-MockCalled Start-Process -Exactly 1 -Scope It -ParameterFilter {
            $FilePath -eq $nodePath -and $ArgumentList -contains '0.0.0.0' -and $WindowStyle -eq 'Hidden'
        }
    }
    It 'reuses an existing LAN frontend' {
        Remove-Item -LiteralPath (Join-Path $fixture 'stopped') -ErrorAction SilentlyContinue
        Mock Get-NetTCPConnection { [PSCustomObject]@{ LocalAddress = '0.0.0.0'; OwningProcess = 123 } }
        & (Join-Path $fixture 'start-dev.ps1') -Service frontend -Lan
        Assert-MockCalled Start-Process -Exactly 0 -Scope It
        Test-Path -LiteralPath (Join-Path $fixture 'stopped') | Should Be $false
    }
    It 'does not stop or start a process when another program owns the port' {
        Mock powershell.exe { '[{"ProcessId":123,"CommandLine":"unrelated-program"}]' }
        { & (Join-Path $fixture 'start-dev.ps1') -Service frontend -Lan } | Should Throw
        Assert-MockCalled Start-Process -Exactly 0 -Scope It
        Test-Path -LiteralPath (Join-Path $fixture 'stopped') | Should Be $false
    }
    It 'keeps the default startup on loopback' {
        Mock Get-NetTCPConnection { @() }
        & (Join-Path $fixture 'start-dev.ps1') -Service frontend
        Assert-MockCalled Start-Process -Exactly 1 -Scope It -ParameterFilter {
            $ArgumentList -contains '127.0.0.1' -and $ArgumentList -notcontains '0.0.0.0'
        }
    }
}
