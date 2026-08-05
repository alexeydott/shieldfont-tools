param(
    [string]$BindHost = "127.0.0.1",
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,
    [string]$ProjectRoot = "",
    [string]$FontsRoot = ".fonts"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$root = if ($ProjectRoot) {
    (Resolve-Path $ProjectRoot).Path
} else {
    $repoRoot
}
$null = New-Item -ItemType Directory -Path (Join-Path $root $FontsRoot) -Force
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

$logDirectory = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$logPath = Join-Path $logDirectory "shieldfont-server-debug.log"

Set-Location $repoRoot
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    if (-not (Test-Path (Join-Path $root "shieldfont.yml"))) {
        Write-Host "shieldfont.yml was not found; creating a project template."
        & $python -m shieldfont.presentation.cli.main `
            --verbose `
            --log-format text `
            init `
            $root 2>&1 | Tee-Object -FilePath $logPath
        if ($LASTEXITCODE -ne 0) {
            throw "ShieldFont project initialization failed with exit code $LASTEXITCODE."
        }
    }

    Write-Host "Starting ShieldFont debug server at http://${BindHost}:${Port}/"
    Write-Host "Project root: $root"
    Write-Host "Debug log: $logPath"
    & $python -m shieldfont.presentation.cli.main `
        --verbose `
        --log-format text `
        serve `
        --project-root $root `
        --host $BindHost `
        --port $Port `
        --fonts-root $FontsRoot 2>&1 | Tee-Object -FilePath $logPath -Append
    exit $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
