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

# GAM OpenSSL Config flags
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
    "-O3"
)

# Rename conflicting GNU link if in MSYS/Git bash path
if (Test-Path "C:\Program Files\Git\usr\bin\link.exe") {
    Rename-Item -Path "C:\Program Files\Git\usr\bin\link.exe" -NewName "gnulink.exe" -Force -ErrorAction SilentlyContinue
}

Write-Host "Configuring OpenSSL with $perl..."
& $perl ./Configure --libdir=lib --prefix="$InstallDir" @configOpts

Write-Host "Compiling OpenSSL with nmake..."
& nmake

Write-Host "Installing OpenSSL software headers and libraries..."
& nmake install_sw

# Ensure applink.c is available at both include\openssl\applink.c and include\applink.c
if (Test-Path "$InstallDir\include\openssl\applink.c") {
    Copy-Item -Path "$InstallDir\include\openssl\applink.c" -Destination "$InstallDir\include\applink.c" -Force
}

Write-Host "OpenSSL build completed."
& "$InstallDir\bin\openssl.exe" version -a
