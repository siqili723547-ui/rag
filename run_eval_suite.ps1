[CmdletBinding()]
param(
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
        [string]$Name,
        [string]$PythonCommand,
        [string[]]$PythonPrefix,
        [string]$ScriptPath,
        [string[]]$ExtraArgs
    )

    Start-Job -Name $Name -ScriptBlock {
        param(
            [int]$InnerOrder,
            [string]$InnerName,
            [string]$InnerPythonCommand,
            [string[]]$InnerPythonPrefix,
            [string]$InnerScriptPath,
            [string[]]$InnerExtraArgs
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
            if ($InnerPythonPrefix) {
                $arguments += $InnerPythonPrefix
            }
            $arguments += $InnerScriptPath
            $arguments += $InnerExtraArgs

            & $InnerPythonCommand @arguments 1> $stdoutFile 2> $stderrFile
            $exitCode = $LASTEXITCODE

            [pscustomobject]@{
                Order    = $InnerOrder
                Name     = $InnerName
                ExitCode = $exitCode
                Stdout   = (Read-JobText -Path $stdoutFile).Trim()
                Stderr   = (Read-JobText -Path $stderrFile).Trim()
            }
        }
        finally {
            Remove-Item -LiteralPath $stdoutFile, $stderrFile -ErrorAction SilentlyContinue
        }
    } -ArgumentList $Order, $Name, $PythonCommand, $PythonPrefix, $ScriptPath, $ExtraArgs
}

$backendDir = $PSScriptRoot
$retrieveScript = Join-Path -Path $backendDir -ChildPath "retrieve_sections.py"

if (-not (Test-Path -LiteralPath $retrieveScript)) {
    throw "retrieve_sections.py not found beside this script."
}

$pythonInvocation = Resolve-PythonInvocation -PreferredCommand $Python
$datasets = @(
    [pscustomobject]@{
        Order = 1
        Name  = "main_fixed"
        File  = "section_retrieval_eval_cases.json"
        TopK  = 3
    },
    [pscustomobject]@{
        Order = 2
        Name  = "definition_content_head"
        File  = "section_retrieval_eval_cases_definition_content_head.json"
        TopK  = 3
    },
    [pscustomobject]@{
        Order = 3
        Name  = "single_char_definition_boundary"
        File  = "section_retrieval_eval_cases_single_char_definition_boundary.json"
        TopK  = 5
    },
    [pscustomobject]@{
        Order = 4
        Name  = "multi_char_partial_overlap_boundary"
        File  = "section_retrieval_eval_cases_multi_char_partial_overlap_boundary.json"
        TopK  = 3
    },
    [pscustomobject]@{
        Order = 5
        Name  = "opening_definition_bridge_boundary"
        File  = "section_retrieval_eval_cases_opening_definition_bridge_boundary.json"
        TopK  = 3
    },
    [pscustomobject]@{
        Order = 6
        Name  = "concept_family_competition_boundary"
        File  = "section_retrieval_eval_cases_concept_family_competition_boundary.json"
        TopK  = 5
    },
    [pscustomobject]@{
        Order = 7
        Name  = "pure_partial_overlap_residual_boundary"
        File  = "section_retrieval_eval_cases_pure_partial_overlap_residual_boundary.json"
        TopK  = 5
    }
)

$jobs = @()
foreach ($dataset in $datasets) {
    $casePath = Join-Path -Path $backendDir -ChildPath $dataset.File
    if (-not (Test-Path -LiteralPath $casePath)) {
        throw "Verification cases file not found: $($dataset.File)"
    }

    $extraArgs = @(
        "--verify",
        "--verify-cases",
        $casePath,
        "--top-k",
        [string]$dataset.TopK,
        "--json"
    )

    $jobs += Start-RetrieveJob `
        -Order $dataset.Order `
        -Name $dataset.Name `
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

$suiteResults = @()
$hasFailure = $false

foreach ($rawResult in ($rawResults | Sort-Object Order)) {
    $summary = $null
    $parseError = $null

    if ($rawResult.Stdout) {
        try {
            $payload = $rawResult.Stdout | ConvertFrom-Json
            $summary = $payload.summary
        }
        catch {
            $parseError = $_.Exception.Message
        }
    }

    if ($rawResult.ExitCode -ne 0 -or $null -eq $summary) {
        $hasFailure = $true
    }

    $suiteResults += [pscustomobject]@{
        name       = $rawResult.Name
        exit_code  = $rawResult.ExitCode
        status     = if ($rawResult.ExitCode -eq 0 -and $null -ne $summary) { "ok" } else { "failed" }
        case_count = if ($summary) { $summary.case_count } else { $null }
        top_k      = if ($summary) { $summary.top_k } else { $null }
        top1       = if ($summary) { "{0}/{1}" -f $summary.top1_hits, $summary.case_count } else { $null }
        top3       = if ($summary) { "{0}/{1}" -f $summary.top3_hits, $summary.case_count } else { $null }
        topk       = if ($summary) { "{0}/{1}" -f $summary.top_k_hits, $summary.case_count } else { $null }
        stdout     = $rawResult.Stdout
        stderr     = $rawResult.Stderr
        parse_error = $parseError
    }
}

if ($Json) {
    $payload = [pscustomobject]@{
        backend_dir = $backendDir
        overall_status = if ($hasFailure) { "failed" } else { "ok" }
        suites = $suiteResults
    }
    $payload | ConvertTo-Json -Depth 6
}
else {
    Write-Host "Parallel evaluation suite"
    Write-Host ("Backend: {0}" -f $backendDir)
    Write-Host ""

    foreach ($suite in $suiteResults) {
        if ($suite.status -eq "ok") {
            $summaryParts = @()
            $summaryParts += ("Top1 {0}" -f $suite.top1)
            $summaryParts += ("Top3 {0}" -f $suite.top3)
            if ($suite.top_k -ne 3) {
                $summaryParts += ("Top{0} {1}" -f $suite.top_k, $suite.topk)
            }
            Write-Host ("[{0}] {1}: {2}" -f "OK", $suite.name, ($summaryParts -join " | "))
            continue
        }

        Write-Host ("[{0}] {1}: exit_code={2}" -f "FAIL", $suite.name, $suite.exit_code)
        if ($suite.parse_error) {
            Write-Host ("  parse_error: {0}" -f $suite.parse_error)
        }
        if ($suite.stderr) {
            Write-Host "  stderr:"
            Write-Host ($suite.stderr -replace "(?m)^", "    ")
        }
        if ($suite.stdout) {
            Write-Host "  stdout:"
            Write-Host ($suite.stdout -replace "(?m)^", "    ")
        }
    }
}

if ($hasFailure) {
    exit 1
}
