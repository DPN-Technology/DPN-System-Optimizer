$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$zip = Join-Path $root 'dist/DPN_System_Optimizer_v2.0_Windows.zip'
$checksumFile = "$zip.sha256"
if (-not (Test-Path $zip) -or -not (Test-Path $checksumFile)) { throw 'Package or checksum missing' }
$want = ((Get-Content -LiteralPath $checksumFile -Raw).Trim() -split '\s+')[0]
$got = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($got -ne $want) { throw 'SHA256 mismatch' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($zip)
try {
    $entries = @($archive.Entries | ForEach-Object { $_.FullName.Replace('\','/') })
    foreach ($expected in @('dpn_system_optimizer.py', 'START_DPN_OPTIMIZER.bat', 'dpn_optimizer/cleaner.py', 'dpn_optimizer/gui.py', 'dpn_optimizer/diskmap.py', 'dpn_optimizer/assets/dpn_logo_splash.png')) {
        if (-not @($entries | Where-Object { $_.EndsWith($expected) }).Count) { throw "Package missing $expected" }
    }
    if (@($entries | Where-Object { $_ -match '/(\.git|__pycache__|\.venv)/|\.env$|\.pyc$' }).Count) {
        throw 'Forbidden or generated content in package'
    }
} finally { $archive.Dispose() }
Write-Host "Verified $($entries.Count) package entries and SHA-256 $got"
