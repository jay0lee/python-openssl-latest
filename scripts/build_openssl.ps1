# build_openssl.ps1 - Windows OpenSSL build matching GAM
param(
    [Parameter(Mandatory=$true)][string]$OpenSSLVersion,
    [Parameter(Mandatory=$true)][string]$SourceDir,
    [Parameter(Mandatory=$true)][string]$InstallDir,
    [string]$Arch = "x64"
)

$ErrorActionPreference = "Stop"

Write-Host "=================================================="
Write-Host "Building OpenSSL $OpenSSLVersion for Windows ($Arch)"
Write-Host "Source:  $SourceDir"
Write-Host "Install: $InstallDir"
Write-Host "=================================================="

New-Item -ItemType Directory -Force -Path $SourceDir | Out-Null
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

if (-not (Test-Path "$SourceDir\Configure")) {
    Write-Host "Cloning OpenSSL source..."
    git clone --filter=blob:none https://github.com/openssl/openssl.git $SourceDir
    Set-Location $SourceDir
    $tagToCheck = "openssl-$OpenSSLVersion"
    $check = git tag -l $tagToCheck
    if ($check) {
        git checkout $tagToCheck
    } else {
        git checkout $OpenSSLVersion
    }
} else {
    Set-Location $SourceDir
}

# Determine Perl executable
$perl = "perl"
if (Test-Path "c:\strawberry\perl\bin\perl.exe") {
    $perl = "c:\strawberry\perl\bin\perl.exe"
}

$isArm64 = ($Arch -ieq "arm64")

# GAM OpenSSL Config flags
# On Windows ARM64 with MSVC (Visual Studio 2026 / MSC 19.51), /O2 and -O3 with /Gs0 trigger a known
# compiler code generation defect where prologue calls __chkstk before saving lr/x30 (Microsoft #11146442 / OpenSSL #26239).
# Using -O1 and stripping /Gs0 completely prevents stack corruption and produces a correct prologue.
$optFlag = if ($isArm64) { "-O1" } else { "-O3" }

$configOpts = @(
    "no-fips",
    "--api=3.0.0",
    "no-docs",
    "no-tls1",
    "no-tls1_1",
    "no-dtls",
    "no-comp",
    "no-srp",
    "no-psk",
    "no-nextprotoneg",
    "no-weak-ssl-ciphers",
    "no-idea",
    "no-seed",
    "no-camellia",
    "no-sm2",
    "no-sm3",
    "no-sm4",
    "no-rc2",
    "no-rc4",
    "no-rc5",
    "no-md2",
    "no-md4",
    "no-cast",
    "no-des",
    "no-shared",
    "no-tests",
    $optFlag
)

# Rename conflicting GNU link if in MSYS/Git bash path
if (Test-Path "C:\Program Files\Git\usr\bin\link.exe") {
    Rename-Item -Path "C:\Program Files\Git\usr\bin\link.exe" -NewName "gnulink.exe" -Force -ErrorAction SilentlyContinue
}

# Remove /Gs0 from Configurations\10-main.conf to prevent MSVC ARM64 stack corruption (Microsoft bug #11146442)
if ($isArm64) {
    $mainConf = Join-Path $SourceDir "Configurations\10-main.conf"
    if (Test-Path $mainConf) {
        $confText = Get-Content $mainConf -Raw
        if ($confText -match "/Gs0\s*") {
            Write-Host "Patching Configurations\10-main.conf: removing /Gs0 to prevent MSVC ARM64 optimizer bug..."
            $confText = $confText -replace "/Gs0\s*", ""
            # Must write as pure ASCII without UTF-8 BOM so Perl parser is not corrupted
            [System.IO.File]::WriteAllText($mainConf, $confText, [System.Text.Encoding]::ASCII)
        }
    }
}

Write-Host "Configuring OpenSSL with $perl..."
& $perl ./Configure --libdir=lib --prefix="$InstallDir" @configOpts
if ($LASTEXITCODE -ne 0) {
    throw "OpenSSL Configure failed with exit code $LASTEXITCODE"
}

if ($isArm64 -and (Test-Path "makefile")) {
    $mf = Get-Content "makefile" -Raw
    if ($mf -match "/Gs0") {
        Write-Host "Stripping remaining /Gs0 flags from generated makefile..."
        $mf = $mf -replace "/Gs0\s*", ""
        [System.IO.File]::WriteAllText((Join-Path (Get-Location) "makefile"), $mf, [System.Text.Encoding]::ASCII)
    }
}

Write-Host "Compiling OpenSSL with nmake..."
& nmake
if ($LASTEXITCODE -ne 0) {
    throw "nmake failed with exit code $LASTEXITCODE"
}

Write-Host "Installing OpenSSL software headers and libraries..."
& nmake install_sw
if ($LASTEXITCODE -ne 0) {
    throw "nmake install_sw failed with exit code $LASTEXITCODE"
}

# Ensure applink.c is available at both include\openssl\applink.c and include\applink.c
if (Test-Path "$InstallDir\include\openssl\applink.c") {
    Copy-Item -Path "$InstallDir\include\openssl\applink.c" -Destination "$InstallDir\include\applink.c" -Force
}

Write-Host "OpenSSL build completed."
& "$InstallDir\bin\openssl.exe" version -a
