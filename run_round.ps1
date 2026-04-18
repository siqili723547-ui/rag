[CmdletBinding(DefaultParameterSetName = "Direct")]
param(
    [Parameter(ParameterSetName = "Direct", Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$Query,

    [Parameter(ParameterSetName = "FromFile", Mandatory = $true)]
    [string]$QueryFile,

    [int]$TopK = 5,
    [int]$SnippetChars = 120,
    [string]$Python,
    [switch]$SkipProbe,
    [switch]$SkipEval,
    [switch]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

function Invoke-ChildScript {
    param(
        [string]$ShellPath,
        [string]$ScriptPath,
        [string[]]$Arguments
    )

    $stdoutFile = [System.IO.Path]::GetTempFileName()
    $stderrFile = [System.IO.Path]::GetTempFileName()

    try {
        $processArgs = @(
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            $ScriptPath
        )
        if ($Arguments) {
            $processArgs += $Arguments
        }

        & $ShellPath @processArgs 1> $stdoutFile 2> $stderrFile
        $exitCode = $LASTEXITCODE

        $stdout = ""
        $stderr = ""
        if ((Get-Item -LiteralPath $stdoutFile).Length -gt 0) {
            $stdout = (Get-Content -LiteralPath $stdoutFile -Raw).Trim()
        }
        if ((Get-Item -LiteralPath $stderrFile).Length -gt 0) {
            $stderr = (Get-Content -LiteralPath $stderrFile -Raw).Trim()
        }

        return [pscustomobject]@{
            exit_code = $exitCode
            stdout    = $stdout
            stderr    = $stderr
        }
    }
    finally {
        Remove-Item -LiteralPath $stdoutFile, $stderrFile -ErrorAction SilentlyContinue
    }
}

function Parse-JsonPayload {
    param(
        [string]$Text
    )

    if (-not $Text) {
        return $null
    }

    try {
        return ($Text | ConvertFrom-Json)
    }
    catch {
        return $null
    }
}

if ($SkipProbe -and $SkipEval) {
    throw "At least one of -SkipProbe / -SkipEval must be false."
}

$backendDir = $PSScriptRoot
$probeScript = Join-Path -Path $backendDir -ChildPath "probe_queries.ps1"
$evalScript = Join-Path -Path $backendDir -ChildPath "run_eval_suite.ps1"

if (-not (Test-Path -LiteralPath $probeScript)) {
    throw "probe_queries.ps1 not found beside this script."
}
if (-not (Test-Path -LiteralPath $evalScript)) {
    throw "run_eval_suite.ps1 not found beside this script."
}

$queries = @()
if (-not $SkipProbe) {
    if ($PSCmdlet.ParameterSetName -eq "FromFile") {
        if (-not (Test-Path -LiteralPath $QueryFile)) {
            throw "Query file not found: $QueryFile"
        }
        $queries = @(
            Get-Content -LiteralPath $QueryFile -Encoding UTF8 |
                ForEach-Object { $_.Trim() } |
                Where-Object { $_ -and -not $_.StartsWith("#") }
        )
    }
    else {
        $queries = @(
            $Query | ForEach-Object { $_.Trim() } | Where-Object { $_ }
        )
    }

    if (-not $queries -or $queries.Count -eq 0) {
        throw "Probe step requires at least one query or -QueryFile."
    }
}

$shellPath = (Get-Process -Id $PID).Path
$overallFailure = $false

$probeResult = $null
if (-not $SkipProbe) {
    $probeArgs = @()
    if ($PSCmdlet.ParameterSetName -eq "FromFile") {
        $probeArgs += @("-QueryFile", $QueryFile)
    }
    else {
        $probeArgs += $queries
    }
    $probeArgs += @(
        "-TopK",
        [string]$TopK,
        "-SnippetChars",
        [string]$SnippetChars
    )
    if ($Python) {
        $probeArgs += @("-Python", $Python)
    }
    if ($Json) {
        $probeArgs += "-Json"
    }

    $probeResult = Invoke-ChildScript -ShellPath $shellPath -ScriptPath $probeScript -Arguments $probeArgs
    if ($probeResult.exit_code -ne 0) {
        $overallFailure = $true
    }
}

$evalResult = $null
if (-not $SkipEval) {
    $evalArgs = @()
    if ($Python) {
        $evalArgs += @("-Python", $Python)
    }
    if ($Json) {
        $evalArgs += "-Json"
    }

    $evalResult = Invoke-ChildScript -ShellPath $shellPath -ScriptPath $evalScript -Arguments $evalArgs
    if ($evalResult.exit_code -ne 0) {
        $overallFailure = $true
    }
}

if ($Json) {
    $payload = [pscustomobject]@{
        backend_dir = $backendDir
        overall_status = if ($overallFailure) { "failed" } else { "ok" }
        probe = if ($probeResult) {
            [pscustomobject]@{
                exit_code = $probeResult.exit_code
                payload    = Parse-JsonPayload -Text $probeResult.stdout
                stderr     = $probeResult.stderr
                raw_stdout = if ((Parse-JsonPayload -Text $probeResult.stdout) -eq $null) { $probeResult.stdout } else { $null }
            }
        } else {
            $null
        }
        eval = if ($evalResult) {
            [pscustomobject]@{
                exit_code = $evalResult.exit_code
                payload    = Parse-JsonPayload -Text $evalResult.stdout
                stderr     = $evalResult.stderr
                raw_stdout = if ((Parse-JsonPayload -Text $evalResult.stdout) -eq $null) { $evalResult.stdout } else { $null }
            }
        } else {
            $null
        }
    }
    $payload | ConvertTo-Json -Depth 10
}
else {
    Write-Host "RAG round runner"
    Write-Host ("Backend: {0}" -f $backendDir)
    Write-Host ""

    if ($probeResult) {
        Write-Host "=== Probe ==="
        if ($probeResult.stdout) {
            Write-Host $probeResult.stdout
        }
        if ($probeResult.stderr) {
            Write-Host "stderr:"
            Write-Host ($probeResult.stderr -replace "(?m)^", "  ")
        }
        Write-Host ""
    }

    if ($evalResult) {
        Write-Host "=== Eval ==="
        if ($evalResult.stdout) {
            Write-Host $evalResult.stdout
        }
        if ($evalResult.stderr) {
            Write-Host "stderr:"
            Write-Host ($evalResult.stderr -replace "(?m)^", "  ")
        }
        Write-Host ""
    }
}

if ($overallFailure) {
    exit 1
}
