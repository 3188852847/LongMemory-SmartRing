param(
    [Parameter(Mandatory = $true)][string]$AssetParent,
    [Parameter(Mandatory = $true)][string]$ProxyScript,
    [switch]$ValidateOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$commit = '970cf66906d7c30059faa2704e7002f06b8c3619'
$manifestPath = Join-Path $PSScriptRoot '../../../firmware/smartring_plus/previews/otto/upstream.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.commit -ne $commit -or $manifest.files.Count -ne 23) { throw 'Unexpected upstream manifest' }
$parent = [IO.Path]::GetFullPath($AssetParent)
$destination = Join-Path $parent $commit
if (Test-Path -LiteralPath $destination) { throw "Refusing existing destination: $destination" }
if (-not (Test-Path -LiteralPath $ProxyScript -PathType Leaf)) { throw 'Proxy script missing' }
if ($ValidateOnly) {
    Write-Output "Validated only; no network or writes. Destination: $destination"
    exit 0
}
# No cleanup on failure: retain this run's partial files for diagnosis, never overwrite.
$run = Join-Path $parent ('.partial-' + [Guid]::NewGuid().ToString('N'))
$zipPath = Join-Path $run 'upstream.zip'
$unpacked = Join-Path $run 'unpacked'
$savedProxy = @{}
foreach ($key in @('HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY')) {
    $savedProxy[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
}
$archive = $null
$oldTls = [Net.ServicePointManager]::SecurityProtocol
try {
    . $ProxyScript
    Enable-DevProxy
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    if (Test-Path -LiteralPath $run) { throw 'Unexpected staging collision' }
    [IO.Directory]::CreateDirectory($unpacked) | Out-Null
    $uri = "https://codeload.github.com/txp666/otto-emoji-gif-component/zip/$commit"
    Invoke-WebRequest -Uri $uri -OutFile $zipPath -UseBasicParsing -Proxy $env:HTTPS_PROXY -TimeoutSec 120
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($zipPath)
    $prefix = "otto-emoji-gif-component-$commit/"
    $expandedBytes = 0L
    foreach ($entry in $archive.Entries) {
        if (-not $entry.FullName.StartsWith($prefix, [StringComparison]::Ordinal)) { throw 'Unexpected archive root' }
        $relative = $entry.FullName.Substring($prefix.Length)
        if (-not $relative) { continue }
        if ($relative.Contains('\') -or $relative.Contains(':')) { throw 'Unsafe archive path' }
        $out = [IO.Path]::GetFullPath((Join-Path $unpacked $relative))
        if (-not $out.StartsWith($unpacked + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Archive path traversal' }
        $expandedBytes += $entry.Length
        if ($expandedBytes -gt 32MB) { throw 'Archive exceeds expected size limit' }
        if ($entry.FullName.EndsWith('/')) { [IO.Directory]::CreateDirectory($out) | Out-Null; continue }
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($out)) | Out-Null
        $inputStream = $entry.Open()
        $outputStream = $null
        try {
            $outputStream = [IO.File]::Open($out, [IO.FileMode]::CreateNew)
            $inputStream.CopyTo($outputStream)
        } finally {
            if ($null -ne $outputStream) { $outputStream.Dispose() }
            $inputStream.Dispose()
        }
    }
    $archive.Dispose(); $archive = $null
    foreach ($file in $manifest.files) {
        $path = Join-Path $unpacked $file.path
        $bytes = [IO.File]::ReadAllBytes($path)
        if ($bytes.Length -ne $file.bytes) { throw "Size mismatch: $($file.path)" }
        $header = [Text.Encoding]::ASCII.GetBytes("blob $($bytes.Length)`0")
        $sha = [Security.Cryptography.SHA1]::Create()
        try {
            $sha.TransformBlock($header, 0, $header.Length, $null, 0) | Out-Null
            $sha.TransformFinalBlock($bytes, 0, $bytes.Length) | Out-Null
            $actual = ([BitConverter]::ToString($sha.Hash)).Replace('-', '').ToLowerInvariant()
        } finally { $sha.Dispose() }
        if ($actual -ne $file.git_blob_sha1) { throw "Git blob mismatch: $($file.path)" }
    }
    if (@(Get-ChildItem -LiteralPath (Join-Path $unpacked 'gifs') -Filter '*.gif' -File).Count -ne 21) { throw 'Expected exactly 21 GIFs' }
    # Both paths are resolved siblings under the explicitly supplied resource parent.
    if (Test-Path -LiteralPath $destination) { throw 'Destination appeared during download; refusing overwrite' }
    [IO.Directory]::Move($unpacked, $destination)
    Write-Output "Verified 21 GIFs + LICENSE + component manifest: $destination"
    Write-Output "Archive retained for provenance: $zipPath"
} finally {
    if ($null -ne $archive) { $archive.Dispose() }
    [Net.ServicePointManager]::SecurityProtocol = $oldTls
    foreach ($key in $savedProxy.Keys) {
        [Environment]::SetEnvironmentVariable($key, $savedProxy[$key], 'Process')
    }
}
