# setup_msvc.ps1 - Native MSVC environment activation without Node.js dependencies
param(
    [string]$Arch = "x64"
)

$ErrorActionPreference = "Stop"

$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) {
    $vswhere = "${env:ProgramFiles}\Microsoft Visual Studio\Installer\vswhere.exe"
}

if (-not (Test-Path $vswhere)) {
    throw "vswhere.exe not found at $vswhere"
}

$vsPath = (& $vswhere -latest -products * -property installationPath).Trim()
$vcvars = Join-Path $vsPath "VC\Auxiliary\Build\vcvarsall.bat"
if (-not (Test-Path $vcvars)) {
    throw "vcvarsall.bat not found at $vcvars"
}

$targetArch = if ($Arch -ieq "arm64") { "arm64" } else { "x64" }

# Locate Visual Studio's modern 64-bit MSBuild
$msBuildArch = if ($targetArch -eq "arm64") { "arm64" } else { "amd64" }
$msBuildExe = Join-Path $vsPath "MSBuild\Current\Bin\$msBuildArch\MSBuild.exe"
if (-not (Test-Path $msBuildExe)) {
    $msBuildExe = Join-Path $vsPath "MSBuild\Current\Bin\MSBuild.exe"
}
if (-not (Test-Path $msBuildExe)) {
    $found = Get-ChildItem -Path "$vsPath\MSBuild" -Filter "MSBuild.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { $msBuildExe = $found.FullName }
}

if (Test-Path $msBuildExe) {
    Write-Host "Configured MSBuild: $msBuildExe"
    [System.Environment]::SetEnvironmentVariable("MSBUILD", $msBuildExe)
    if ($env:GITHUB_ENV) {
        "MSBUILD<<__MSVC_ENV_EOF__`n$msBuildExe`n__MSVC_ENV_EOF__" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
    }
}

# Ensure 64-bit hosted toolchain is preferred so compiler pass 2 doesn't hit heap space exhaustion (C1002)
[System.Environment]::SetEnvironmentVariable("PreferredToolArchitecture", $targetArch)
if ($env:GITHUB_ENV) {
    "PreferredToolArchitecture<<__MSVC_ENV_EOF__`n$targetArch`n__MSVC_ENV_EOF__" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
}
Write-Host "Activating MSVC ($targetArch) via $vcvars..."

$origPath = $env:PATH -split ";"
$envOutput = cmd /c "`"$vcvars`" $targetArch && set"
foreach ($line in $envOutput) {
    if ($line -match "^([^=]+)=(.*)$") {
        $k = $matches[1]
        $v = $matches[2]
        if ($k -ieq "PATH") {
            [System.Environment]::SetEnvironmentVariable("PATH", $v)
            if ($env:GITHUB_ENV) {
                "Path<<__MSVC_ENV_EOF__`n$v`n__MSVC_ENV_EOF__" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
            }
            # Extract only the newly added directories from vcvarsall
            $newDirs = @()
            if ($msBuildExe -and (Test-Path (Split-Path -Parent $msBuildExe))) {
                $newDirs += (Split-Path -Parent $msBuildExe)
            }
            foreach ($dir in ($v -split ";")) {
                if ($dir -and ($origPath -notcontains $dir) -and ($newDirs -notcontains $dir) -and (Test-Path $dir)) {
                    $newDirs += $dir
                }
            }
            # Prepend to GITHUB_PATH in reverse order so GitHub Actions prepends them in original order
            [Array]::Reverse($newDirs)
            foreach ($dir in $newDirs) {
                if ($env:GITHUB_PATH) {
                    $dir | Out-File -FilePath $env:GITHUB_PATH -Append -Encoding utf8
                }
            }
        } else {
            [System.Environment]::SetEnvironmentVariable($k, $v)
            if ($env:GITHUB_ENV) {
                "$k<<__MSVC_ENV_EOF__`n$v`n__MSVC_ENV_EOF__" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
            }
        }
    }
}

Write-Host "MSVC environment successfully configured for $targetArch."
