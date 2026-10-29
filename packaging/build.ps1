# Builds the ScreenRec Studio installer locally.
#   .\packaging\build.ps1            -> dist\ScreenRecStudio-<version>-Setup.exe (+ .sha256)
# Needs: Python 3.12 (py launcher or python.exe) and Inno Setup 6. FFmpeg is downloaded if missing.
param([string]$Python = "")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$version = (Select-String -Path "src\screenrec_studio.py" -Pattern '^VERSION = "(.+)"').Matches[0].Groups[1].Value
$repo = (Select-String -Path "src\screenrec_studio.py" -Pattern '^GITHUB_REPO = "(.+?)"').Matches[0].Groups[1].Value
Write-Host "ScreenRec Studio $version ($repo)"

# 1) FFmpeg 8.0.1 essentials (GPL) - same build the app is tested with
$ffVersion = "8.0.1"
if (-not (Test-Path "ffmpeg\ffmpeg.exe")) {
    $zip = Join-Path $env:TEMP "ffmpeg-$ffVersion-essentials_build.zip"
    Invoke-WebRequest "https://github.com/GyanD/codexffmpeg/releases/download/$ffVersion/ffmpeg-$ffVersion-essentials_build.zip" -OutFile $zip
    $tmp = Join-Path $env:TEMP "ffmpeg-extract"
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive $zip $tmp
    New-Item -ItemType Directory -Force ffmpeg | Out-Null
    Copy-Item "$tmp\ffmpeg-$ffVersion-essentials_build\bin\ffmpeg.exe" ffmpeg\
    Copy-Item "$tmp\ffmpeg-$ffVersion-essentials_build\LICENSE" ffmpeg\LICENSE.txt
}

# 2) Clean virtual environment so only the required packages are bundled
if (-not $Python) {
    if (Get-Command py -ErrorAction SilentlyContinue) { $Python = "py" } else { $Python = "python" }
}
if (-not (Test-Path ".venv-build")) {
    if ($Python -eq "py") { & py -3.12 -m venv .venv-build } else { & $Python -m venv .venv-build }
}
$vpy = ".venv-build\Scripts\python.exe"
& $vpy -m pip install --quiet --upgrade pip
& $vpy -m pip install --quiet -r requirements.txt pyinstaller==6.16.0

# 3) PyInstaller -> dist\ScreenRecStudio
& $vpy -m PyInstaller packaging\screenrec_studio.spec --noconfirm --clean --distpath dist --workpath build

# 4) Inno Setup -> dist\ScreenRecStudio-<version>-Setup.exe
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found (winget install JRSoftware.InnoSetup)" }
& $iscc /Q "/DAppVersion=$version" "/DRepoUrl=https://github.com/$repo" packaging\installer.iss
$setup = "dist\ScreenRecStudio-$version-Setup.exe"
(Get-FileHash $setup -Algorithm SHA256).Hash.ToLower() + "  " + (Split-Path $setup -Leaf) | Out-File "$setup.sha256" -Encoding ascii
Get-Item $setup | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }
