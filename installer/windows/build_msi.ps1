#Requires -Version 7.0
<#
.SYNOPSIS
    Build the OpenForge EDA Windows MSI installer.

.DESCRIPTION
    Builds all Python wheels, Rust binaries, and web assets, then stages them
    and invokes WiX toolset to produce a signed MSI package.

.PARAMETER Version
    Product version string (e.g., "0.1.0"). Defaults to reading from pyproject.toml.

.PARAMETER SignCert
    Path to PFX code-signing certificate. If omitted, signing is skipped.

.PARAMETER SignPassword
    Password for the code-signing certificate.

.PARAMETER WixToolsetPath
    Path to WiX Toolset bin directory. Defaults to "C:\Program Files (x86)\WiX Toolset v3.14\bin".

.EXAMPLE
    .\build_msi.ps1 -Version "0.1.0"
    .\build_msi.ps1 -Version "0.1.0" -SignCert "cert.pfx" -SignPassword "secret"
#>

[CmdletBinding()]
param(
    [string]$Version = "",
    [string]$SignCert = "",
    [string]$SignPassword = "",
    [string]$WixToolsetPath = "C:\Program Files (x86)\WiX Toolset v3.14\bin"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$InstallerDir = $PSScriptRoot
$StagingDir = Join-Path $InstallerDir "staging"
$OutputDir = Join-Path $InstallerDir "output"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Assert-Command([string]$Cmd) {
    if (-not (Get-Command $Cmd -ErrorAction SilentlyContinue)) {
        Write-Error "Required command '$Cmd' not found in PATH."
    }
}

# ---------------------------------------------------------------------------
# Resolve version
# ---------------------------------------------------------------------------
if (-not $Version) {
    $pyprojectPath = Join-Path $RepoRoot "packages\core\pyproject.toml"
    $match = Select-String -Path $pyprojectPath -Pattern 'version\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($match) {
        $Version = $match.Matches[0].Groups[1].Value
    } else {
        Write-Error "Cannot determine version. Pass -Version explicitly."
    }
}
Write-Host "Building OpenForge EDA v$Version MSI installer" -ForegroundColor Green

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------
Write-Step "Checking prerequisites"
Assert-Command "python"
Assert-Command "pip"
Assert-Command "cargo"

$candle = Join-Path $WixToolsetPath "candle.exe"
$light  = Join-Path $WixToolsetPath "light.exe"
if (-not (Test-Path $candle)) {
    Write-Error "WiX candle.exe not found at '$candle'. Install WiX Toolset or set -WixToolsetPath."
}

# ---------------------------------------------------------------------------
# Clean staging
# ---------------------------------------------------------------------------
Write-Step "Preparing staging directory"
if (Test-Path $StagingDir) { Remove-Item $StagingDir -Recurse -Force }
New-Item -ItemType Directory -Path $StagingDir | Out-Null
New-Item -ItemType Directory -Path (Join-Path $StagingDir "bin") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $StagingDir "lib") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $StagingDir "pdk") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $StagingDir "web") | Out-Null

if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

# ---------------------------------------------------------------------------
# Build Python wheels
# ---------------------------------------------------------------------------
Write-Step "Building Python wheels"
$wheelDir = Join-Path $StagingDir "lib"
$packages = @("core", "cli", "api", "desktop", "crypto")

foreach ($pkg in $packages) {
    $pkgDir = Join-Path $RepoRoot "packages\$pkg"
    if (Test-Path $pkgDir) {
        Write-Host "  Building $pkg..."
        pip wheel --no-deps --wheel-dir $wheelDir $pkgDir
    }
}

# ---------------------------------------------------------------------------
# Build Rust tools
# ---------------------------------------------------------------------------
Write-Step "Building Rust tools (release)"
Push-Location $RepoRoot
try {
    cargo build --release
} finally {
    Pop-Location
}

$rustBinDir = Join-Path $RepoRoot "target\release"
$rustTools = @("openforge-ct", "openforge-sca", "openforge-entropy", "openforge-lint", "openforge-wave")
foreach ($tool in $rustTools) {
    $src = Join-Path $rustBinDir "$tool.exe"
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $StagingDir "bin\$tool.exe")
        Write-Host "  Staged $tool.exe"
    } else {
        Write-Warning "Rust binary $tool.exe not found, skipping."
    }
}

# ---------------------------------------------------------------------------
# Build CLI launcher
# ---------------------------------------------------------------------------
Write-Step "Creating CLI launcher"
$launcherScript = @"
@echo off
python -m openforge_cli.main %*
"@
$launcherBat = Join-Path $StagingDir "bin\openforge.bat"
Set-Content -Path $launcherBat -Value $launcherScript
# Create a stub exe placeholder - in production use pyinstaller or similar
Copy-Item $launcherBat (Join-Path $StagingDir "bin\openforge.exe") -ErrorAction SilentlyContinue

# ---------------------------------------------------------------------------
# Build web assets
# ---------------------------------------------------------------------------
Write-Step "Building web frontend"
$webDir = Join-Path $RepoRoot "packages\web"
if (Test-Path (Join-Path $webDir "package.json")) {
    Push-Location $webDir
    try {
        npm ci
        npm run build
        $buildOutput = Join-Path $webDir "build"
        if (Test-Path $buildOutput) {
            Copy-Item -Path "$buildOutput\*" -Destination (Join-Path $StagingDir "web") -Recurse
        }
    } finally {
        Pop-Location
    }
}

# ---------------------------------------------------------------------------
# PDK placeholder
# ---------------------------------------------------------------------------
Write-Step "Staging PDK files"
Set-Content -Path (Join-Path $StagingDir "pdk\README.txt") -Value @"
OpenForge EDA - Process Design Kits

PDK files can be installed separately. Visit https://github.com/dyber-pqc/OpenForge
for available PDK packages and installation instructions.
"@

# ---------------------------------------------------------------------------
# Run WiX compiler
# ---------------------------------------------------------------------------
Write-Step "Compiling WiX installer"
$wxsFile = Join-Path $InstallerDir "openforge.wxs"
$wixobjFile = Join-Path $OutputDir "openforge.wixobj"
$msiFile = Join-Path $OutputDir "OpenForge-EDA-$Version.msi"

& $candle $wxsFile `
    -dProductVersion="$Version" `
    -out $wixobjFile `
    -arch x64 `
    -ext WixUIExtension `
    -ext WixUtilExtension

if ($LASTEXITCODE -ne 0) { Write-Error "WiX candle failed." }

& $light $wixobjFile `
    -out $msiFile `
    -ext WixUIExtension `
    -ext WixUtilExtension `
    -spdb

if ($LASTEXITCODE -ne 0) { Write-Error "WiX light failed." }

Write-Host "  MSI created: $msiFile" -ForegroundColor Green

# ---------------------------------------------------------------------------
# Code signing (optional)
# ---------------------------------------------------------------------------
if ($SignCert -and (Test-Path $SignCert)) {
    Write-Step "Signing MSI with certificate"
    $signArgs = @(
        "sign",
        "/f", $SignCert,
        "/tr", "http://timestamp.digicert.com",
        "/td", "sha256",
        "/fd", "sha256"
    )
    if ($SignPassword) {
        $signArgs += @("/p", $SignPassword)
    }
    $signArgs += $msiFile

    & signtool.exe @signArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Signing failed. MSI is unsigned."
    } else {
        Write-Host "  MSI signed successfully." -ForegroundColor Green
    }
} else {
    Write-Host "  No signing certificate provided. MSI is unsigned." -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Step "Build complete"
$msiSize = (Get-Item $msiFile).Length / 1MB
Write-Host "  Output:  $msiFile"
Write-Host "  Size:    $([math]::Round($msiSize, 2)) MB"
Write-Host "  Version: $Version"
