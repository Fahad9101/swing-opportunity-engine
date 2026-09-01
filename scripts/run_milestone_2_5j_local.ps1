param(
    [string]$SecUserAgent = "",
    [string]$SecContactEmail = "",
    [switch]$SkipInstall,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot ".."))
Set-Location $RepoRoot

$ResultsDir = Join-Path $RepoRoot "validation-results/milestone-2.5j"
$CacheDir = Join-Path $RepoRoot ".cache/soe"
$SecCacheDir = Join-Path $CacheDir "sec"
$VenvDir = Join-Path $RepoRoot ".venv"
$Python = Join-Path $VenvDir "Scripts/python.exe"

New-Item -ItemType Directory -Force -Path $ResultsDir | Out-Null
New-Item -ItemType Directory -Force -Path $SecCacheDir | Out-Null

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )
    Write-Host "`n=== $Label ==="
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path $Python)) {
    Write-Host "Creating Python 3.12 virtual environment..."
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv $VenvDir
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv $VenvDir
    }
    else {
        throw "Python 3.12 was not found. Install Python 3.12, then rerun this script."
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create .venv with Python 3.12."
    }
}

$Version = & $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($Version.Trim() -ne "3.12") {
    throw "SOE requires Python 3.12 for this validation; .venv is Python $Version. Delete .venv and rerun after installing Python 3.12."
}

if (-not $SkipInstall) {
    Invoke-Checked "Install SOE + test dependencies" { & $Python -m pip install -e ".[test]" }
}

# SEC fair-access guidance asks automated clients to declare a User-Agent that
# identifies the application/organization and contains a real contact email.
# Do not persist the email in git; prompt locally unless an explicit User-Agent
# was supplied on the command line.
if ([string]::IsNullOrWhiteSpace($SecUserAgent)) {
    if ([string]::IsNullOrWhiteSpace($SecContactEmail)) {
        $SecContactEmail = Read-Host "SEC requires a declared contact email for automated access. Enter the email to use only for this local run"
    }
    if ($SecContactEmail -notmatch '^[^\s@]+@[^\s@]+\.[^\s@]+$') {
        throw "A valid SEC contact email is required. It is used only in the request User-Agent and is not written to the repository."
    }
    $SecUserAgent = "SwingOpportunityEngine LocalValidation $SecContactEmail"
}
elseif ($SecUserAgent -notmatch '@') {
    throw "SEC_USER_AGENT must include a contact email under SEC fair-access guidance."
}

$env:DATABASE_URL = "sqlite+pysqlite:///./soe_milestone_2_5j_local.db"
$env:PROVIDER_NAME = "free_public"
$env:SEC_USER_AGENT = $SecUserAgent
$env:SEC_COMPANYFACTS_ZIP_PATH = ".cache/soe/sec/companyfacts.zip"
$env:SEC_SUBMISSIONS_ZIP_PATH = ".cache/soe/sec/submissions.zip"
$env:CACHE_DIR = ".cache/soe"
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONPATH = "backend"

Write-Host "`n=== Verify frozen SOE-1.0.0 rules ==="
& git fetch origin main --depth=1
if ($LASTEXITCODE -ne 0) { throw "git fetch origin main failed." }
$HeadRules = (& git rev-parse "HEAD:config/soe_v1_0_rules.yaml").Trim()
$MainRules = (& git rev-parse "origin/main:config/soe_v1_0_rules.yaml").Trim()
if ($LASTEXITCODE -ne 0 -or $HeadRules -ne $MainRules) {
    throw "Frozen SOE rules differ from main. Validation aborted. HEAD=$HeadRules main=$MainRules"
}
Write-Host "Rules blob SHA: $HeadRules"

if (-not $SkipTests) {
    $PreviousProvider = $env:PROVIDER_NAME
    $env:PROVIDER_NAME = "fixture"
    try {
        Invoke-Checked "Run deterministic suite" { & $Python -m pytest }
    }
    finally {
        $env:PROVIDER_NAME = $PreviousProvider
    }
}

Write-Host "`n=== Download/reuse official SEC bulk archives ==="
& $Python -m app.cli_sec_bulk
if ($LASTEXITCODE -ne 0) {
    throw @"
SEC bulk download was denied even with an SEC-compliant declared User-Agent.
Do not continue with a 5,000+ ticker per-company fallback and do not change SOE rules.
If the same network can open the official SEC bulk links in a normal browser, manually save:
  https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip
  -> .cache/soe/sec/companyfacts.zip
  https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip
  -> .cache/soe/sec/submissions.zip
Then rerun this script with -SkipInstall -SkipTests; validated local ZIPs will be reused.
"@
}

$CompanyFacts = Join-Path $RepoRoot ".cache/soe/sec/companyfacts.zip"
$Submissions = Join-Path $RepoRoot ".cache/soe/sec/submissions.zip"
if (-not (Test-Path $CompanyFacts) -or -not (Test-Path $Submissions)) {
    throw "SEC bulk command returned success but one or both required archives are missing."
}
Write-Host "companyfacts.zip: $([math]::Round((Get-Item $CompanyFacts).Length / 1MB, 2)) MB"
Write-Host "submissions.zip: $([math]::Round((Get-Item $Submissions).Length / 1MB, 2)) MB"

$JsonOut = Join-Path $ResultsDir "milestone_2_5j_validation.json"
$MarkdownOut = Join-Path $ResultsDir "MILESTONE_2_5J_REPORT.md"
$LogOut = Join-Path $ResultsDir "milestone_2_5j_validation.log"
$LocalDb = Join-Path $RepoRoot "soe_milestone_2_5j_local.db"

# A prior interrupted local run may have a partially populated validation DB.
# It is disposable validation state only, so start the final run clean while
# keeping the downloaded SEC/Yahoo caches for speed and reproducibility.
if (Test-Path $LocalDb) { Remove-Item -Force $LocalDb }
foreach ($Output in @($JsonOut, $MarkdownOut, $LogOut)) {
    if (Test-Path $Output) { Remove-Item -Force $Output }
}

Write-Host "`n=== Run final Milestone 2.5J full-market validation ==="

# Python logging intentionally writes per-ticker recoverable exceptions to
# stderr. Windows PowerShell 5.1 converts native stderr into ErrorRecord objects;
# with ErrorActionPreference=Stop that incorrectly aborts the scan on the first
# recoverable ticker failure. Merge stderr inside cmd.exe before PowerShell sees
# it so the SOE pipeline can record that ticker failure and continue as designed.
$RunnerBat = Join-Path $env:TEMP "soe_milestone_2_5j_validation.cmd"
@"
@echo off
"$Python" -m app.cli_milestone_2_5j_validation --json-out "$JsonOut" --markdown-out "$MarkdownOut" 2>&1
exit /b %ERRORLEVEL%
"@ | Set-Content -Path $RunnerBat -Encoding ASCII

try {
    & $env:ComSpec /d /c $RunnerBat | Tee-Object -FilePath $LogOut
    $ValidationExit = $LASTEXITCODE
}
finally {
    Remove-Item $RunnerBat -Force -ErrorAction SilentlyContinue
}

if ($ValidationExit -ne 0) {
    throw "Milestone 2.5J validation failed with exit code $ValidationExit. Review $LogOut"
}

Write-Host "`n=== Validation completed ==="
Write-Host "Report: $MarkdownOut"
Write-Host "JSON:   $JsonOut"
Write-Host "Log:    $LogOut"
Write-Host "`nNext: commit only the validation-results/milestone-2.5j outputs and push this branch so the results can be independently reviewed before merge."
Write-Host "  git add validation-results/milestone-2.5j"
Write-Host "  git commit -m 'Record final Milestone 2.5J full-market validation'"
Write-Host "  git push origin milestone-2.5j-free-data-hardening"
