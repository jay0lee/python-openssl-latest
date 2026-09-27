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
Write-Host "Activating MSVC ($targetArch) via $vcvars..."

$envOutput = cmd /c "`"$vcvars`" $targetArch && set"
foreach ($line in $envOutput) {
    if ($line -match "^([^=]+)=(.*)$") {
        $k = $matches[1]
        $v = $matches[2]
        if ($k -ieq "PATH") {
            if ($env:GITHUB_PATH) {
                $v.Split(";") | Where-Object { $_ -and (Test-Path $_) } | ForEach-Object {
                    $_ | Out-File -FilePath $env:GITHUB_PATH -Append -Encoding utf8
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
