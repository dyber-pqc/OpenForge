<#
.SYNOPSIS
    OpenForge sign-off binaries installer for Windows.

.DESCRIPTION
    Downloads the latest (or pinned) signoff archive, verifies the SHA-256
    checksum, extracts openforge-drc.exe / openforge-lvs.exe / openforge-xrc.exe
    to the install prefix (default: %LOCALAPPDATA%\openforge\bin), and runs
    --version on each binary to confirm.

.PARAMETER Version
    Tag to install (e.g. v0.3.0). Defaults to the latest release.

.PARAMETER Prefix
    Install directory. Defaults to $env:LOCALAPPDATA\openforge\bin.

.EXAMPLE
    irm https://raw.githubusercontent.com/dyber-pqc/OpenForge/main/scripts/install.ps1 | iex

.EXAMPLE
    .\install.ps1 -Version v0.3.0 -Prefix C:\tools\openforge
#>
[CmdletBinding()]
param(
    [string]$Version = $env:OPENFORGE_VERSION,
    [string]$Prefix  = $(if ($env:OPENFORGE_PREFIX) { $env:OPENFORGE_PREFIX } else { Join-Path $env:LOCALAPPDATA "openforge\bin" })
)

$ErrorActionPreference = "Stop"
$Repo = "dyber-pqc/OpenForge"
$Platform = "windows"
$Arch = "x86_64"
$Archive = "openforge-signoff-$Platform-$Arch.zip"

# -- Resolve version ---------------------------------------------------------
if (-not $Version) {
    Write-Host "==> Resolving latest release..."
    $latest = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest"
    $Version = $latest.tag_name
    if (-not $Version) { throw "Could not resolve latest release tag." }
}
Write-Host "==> Installing OpenForge sign-off $Version for $Platform-$Arch into $Prefix"

$Url      = "https://github.com/$Repo/releases/download/$Version/$Archive"
$SumsUrl  = "https://github.com/$Repo/releases/download/$Version/checksums.txt"

# -- Temp workspace ----------------------------------------------------------
$tmp = Join-Path $env:TEMP ("openforge-install-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
try {
    $archivePath = Join-Path $tmp $Archive
    Write-Host "==> Downloading $Url"
    Invoke-WebRequest -Uri $Url -OutFile $archivePath -UseBasicParsing

    # -- Verify checksum -----------------------------------------------------
    Write-Host "==> Verifying SHA-256"
    try {
        $sumsPath = Join-Path $tmp "checksums.txt"
        Invoke-WebRequest -Uri $SumsUrl -OutFile $sumsPath -UseBasicParsing
        $line = Get-Content $sumsPath | Where-Object { $_ -match "  $([regex]::Escape($Archive))$" } | Select-Object -First 1
        if ($line) {
            $expected = ($line -split '\s+')[0].ToLower()
            $actual   = (Get-FileHash -Path $archivePath -Algorithm SHA256).Hash.ToLower()
            if ($expected -ne $actual) {
                throw "Checksum mismatch! expected=$expected actual=$actual"
            }
            Write-Host "    OK ($actual)"
        } else {
            Write-Host "    (no entry for $Archive in checksums.txt - skipping)"
        }
    } catch {
        Write-Warning "Could not verify checksum: $_"
    }

    # -- Extract + install ---------------------------------------------------
    $extractDir = Join-Path $tmp "extract"
    Expand-Archive -Path $archivePath -DestinationPath $extractDir -Force

    if (-not (Test-Path $Prefix)) {
        New-Item -ItemType Directory -Path $Prefix -Force | Out-Null
    }

    foreach ($tool in @("openforge-drc.exe", "openforge-lvs.exe", "openforge-xrc.exe")) {
        $src = Join-Path $extractDir $tool
        $dst = Join-Path $Prefix $tool
        Copy-Item -Path $src -Destination $dst -Force
        Write-Host "    installed $dst"
    }

    # -- Verify --------------------------------------------------------------
    Write-Host "==> Verifying install"
    foreach ($tool in @("openforge-drc.exe", "openforge-lvs.exe", "openforge-xrc.exe")) {
        $exe = Join-Path $Prefix $tool
        try {
            $out = & $exe --version
            Write-Host "    $out"
        } catch {
            Write-Warning "$tool --version failed: $_"
        }
    }

    # -- PATH hint -----------------------------------------------------------
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (($userPath -split ';') -notcontains $Prefix) {
        Write-Host ""
        Write-Host "To use these tools from any shell, add $Prefix to your PATH:"
        Write-Host "    [Environment]::SetEnvironmentVariable('Path', `"`$env:Path;$Prefix`", 'User')"
    }
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Done."
