# Build VHS-Sat Lite for Windows.
# Requirements: Python 3.10+, internet for ffmpeg download.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$Version = "0.3.0"

# ---------- 1. PyInstaller ----------
if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Host "==> Installing PyInstaller..."
    pip install pyinstaller
}

# ---------- 2. FFmpeg ----------
if (-not (Test-Path "vendor/ffmpeg/ffmpeg.exe")) {
    Write-Host "==> Downloading ffmpeg..."
    New-Item -ItemType Directory -Path "vendor" -Force | Out-Null
    $zip = "vendor/ffmpeg.zip"
    $tmp = "vendor/ffmpeg-tmp"
    Invoke-WebRequest `
        -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" `
        -OutFile $zip
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    Expand-Archive $zip -DestinationPath $tmp -Force
    $inner = Get-ChildItem -Path $tmp -Filter "ffmpeg-*-essentials_build" -Directory |
             Select-Object -First 1
    if (-not $inner) { throw "ffmpeg archive structure unexpected" }
    New-Item -ItemType Directory -Path "vendor/ffmpeg" -Force | Out-Null
    Copy-Item (Join-Path $inner.FullName "bin/ffmpeg.exe")  "vendor/ffmpeg/"
    Copy-Item (Join-Path $inner.FullName "bin/ffprobe.exe") "vendor/ffmpeg/"
    Remove-Item -Recurse -Force $tmp, $zip
}

# ---------- 3. PyInstaller build ----------
Write-Host "==> Building .exe..."
pyinstaller --clean --noconfirm vhs-sat-lite.spec

# ---------- 4. Dist: bin/ + config.example.yaml + README ----------
$dist = "dist/VHS-Sat-Lite"
New-Item -ItemType Directory -Path "$dist/bin" -Force | Out-Null
Copy-Item "vendor/ffmpeg/ffmpeg.exe"  "$dist/bin/"
Copy-Item "vendor/ffmpeg/ffprobe.exe" "$dist/bin/"
Copy-Item "config.example.yaml"        "$dist/"
if (Test-Path "README-LITE.txt") {
    Copy-Item "README-LITE.txt" "$dist/"
}

# ---------- 5. Zip ----------
$zipOut = "dist/VHS-Sat-Lite-$Version-win64.zip"
if (Test-Path $zipOut) { Remove-Item $zipOut }
Compress-Archive -Path "$dist/*" -DestinationPath $zipOut -Force

Write-Host ""
Write-Host "Done: $zipOut"
$sizeMb = [math]::Round((Get-Item $zipOut).Length / 1MB, 1)
Write-Host "Size: $sizeMb MB"