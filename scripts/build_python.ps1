# build_python.ps1 - Windows CPython build matching GAM
param(
    [Parameter(Mandatory=$true)][string]$PythonVersion,
    [Parameter(Mandatory=$true)][string]$OpenSSLVersion,
    [Parameter(Mandatory=$true)][string]$OpenSSLInstallDir,
    [Parameter(Mandatory=$true)][string]$SourceDir,
    [Parameter(Mandatory=$true)][string]$InstallDir,
    [string]$Arch = "x64"
)

$ErrorActionPreference = "Stop"

Write-Host "=================================================="
Write-Host "Building Python $PythonVersion with OpenSSL $OpenSSLVersion for Windows ($Arch)"
Write-Host "OpenSSL Install: $OpenSSLInstallDir"
Write-Host "Python Source:   $SourceDir"
Write-Host "Python Install:  $InstallDir"
Write-Host "=================================================="

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir

New-Item -ItemType Directory -Force -Path $SourceDir | Out-Null
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

if (-not (Test-Path "$SourceDir\PCBuild\build.bat")) {
    Write-Host "Cloning CPython source..."
    git clone --filter=blob:none https://github.com/python/cpython.git $SourceDir
    Set-Location $SourceDir
    $tagToCheck = "v$PythonVersion"
    $check = git tag -l $tagToCheck
    if ($check) {
        git checkout $tagToCheck
    } else {
        git checkout $PythonVersion
    }
} else {
    Set-Location $SourceDir
}

# 1. Fetch externals
Write-Host "Fetching external dependencies..."
& PCBuild\get_externals.bat

# 2. Overwrite external OpenSSL with our locally compiled OpenSSL
$osslExtParent = (Get-Item externals\openssl-bin-* | Select-Object -First 1).FullName
Write-Host "External OpenSSL location: $osslExtParent"

if ($Arch -eq "arm64" -or $Arch -eq "ARM64") {
    $osslSub = "arm64"
    $buildArch = "ARM64"
} else {
    $osslSub = "amd64"
    $buildArch = "x64"
}

$targetExtDir = Join-Path $osslExtParent $osslSub
Write-Host "Injecting custom OpenSSL into $targetExtDir"
New-Item -ItemType Directory -Force -Path (Join-Path $targetExtDir "include\openssl") | Out-Null

Copy-Item -Path "$OpenSSLInstallDir\lib\*" -Destination $targetExtDir -Force
Copy-Item -Path "$OpenSSLInstallDir\bin\*" -Destination $targetExtDir -Force
Copy-Item -Path "$OpenSSLInstallDir\include\openssl\*" -Destination (Join-Path $targetExtDir "include\openssl") -Recurse -Force
if (Test-Path "$OpenSSLInstallDir\include\openssl\applink.c") {
    Copy-Item -Path "$OpenSSLInstallDir\include\openssl\applink.c" -Destination (Join-Path $targetExtDir "include") -Force
}

# 3. Apply custom openssl.props and _hashlib.vcxproj from patches
$propsSrc = Join-Path $repoRoot "patches\windows\openssl.props"
$hashlibSrc = Join-Path $repoRoot "patches\windows\_hashlib.vcxproj"
if (Test-Path $propsSrc) {
    Copy-Item -Path $propsSrc -Destination "PCBuild\" -Force -Verbose
}
if (Test-Path $hashlibSrc) {
    Copy-Item -Path $hashlibSrc -Destination "PCBuild\" -Force -Verbose
}

# 4. Build Python
Write-Host "Building Python for $buildArch..."
& PCBuild\build.bat -c Release -p $buildArch --pgo

# 5. Layout Python into clean installation directory
Write-Host "Creating layout into $InstallDir..."
& .\python.bat PC\layout --precompile --preset-default --copy $InstallDir

# 6. Verify Python and OpenSSL
Write-Host "=================================================="
Write-Host "Verifying Python and OpenSSL installation:"
$installedPy = Join-Path $InstallDir "python.exe"
& $installedPy -VV
& $installedPy -c "import ssl; print(f'OpenSSL Version in Python: {ssl.OPENSSL_VERSION}')"
Write-Host "=================================================="
