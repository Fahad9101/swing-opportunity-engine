param(
    [string]$SecUserAgent = "",
    [string]$SecContactEmail = "",
    [string]$BasketFile = "validation/phase_1_1b_preregistered_basket_v1.json",
    [ValidateRange(4, 32)][int]$MaxEventFilings = 16,
    [switch]$SkipInstall,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot ".."))
Set-Location $RepoRoot
$ResultsDir = Join-Path $RepoRoot "validation-results/milestone-1.1b"
$VenvDir = Join-Path $RepoRoot ".venv"
$Python = Join-Path $VenvDir "Scripts/python.exe"
New-Item -ItemType Directory -Force -Path $ResultsDir | Out-Null

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )
    Write-Host "`n=== $Label ==="
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Label failed with exit code $LASTEXITCODE" }
}

$BasketPath = Join-Path $RepoRoot $BasketFile
if (-not (Test-Path $BasketPath)) {
    throw "Preregistered Phase 1.1B basket was not found: $BasketPath"
}
$Basket = Get-Content -Raw -Path $BasketPath | ConvertFrom-Json
if (-not $Basket.entries -or $Basket.entries.Count -lt 20) {
    throw "Preregistered Phase 1.1B basket is invalid or too small."
}
$BasketId = [string]$Basket.basket_id
$BasketHash = (Get-FileHash -Algorithm SHA256 -Path $BasketPath).Hash.ToLowerInvariant()

if (-not (Test-Path $Python)) {
    Write-Host "Creating Python 3.12 virtual environment..."
    if (Get-Command py -ErrorAction SilentlyContinue) { & py -3.12 -m venv $VenvDir }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { & python -m venv $VenvDir }
    else { throw "Python 3.12 was not found." }
    if ($LASTEXITCODE -ne 0) { throw "Unable to create Python 3.12 .venv." }
}

$Version = & $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($Version.Trim() -ne "3.12") { throw "SOE requires Python 3.12; .venv is Python $Version." }

if (-not $SkipInstall) {
    Invoke-Checked "Install SOE + test dependencies" { & $Python -m pip install -e ".[test]" }
}

if ([string]::IsNullOrWhiteSpace($SecUserAgent)) {
    if ([string]::IsNullOrWhiteSpace($SecContactEmail)) {
        $SecContactEmail = Read-Host "SEC requires a declared contact email for automated access. Enter the email to use only for this local run"
    }
    if ($SecContactEmail -notmatch '^[^\s@]+@[^\s@]+\.[^\s@]+$') {
        throw "A valid SEC contact email is required. It is not written to the repository."
    }
    $SecUserAgent = "SwingOpportunityEngine DistressValidation/1.1B $SecContactEmail"
}
elseif ($SecUserAgent -notmatch '@') {
    throw "SEC User-Agent must include a real contact email."
}

$env:SEC_USER_AGENT = $SecUserAgent
$env:SEC_COMPANYFACTS_ZIP_PATH = ".cache/soe/sec/companyfacts.zip"
$env:SEC_SUBMISSIONS_ZIP_PATH = ".cache/soe/sec/submissions.zip"
$env:CACHE_DIR = ".cache/soe"
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONPATH = "backend"

Write-Host "`n=== Verify SOE-1.0.0 remains frozen ==="
& git fetch origin main --depth=1
if ($LASTEXITCODE -ne 0) { throw "git fetch origin main failed." }
foreach ($Path in @("config/soe_v1_0_rules.yaml", "backend/app/core/constants.py")) {
    $HeadBlob = (& git rev-parse "HEAD:$Path").Trim()
    $MainBlob = (& git rev-parse "origin/main:$Path").Trim()
    if ($LASTEXITCODE -ne 0 -or $HeadBlob -ne $MainBlob) {
        throw "SOE-1.0.0 runtime artifact differs from main: $Path"
    }
    Write-Host "$Path blob SHA: $HeadBlob"
}

if (-not $SkipTests) {
    $env:PROVIDER_NAME = "fixture"
    Invoke-Checked "Run deterministic suite" { & $Python -m pytest }
}

$JsonOut = Join-Path $ResultsDir "distress_validation.json"
$MarkdownOut = Join-Path $ResultsDir "PHASE_1_1B_DISTRESS_VALIDATION.md"
$LogOut = Join-Path $ResultsDir "distress_validation.log"
foreach ($Output in @($JsonOut, $MarkdownOut, $LogOut)) {
    if (Test-Path $Output) { Remove-Item -Force $Output }
}

Write-Host "`n=== Run Phase 1.1B targeted SEC distress validation ==="
Write-Host "Validation basket: $BasketId"
Write-Host "Validation basket SHA-256: $BasketHash"
Write-Host "Validation ticker count: $($Basket.entries.Count)"
Write-Host "Max post-periodic 8-K/6-K filings screened per ticker: $MaxEventFilings"
Write-Host "Safe classifications require a completed recent primary-source hard-distress screen."

$RunnerBat = Join-Path $env:TEMP "soe_phase_1_1b_distress_validation.cmd"
@"
@echo off
"$Python" -m app.cli_distress_validation --basket "$BasketPath" --output-dir "$ResultsDir" --max-event-filings $MaxEventFilings 2>&1
exit /b %ERRORLEVEL%
"@ | Set-Content -Path $RunnerBat -Encoding ASCII

try {
    & $env:ComSpec /d /c $RunnerBat | Tee-Object -FilePath $LogOut
    $ValidationExit = $LASTEXITCODE
}
finally {
    Remove-Item $RunnerBat -Force -ErrorAction SilentlyContinue
}

if (-not (Test-Path $JsonOut) -or -not (Test-Path $MarkdownOut)) {
    throw "Distress validation did not produce its required artifacts. Review $LogOut"
}

Write-Host "`n=== Phase 1.1B validation completed ==="
Write-Host "Report: $MarkdownOut"
Write-Host "JSON:   $JsonOut"
Write-Host "Log:    $LogOut"
if ($ValidationExit -eq 0) {
    Write-Host "Exit gate: PASS"
}
elseif ($ValidationExit -eq 2) {
    Write-Warning "Exit gate did not pass yet. This is a valid validation result; do not weaken frozen rules."
}
else {
    throw "Distress validation encountered an execution failure with exit code $ValidationExit. Review $LogOut"
}

Write-Host "`nDo not start Phase 1.1C yet. Push the validation artifacts for independent review:"
Write-Host "  git add validation-results/milestone-1.1b"
Write-Host "  git commit -m 'Record Phase 1.1B live distress validation'"
Write-Host "  git push origin milestone-1.1b-balance-sheet-distress"
