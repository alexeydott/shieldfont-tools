[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$KeepWork
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BuildDirectory = Join-Path $ProjectRoot "build"
$WorkDirectory = Join-Path $BuildDirectory ".pyinstaller-work"
$SpecDirectory = Join-Path $BuildDirectory ".pyinstaller-spec"
$ExecutablePath = Join-Path $BuildDirectory "shieldfont-generate.exe"
$EntryPoint = Join-Path $ProjectRoot "src\shieldfont\presentation\cli\generate_main.py"
$StaticDirectory = Join-Path $ProjectRoot "src\shieldfont\presentation\web\static"
$VendorPackages = @(
    "@monaco-editor\loader",
    "@vscode\l10n",
    "jsonc-parser",
    "monaco-editor",
    "monaco-languageserver-types",
    "monaco-marker-data-provider",
    "monaco-types",
    "monaco-worker-manager",
    "monaco-yaml",
    "path-browserify",
    "prettier",
    "proxy-disposable",
    "state-local",
    "vscode-languageserver-textdocument",
    "vscode-languageserver-types",
    "vscode-uri",
    "yaml"
)

if (-not (Test-Path -LiteralPath $EntryPoint -PathType Leaf)) {
    throw "CLI entry point was not found: $EntryPoint"
}
if (-not (Test-Path -LiteralPath $StaticDirectory -PathType Container)) {
    throw "Web static directory was not found: $StaticDirectory"
}

$VendorDataArguments = @()
foreach ($package in $VendorPackages) {
    $packageSource = Join-Path $ProjectRoot "node_modules\$package"
    if (-not (Test-Path -LiteralPath $packageSource -PathType Container)) {
        throw "Web vendor package was not found: $packageSource"
    }
    $packageDestination = "shieldfont\presentation\web\bundled_node_modules\$package"
    $VendorDataArguments += @(
        "--add-data",
        "$packageSource;$packageDestination"
    )
}

$Runtime = & $Python -c 'import platform, struct, sys; print("{}|{}|{}|{}.{}".format(platform.system(), platform.machine(), struct.calcsize("P") * 8, sys.version_info.major, sys.version_info.minor))'
if ($LASTEXITCODE -ne 0) {
    throw "Unable to execute Python interpreter '$Python'."
}

$RuntimeParts = $Runtime.Trim().Split("|")
if ($RuntimeParts.Count -ne 4 -or $RuntimeParts[0] -ne "Windows" -or
    $RuntimeParts[1] -notin @("AMD64", "x86_64") -or $RuntimeParts[2] -ne "64") {
    throw "Portable build requires a 64-bit Windows Python interpreter; detected '$($Runtime.Trim())'."
}

& $Python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is missing. Install the optional build dependency with: $Python -m pip install -e `".[portable]`""
}

New-Item -ItemType Directory -Force -Path $BuildDirectory | Out-Null
if (Test-Path -LiteralPath $ExecutablePath) {
    Remove-Item -LiteralPath $ExecutablePath -Force
}

$PyInstallerArguments = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--console",
    "--name", "shieldfont-generate",
    "--paths", (Join-Path $ProjectRoot "src"),
    "--add-data", "$StaticDirectory;shieldfont\presentation\web\static"
)
$PyInstallerArguments += $VendorDataArguments
$PyInstallerArguments += @(
    "--distpath", $BuildDirectory,
    "--workpath", $WorkDirectory,
    "--specpath", $SpecDirectory,
    $EntryPoint
)

& $Python @PyInstallerArguments
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed to create the portable executable."
}
if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
    throw "PyInstaller completed without creating $ExecutablePath."
}

if (-not $KeepWork) {
    foreach ($PathToRemove in @($WorkDirectory, $SpecDirectory)) {
        if (Test-Path -LiteralPath $PathToRemove) {
            Remove-Item -LiteralPath $PathToRemove -Recurse -Force
        }
    }
}

Write-Output "Portable x64 executable: $ExecutablePath"
