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

# Apply GAM patch for Python 3.14 + OpenSSL 4.0 if needed
$pyMajor = $PythonVersion.Split('.')[0]
$pyMinor = $PythonVersion.Split('.')[1]
$osslMajor = $OpenSSLVersion.Split('.')[0]

if ($pyMajor -eq "3" -and $pyMinor -eq "14" -and [int]$osslMajor -ge 4) {
    $patchFile = Join-Path $repoRoot "patches\py314-ossl4.diff"
    if (Test-Path $patchFile) {
        Write-Host "Applying Python 3.14 + OpenSSL 4 compatibility patch: $patchFile"
        git apply --ignore-space-change --ignore-whitespace $patchFile
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "git apply returned $LASTEXITCODE. Trying git patch / patch.exe..."
            $gitPatch = "C:\Program Files\Git\usr\bin\patch.exe"
            if (Test-Path $gitPatch) {
                & $gitPatch -p1 -N -i $patchFile
            }
        }
        $sslSource = Get-Content "Modules\_ssl.c" -Raw
        if ($sslSource -notmatch "OPENSSL_NO_SSL3_METHOD") {
            throw "Failed to apply Python 3.14 + OpenSSL 4 compatibility patch to Modules\_ssl.c"
        }
        Write-Host "Patch verified successfully in Modules\_ssl.c"
    }
}

# 1. Fetch externals excluding OpenSSL (we provide our own freshly built OpenSSL)
Write-Host "Fetching external dependencies (excluding OpenSSL)..."
& PCBuild\get_externals.bat --no-openssl
if ($LASTEXITCODE -ne 0) {
    throw "PCBuild\get_externals.bat failed with exit code $LASTEXITCODE"
}

# Determine architecture strings
if ($Arch -eq "arm64" -or $Arch -eq "ARM64") {
    $osslSub = "arm64"
    $buildArch = "ARM64"
} else {
    $osslSub = "amd64"
    $buildArch = "x64"
}

# 2. Configure MSBuild to point at our custom OpenSSL via CPython's native ExternalProps hook
$resolvedOpenSSL = (Resolve-Path $OpenSSLInstallDir).Path
$propsSrc = (Resolve-Path (Join-Path $repoRoot "patches\windows\openssl.props")).Path

# Ensure applink.c is available in include root if code uses #include <applink.c>
if (Test-Path "$resolvedOpenSSL\include\openssl\applink.c") {
    Copy-Item -Path "$resolvedOpenSSL\include\openssl\applink.c" -Destination "$resolvedOpenSSL\include\applink.c" -Force -ErrorAction SilentlyContinue
}

# Export environment variables for MSBuild
$env:OpenSSLInstallDir = $resolvedOpenSSL
$env:ExternalProps = $propsSrc

# Configure MSBuild response file PCbuild\msbuild.rsp so all MSBuild invocations (including nested/PGO) inherit these properties
$rspLines = @(
    "/p:ExternalProps=`"$propsSrc`"",
    "/p:OpenSSLInstallDir=`"$resolvedOpenSSL`""
)

# If no DLLs in bin, indicate static OpenSSL build to skip _CopySSLDLL target
$hasDlls = (Get-ChildItem -Path "$resolvedOpenSSL\bin\libcrypto*.dll" -ErrorAction SilentlyContinue).Count -gt 0
if (-not $hasDlls) {
    $env:SkipCopySSLDLL = "true"
    $rspLines += "/p:SkipCopySSLDLL=true"
}

Set-Content -Path "PCbuild\msbuild.rsp" -Value $rspLines -Encoding ASCII
Write-Host "Configured MSBuild response file PCbuild\msbuild.rsp with ExternalProps: $propsSrc"

# 4. Build Python
# Ensure Visual Studio modern MSBuild is prioritized over .NET Framework MSBuild
if (-not $env:MSBUILD -or -not (Test-Path $env:MSBUILD)) {
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $vswhere)) {
        $vswhere = "${env:ProgramFiles}\Microsoft Visual Studio\Installer\vswhere.exe"
    }
    if (Test-Path $vswhere) {
        $vsPath = (& $vswhere -latest -products * -property installationPath).Trim()
        $candidate = Join-Path $vsPath "MSBuild\Current\Bin\MSBuild.exe"
        if (Test-Path $candidate) {
            $env:MSBUILD = $candidate
        }
    }
}
if ($env:MSBUILD -and (Test-Path $env:MSBUILD)) {
    Write-Host "Using MSBuild: $env:MSBUILD"
    $msbDir = Split-Path -Parent $env:MSBUILD
    $env:PATH = "$msbDir;$env:PATH"
}

Write-Host "Building Python for $buildArch..."
if ($buildArch -eq "ARM64") {
    & PCBuild\build.bat -c Release -p $buildArch
} else {
    & PCBuild\build.bat -c Release -p $buildArch --pgo
}
if ($LASTEXITCODE -ne 0) {
    throw "PCBuild\build.bat failed with exit code $LASTEXITCODE"
}

# 5. Layout Python into clean installation directory
Write-Host "Creating layout into $InstallDir..."
if (Test-Path "PCBuild\python.bat") {
    & PCBuild\python.bat PC\layout --precompile --preset-default --copy $InstallDir
} elseif (Test-Path ".\python.bat") {
    & .\python.bat PC\layout --precompile --preset-default --copy $InstallDir
} else {
    $pyExe = Join-Path $SourceDir "PCbuild\$osslSub\python.exe"
    & $pyExe PC\layout --precompile --preset-default --copy $InstallDir
}

Write-Host "Python compilation and layout completed successfully."
