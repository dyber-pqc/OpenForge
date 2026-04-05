#Requires -Version 5.1
<#
.SYNOPSIS
    Install OpenForge EDA on Windows.

.DESCRIPTION
    Downloads and installs OpenForge EDA Python packages and Rust tool binaries.
    Optionally installs the MSI package if available.

.PARAMETER Version
    Version to install. Defaults to "latest".

.PARAMETER InstallDir
    Installation directory for Rust binaries. Defaults to "$env:LOCALAPPDATA\OpenForge\bin".

.PARAMETER WithDocker
    Also pull Docker images for EDA tools.

.PARAMETER NoRust
    Skip Rust binary installation.

.PARAMETER UseMsi
    Download and run the MSI installer instead of pip-based install.

.EXAMPLE
    irm https://raw.githubusercontent.com/dyber-pqc/OpenForge/main/installer/scripts/install.ps1 | iex
    .\install.ps1 -Version "0.1.0" -WithDocker
#>

[CmdletBinding()]
param(
    [string]$Version = "latest",
    [string]$InstallDir = "$env:LOCALAPPDATA\OpenForge\bin",
    [switch]$WithDocker,
    [switch]$NoRust,
    [switch]$UseMsi
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$GitHubRepo = "dyber-pqc/OpenForge"
$GitHubApi  = "https://api.github.com/repos/$GitHubRepo"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "  [OK] $Message" -ForegroundColor Green
}

function Write-Warn([string]$Message) {
    Write-Host "  [WARN] $Message" -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Check prerequisites
# ---------------------------------------------------------------------------
Write-Step "Checking prerequisites"

# Python 3.12+
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    $python = Get-Command python3 -ErrorAction SilentlyContinue
}
if (-not $python) {
    Write-Error @"
Python not found. Install Python 3.12+ from https://www.python.org/downloads/
Ensure 'Add Python to PATH' is checked during installation.
"@
}

$pyVersion = & $python.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$pyParts = $pyVersion -split '\.'
if ([int]$pyParts[0] -lt 3 -or ([int]$pyParts[0] -eq 3 -and [int]$pyParts[1] -lt 12)) {
    Write-Error "Python 3.12+ required, found $pyVersion"
}
Write-Ok "Python $pyVersion"

$pip = Get-Command pip -ErrorAction SilentlyContinue
if (-not $pip) {
    $pip = Get-Command pip3 -ErrorAction SilentlyContinue
}
if (-not $pip) {
    Write-Error "pip not found. Run: python -m ensurepip"
}
Write-Ok "pip found"

# ---------------------------------------------------------------------------
# Resolve version
# ---------------------------------------------------------------------------
if ($Version -eq "latest") {
    Write-Step "Resolving latest version"
    try {
        $release = Invoke-RestMethod -Uri "$GitHubApi/releases/latest" -Headers @{ Accept = "application/vnd.github+json" }
        $Version = $release.tag_name -replace '^v', ''
    } catch {
        Write-Error "Could not determine latest version. Specify -Version manually."
    }
}
Write-Host "`nInstalling OpenForge EDA v$Version" -ForegroundColor Green

# ---------------------------------------------------------------------------
# Create temp directory
# ---------------------------------------------------------------------------
$TempDir = Join-Path $env:TEMP "openforge-install-$(Get-Random)"
New-Item -ItemType Directory -Path $TempDir | Out-Null

try {
    $ReleaseUrl = "https://github.com/$GitHubRepo/releases/download/v$Version"

    # ---------------------------------------------------------------------------
    # MSI install path
    # ---------------------------------------------------------------------------
    if ($UseMsi) {
        Write-Step "Downloading MSI installer"
        $msiFile = Join-Path $TempDir "OpenForge-EDA-$Version.msi"
        Invoke-WebRequest -Uri "$ReleaseUrl/OpenForge-EDA-$Version.msi" -OutFile $msiFile
        Write-Ok "Downloaded MSI"

        Write-Step "Running MSI installer"
        Start-Process msiexec.exe -ArgumentList "/i `"$msiFile`" /passive /norestart" -Wait
        Write-Ok "MSI installation complete"
        return
    }

    # ---------------------------------------------------------------------------
    # Install Python packages
    # ---------------------------------------------------------------------------
    Write-Step "Installing Python packages"
    $packages = @("openforge_core", "openforge_cli", "openforge_api", "openforge_desktop", "openforge_crypto")

    foreach ($pkg in $packages) {
        $whlName = "${pkg}-${Version}-py3-none-any.whl"
        $whlPath = Join-Path $TempDir $whlName
        try {
            Invoke-WebRequest -Uri "$ReleaseUrl/$whlName" -OutFile $whlPath
        } catch {
            Write-Warn "Could not download $whlName, skipping"
            continue
        }
    }

    $wheels = Get-ChildItem -Path $TempDir -Filter "*.whl"
    if ($wheels.Count -gt 0) {
        & $pip.Source install $wheels.FullName
        Write-Ok "Python packages installed"
    }

    # ---------------------------------------------------------------------------
    # Install Rust binaries
    # ---------------------------------------------------------------------------
    if (-not $NoRust) {
        Write-Step "Installing Rust tools"
        $rustArchive = "openforge-rust-tools-${Version}-windows-x86_64.zip"
        $rustZip = Join-Path $TempDir $rustArchive

        try {
            Invoke-WebRequest -Uri "$ReleaseUrl/$rustArchive" -OutFile $rustZip

            if (-not (Test-Path $InstallDir)) {
                New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
            }

            Expand-Archive -Path $rustZip -DestinationPath $InstallDir -Force
            Write-Ok "Rust tools installed to $InstallDir"
        } catch {
            Write-Warn "Could not download Rust tools for Windows x86_64. Skipping."
        }
    }

    # ---------------------------------------------------------------------------
    # Configure PATH
    # ---------------------------------------------------------------------------
    Write-Step "Configuring PATH"

    # Add Rust tools dir to user PATH
    $userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    $pathUpdated = $false

    if ($userPath -notlike "*$InstallDir*") {
        [Environment]::SetEnvironmentVariable("PATH", "$InstallDir;$userPath", "User")
        $pathUpdated = $true
        Write-Ok "Added $InstallDir to user PATH"
    }

    # Also ensure Python Scripts dir is in PATH
    $pythonScripts = & $python.Source -c "import site; print(site.getusersitepackages().replace('site-packages','Scripts'))"
    if ($userPath -notlike "*$pythonScripts*") {
        $updatedPath = [Environment]::GetEnvironmentVariable("PATH", "User")
        [Environment]::SetEnvironmentVariable("PATH", "$pythonScripts;$updatedPath", "User")
        $pathUpdated = $true
        Write-Ok "Added $pythonScripts to user PATH"
    }

    # Update current session PATH
    $env:PATH = "$InstallDir;$pythonScripts;$env:PATH"

    # ---------------------------------------------------------------------------
    # Docker images (optional)
    # ---------------------------------------------------------------------------
    if ($WithDocker) {
        Write-Step "Pulling Docker images for EDA tools"
        $docker = Get-Command docker -ErrorAction SilentlyContinue
        if ($docker) {
            $images = @(
                "ghcr.io/dyber-pqc/openforge-yosys:latest",
                "ghcr.io/dyber-pqc/openforge-nextpnr:latest",
                "ghcr.io/dyber-pqc/openforge-verilator:latest",
                "ghcr.io/dyber-pqc/openforge-ghdl:latest"
            )
            foreach ($img in $images) {
                Write-Host "  Pulling $img"
                docker pull $img 2>&1 | Out-Null
                if ($LASTEXITCODE -ne 0) { Write-Warn "Failed to pull $img" }
            }
        } else {
            Write-Warn "Docker not found. Install from https://docs.docker.com/desktop/install/windows-install/"
        }
    }

    # ---------------------------------------------------------------------------
    # Verify
    # ---------------------------------------------------------------------------
    Write-Step "Verifying installation"
    try {
        & openforge --help | Out-Null
        Write-Ok "openforge CLI: working"
    } catch {
        Write-Warn "openforge CLI not found. Restart your terminal to update PATH."
    }

    if (-not $NoRust) {
        foreach ($tool in @("openforge-ct", "openforge-sca", "openforge-entropy", "openforge-lint", "openforge-wave")) {
            if (Get-Command "$tool" -ErrorAction SilentlyContinue) {
                Write-Ok "${tool}: installed"
            } else {
                Write-Warn "${tool}: not found in PATH"
            }
        }
    }

    # ---------------------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------------------
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  OpenForge EDA v$Version installed successfully!" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Getting started:"
    Write-Host "    openforge --help           # CLI reference"
    Write-Host "    openforge init my-project  # Create a new project"
    Write-Host "    openforge-desktop          # Launch desktop GUI"
    Write-Host ""
    if ($pathUpdated) {
        Write-Host "  NOTE: Restart your terminal to pick up PATH changes." -ForegroundColor Yellow
        Write-Host ""
    }
    Write-Host "  Documentation: https://github.com/dyber-pqc/OpenForge"
    Write-Host "  Issues:        https://github.com/dyber-pqc/OpenForge/issues"
    Write-Host ""

} finally {
    # Clean up temp directory
    Remove-Item -Path $TempDir -Recurse -Force -ErrorAction SilentlyContinue
}
