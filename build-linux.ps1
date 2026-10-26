# Build Linux distribution tarball for VHS-Sat (Windows -> Linux, no WSL needed).
# Usage: .\build-linux.ps1 [VERSION]
# Creates: dist/VHS-Sat-<VERSION>-linux.tar.gz

param(
    [string]$Version = "0.3.0"
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$Pkg      = "VHS-Sat-$Version-linux"
$Dist     = "dist"
$Tarball  = "$Dist/$Pkg.tar.gz"
$Staging  = "$Dist/.staging"
$StageDir = "$Staging/$Pkg"

# ---------- checks ----------
if (-not (Test-Path "server.py")) {
    Write-Host "ERROR: server.py not found. Run from project root." -ForegroundColor Red
    exit 1
}

$requiredScripts = @("install-linux.sh", "build-linux.sh", "README-LINUX.txt")
$missing = @()
foreach ($s in $requiredScripts) {
    if (-not (Test-Path $s)) { $missing += $s }
}
if ($missing.Count -gt 0) {
    Write-Host "ERROR: missing required files:" -ForegroundColor Red
    foreach ($m in $missing) { Write-Host "  - $m" -ForegroundColor Red }
    exit 1
}

if (-not (Get-Command tar -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: tar.exe not found. Windows 10 1803+ required." -ForegroundColor Red
    Write-Host "Alternative: use WSL and run ./build-linux.sh there." -ForegroundColor Yellow
    exit 1
}

# ---------- convert CRLF -> LF in .sh (critical for Linux) ----------
$shFiles = @("install-linux.sh", "build-linux.sh")
foreach ($sh in $shFiles) {
    $full = (Resolve-Path $sh).Path
    $content = [System.IO.File]::ReadAllText($full)
    $content = $content -replace "`r`n", "`n"
    [System.IO.File]::WriteAllText($full, $content, [System.Text.UTF8Encoding]::new($false))
}
Write-Host "[+] Converted CRLF -> LF in .sh files"

# ---------- cleanup ----------
if (Test-Path $Staging)  { Remove-Item -Recurse -Force $Staging }
if (Test-Path $Tarball)  { Remove-Item -Force $Tarball }

New-Item -ItemType Directory -Path $StageDir -Force | Out-Null

# ---------- exclude rules ----------
$excludeDirs = @(
    '.git', '.venv', 'venv', 'env',
    '__pycache__', 'dist', 'build', 'vendor',
    'data', 'logs', '.idea', '.vscode'
)

$excludeFiles = @(
    'config.yaml', '*.db', '*.sqlite3', '*.spec',
    'cookies.txt', 'build-lite.ps1', 'build-linux.ps1',
    '*.tar.gz', '*.zip', '*.log'
)

$excludePatterns = @(
    'fix_*.py', 'make_*.py', 'test_*.py', 'check_*.py',
    '*.pyc', '*.pyo'
)

function Should-Exclude {
    param([System.IO.FileSystemInfo]$Item)

    $rel = $Item.FullName.Substring($PSScriptRoot.Length + 1)
    $parts = $rel -split '[\\/]'

    foreach ($p in $parts) {
        if ($excludeDirs -contains $p) { return $true }
    }

    $name = $Item.Name
    foreach ($pat in $excludeFiles) {
        if ($name -like $pat) { return $true }
    }
    foreach ($pat in $excludePatterns) {
        if ($name -like $pat) { return $true }
    }

    return $false
}

# ---------- stage ----------
Write-Host "[+] Staging files..."
$copiedFiles = 0
$copiedDirs  = 0

Get-ChildItem -Path $PSScriptRoot -Recurse -Force | ForEach-Object {
    if (Should-Exclude $_) { return }

    $rel = $_.FullName.Substring($PSScriptRoot.Length + 1)
    $dest = Join-Path $StageDir $rel

    if ($_.PSIsContainer) {
        if (-not (Test-Path $dest)) {
            New-Item -ItemType Directory -Path $dest -Force | Out-Null
            $script:copiedDirs++
        }
    } else {
        $parent = Split-Path $dest -Parent
        if (-not (Test-Path $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        Copy-Item $_.FullName $dest -Force
        $script:copiedFiles++
    }
}

Write-Host ("    Copied {0} files, {1} dirs" -f $copiedFiles, $copiedDirs)

# ---------- sanity checks ----------
$critical = @(
    "server.py",
    "server_lite.py",
    "install-linux.sh",
    "build-linux.sh",
    "requirements.txt",
    "config.example.yaml",
    "README-LINUX.txt",
    "templates/base.html",
    "static/style.css"
)
$missingInStage = @()
foreach ($c in $critical) {
    if (-not (Test-Path (Join-Path $StageDir $c))) { $missingInStage += $c }
}
if ($missingInStage.Count -gt 0) {
    Write-Host "ERROR: critical files missing from staging:" -ForegroundColor Red
    foreach ($m in $missingInStage) { Write-Host "  - $m" -ForegroundColor Red }
    Remove-Item -Recurse -Force $Staging -ErrorAction SilentlyContinue
    exit 1
}

# ---------- create tarball ----------
Write-Host "[+] Creating tarball..."
$tarballFull = (Join-Path (Get-Location) $Tarball)
& tar -czf $tarballFull -C $Staging $Pkg
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: tar failed with exit code $LASTEXITCODE" -ForegroundColor Red
    Remove-Item -Recurse -Force $Staging -ErrorAction SilentlyContinue
    exit 1
}

# cleanup staging (tarball is already in dist/)
Remove-Item -Recurse -Force $Staging -ErrorAction SilentlyContinue

if (-not (Test-Path $Tarball)) {
    Write-Host "ERROR: tarball was not created: $Tarball" -ForegroundColor Red
    exit 1
}

# ---------- summary ----------
$sizeKb = [math]::Round((Get-Item $Tarball).Length / 1KB, 1)
$fileCount = (tar -tzf $Tarball | Measure-Object).Count

Write-Host ""
Write-Host "================================================"
Write-Host (" Done: {0}" -f $Tarball)
Write-Host (" Size: {0} KB" -f $sizeKb)
Write-Host (" Files: {0}" -f $fileCount)
Write-Host ""
Write-Host " Test extract (shows top level):"
Write-Host "   tar -tzf $Tarball | Select-String '^VHS-Sat-[^/]+/[^/]+$' | Select-Object -First 20"
Write-Host ""
Write-Host " Upload to GitHub:"
Write-Host ("   gh release upload v{0} {1} --clobber" -f $Version, $Tarball)
Write-Host "================================================"