$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$stage = Join-Path $root 'build/DPN_System_Optimizer_v2'
$dist = Join-Path $root 'dist'
$zip = Join-Path $dist 'DPN_System_Optimizer_v2.0_Windows.zip'
if (Test-Path (Join-Path $root 'build')) { Remove-Item (Join-Path $root 'build') -Recurse -Force }
New-Item -ItemType Directory -Path $stage -Force | Out-Null
New-Item -ItemType Directory -Path $dist -Force | Out-Null
# Explicit allowlist prevents uploading .git, CI files, logs, local reports, or secrets.
$rootFiles = @('README.md', 'SECURITY.md', 'LICENSE.txt', 'START_DPN_OPTIMIZER.bat', 'INSTALL_MONITORING.bat', 'dpn_system_optimizer.py', 'requirements.txt')
foreach ($item in $rootFiles) {
    Copy-Item -LiteralPath (Join-Path $root $item) -Destination (Join-Path $stage $item) -ErrorAction Stop
}
$dest = Join-Path $stage 'dpn_optimizer'
New-Item -ItemType Directory -Path $dest -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $root 'dpn_optimizer') -File -Filter '*.py' | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $dest
}
$assets = Join-Path $root 'dpn_optimizer/assets'
if (Test-Path $assets) {
    $assetDest = Join-Path $dest 'assets'
    New-Item -ItemType Directory -Path $assetDest -Force | Out-Null
    Get-ChildItem -LiteralPath $assets -File | Where-Object { $_.Extension -in '.png', '.ico' } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $assetDest
    }
}
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -LiteralPath $stage -DestinationPath $zip -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$zip.sha256" -Value "$hash  DPN_System_Optimizer_v2.0_Windows.zip" -Encoding ascii
Write-Host "Package: $zip"; Write-Host "SHA-256: $hash"
