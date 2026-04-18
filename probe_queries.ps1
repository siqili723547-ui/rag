[CmdletBinding(DefaultParameterSetName = "Direct")]
param(
    [Parameter(ParameterSetName = "Direct", Mandatory = $true, Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$Query,

    [Parameter(ParameterSetName = "FromFile", Mandatory = $true)]
    [string]$QueryFile,

    [int]$TopK = 5,
    [int]$SnippetChars = 120,
    [string]$Python,
    [switch]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-PythonInvocation {
    param(
        [string]$PreferredCommand
    )

    if ($PreferredCommand) {
        if (Test-Path -LiteralPath $PreferredCommand) {
            return [pscustomobject]@{
                Command = (Resolve-Path -LiteralPath $PreferredCommand).Path
                Prefix  = @()
            }
        }

        if (Get-Command $PreferredCommand -ErrorAction SilentlyContinue) {
            return [pscustomobject]@{
                Command = $PreferredCommand
                Prefix  = @()
            }
        }

        throw "Python command '$PreferredCommand' not found."
    }

    if (Get-Command py -ErrorAction SilentlyContinue) {
        return [pscustomobject]@{
            Command = "py"
            Prefix  = @("-3")
        }
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        return [pscustomobject]@{
            Command = "python"
            Prefix  = @()
        }
    }

    throw "Could not find a Python interpreter. Pass -Python explicitly."
}

function Start-RetrieveJob {
    param(
        [int]$Order,
        [string]$InnerQuery,
        [string]$PythonCommand,
        [string[]]$PythonPrefix,
        [string]$ScriptPath,
        [string[]]$ExtraArgs
    )

    Start-Job -Name ("query-{0}" -f $Order) -ScriptBlock {
        param(
            [int]$JobOrder,
            [string]$JobQuery,
            [string]$JobPythonCommand,
            [string[]]$JobPythonPrefix,
            [string]$JobScriptPath,
            [string[]]$JobExtraArgs
        )

        [Console]::InputEncoding = [System.Text.Encoding]::UTF8
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
        $OutputEncoding = [System.Text.Encoding]::UTF8
        $env:PYTHONIOENCODING = "utf-8"

        function Read-JobText {
            param(
                [string]$Path
            )

            if (-not (Test-Path -LiteralPath $Path)) {
                return ""
            }

            $item = Get-Item -LiteralPath $Path
            if ($item.Length -le 0) {
                return ""
            }

            return (Get-Content -LiteralPath $Path -Raw)
        }

        $stdoutFile = [System.IO.Path]::GetTempFileName()
        $stderrFile = [System.IO.Path]::GetTempFileName()

        try {
            $arguments = @()
            if ($JobPythonPrefix) {
                $arguments += $JobPythonPrefix
            }
            $arguments += $JobScriptPath
            $arguments += $JobExtraArgs

            & $JobPythonCommand @arguments 1> $stdoutFile 2> $stderrFile
            $exitCode = $LASTEXITCODE

            [pscustomobject]@{
                Order    = $JobOrder
                Query    = $JobQuery
                ExitCode = $exitCode
                Stdout   = (Read-JobText -Path $stdoutFile).Trim()
                Stderr   = (Read-JobText -Path $stderrFile).Trim()
            }
        }
        finally {
            Remove-Item -LiteralPath $stdoutFile, $stderrFile -ErrorAction SilentlyContinue
        }
    } -ArgumentList $Order, $InnerQuery, $PythonCommand, $PythonPrefix, $ScriptPath, $ExtraArgs
}

if ($TopK -le 0) {
    throw "-TopK must be a positive integer."
}

if ($SnippetChars -le 0) {
    throw "-SnippetChars must be a positive integer."
}

$queries = @()
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
    throw "No queries to probe."
}

$backendDir = $PSScriptRoot
$retrieveScript = Join-Path -Path $backendDir -ChildPath "retrieve_sections.py"

if (-not (Test-Path -LiteralPath $retrieveScript)) {
    throw "retrieve_sections.py not found beside this script."
}

$pythonInvocation = Resolve-PythonInvocation -PreferredCommand $Python
$jobs = @()

for ($index = 0; $index -lt $queries.Count; $index++) {
    $currentQuery = $queries[$index]
    $extraArgs = @(
        $currentQuery,
        "--top-k",
        [string]$TopK,
        "--snippet-chars",
        [string]$SnippetChars,
        "--json"
    )

    $jobs += Start-RetrieveJob `
        -Order ($index + 1) `
        -InnerQuery $currentQuery `
        -PythonCommand $pythonInvocation.Command `
        -PythonPrefix $pythonInvocation.Prefix `
        -ScriptPath $retrieveScript `
        -ExtraArgs $extraArgs
}

try {
    Wait-Job -Job $jobs | Out-Null
    $rawResults = $jobs | Receive-Job
}
finally {
    $jobs | Remove-Job -Force -ErrorAction SilentlyContinue
}

$parsedResults = @()
$hasFailure = $false

foreach ($rawResult in ($rawResults | Sort-Object Order)) {
    $payload = $null
    $parseError = $null

    if ($rawResult.Stdout) {
        try {
            $payload = $rawResult.Stdout | ConvertFrom-Json
        }
        catch {
            $parseError = $_.Exception.Message
        }
    }

    if ($rawResult.ExitCode -ne 0 -or $null -eq $payload) {
        $hasFailure = $true
    }

    $parsedResults += [pscustomobject]@{
        query       = $rawResult.Query
        exit_code   = $rawResult.ExitCode
        status      = if ($rawResult.ExitCode -eq 0 -and $null -ne $payload) { "ok" } else { "failed" }
        top_k       = if ($payload) { $payload.top_k } else { $TopK }
        results     = if ($payload) { $payload.results } else { @() }
        stdout      = $rawResult.Stdout
        stderr      = $rawResult.Stderr
        parse_error = $parseError
    }
}

if ($Json) {
    $payload = [pscustomobject]@{
        backend_dir = $backendDir
        overall_status = if ($hasFailure) { "failed" } else { "ok" }
        probes = $parsedResults
    }
    $payload | ConvertTo-Json -Depth 8
}
else {
    Write-Host "Parallel query probe"
    Write-Host ("Backend: {0}" -f $backendDir)
    Write-Host ""

    foreach ($probe in $parsedResults) {
        Write-Host ("query: {0}" -f $probe.query)

        if ($probe.status -ne "ok") {
            Write-Host ("  status: failed (exit_code={0})" -f $probe.exit_code)
            if ($probe.parse_error) {
                Write-Host ("  parse_error: {0}" -f $probe.parse_error)
            }
            if ($probe.stderr) {
                Write-Host "  stderr:"
                Write-Host ($probe.stderr -replace "(?m)^", "    ")
            }
            if ($probe.stdout) {
                Write-Host "  stdout:"
                Write-Host ($probe.stdout -replace "(?m)^", "    ")
            }
            Write-Host ""
            continue
        }

        if (-not $probe.results -or $probe.results.Count -eq 0) {
            Write-Host "  no matches"
            Write-Host ""
            continue
        }

        for ($index = 0; $index -lt $probe.results.Count; $index++) {
            $result = $probe.results[$index]
            Write-Host ("  {0}. [{1}] {2} (score={3})" -f ($index + 1), $result.section_id, $result.title, $result.score)
            Write-Host ("     source: {0}" -f $result.source_path)
            Write-Host ("     pdf: {0}-{1}" -f $result.pdf_page_start, $result.pdf_page_end)
            Write-Host ("     reasons: {0}" -f (($result.match_reasons -join ", ")))
            Write-Host ("     snippet: {0}" -f $result.snippet)
        }
        Write-Host ""
    }
}

if ($hasFailure) {
    exit 1
}
