[CmdletBinding()]
param(
    [string]$CoreRoot = 'C:\SeaDice',
    [switch]$VerifyOnly,
    [switch]$PreflightOnly
)
$ErrorActionPreference = 'Stop'
$packageRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\') + '\'
$source = Join-Path $PSScriptRoot 'payload\pokemon.js'
$manifest = Join-Path $PSScriptRoot 'SHA256SUMS.txt'

foreach ($line in Get-Content -LiteralPath $manifest -Encoding UTF8) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    $parts = $line -split '  ', 2
    if ($parts.Count -ne 2 -or $parts[0] -notmatch '^[a-fA-F0-9]{64}$' -or
        [IO.Path]::IsPathRooted($parts[1]) -or $parts[1] -match '(^|[\\/])\.\.([\\/]|$)') { throw 'Invalid package manifest.' }
    $file = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $parts[1]))
    if (-not $file.StartsWith($packageRoot, [StringComparison]::OrdinalIgnoreCase) -or
        -not (Test-Path -LiteralPath $file -PathType Leaf) -or
        (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $parts[0]) { throw ('Package verification failed: ' + $parts[1]) }
}
Write-Host 'Package hashes verified.'
if ($VerifyOnly) { return }

$payloadText = [IO.File]::ReadAllText($source, [Text.Encoding]::UTF8)
if ($payloadText -notmatch '(?m)^\s*//\s*@name\s+门版宝可梦TRPG综合助手\s+v1\.39\.1\s*$' -or
    $payloadText -notmatch '(?m)^\s*//\s*@version\s+1\.39\.1\s*$') { throw 'Unexpected v1.39.1 payload.' }
$CoreRoot = [IO.Path]::GetFullPath($CoreRoot)
$scriptsDir = Join-Path $CoreRoot 'data\default\scripts'
if (-not (Test-Path -LiteralPath $scriptsDir -PathType Container)) { throw ('SeaDice scripts directory not found: ' + $scriptsDir) }

$candidates = @()
foreach ($file in Get-ChildItem -LiteralPath $scriptsDir -File -Filter '*.js') {
    $oldText = [IO.File]::ReadAllText($file.FullName, [Text.Encoding]::UTF8)
    if ($oldText -match '(?m)^\s*//\s*@name\s+门版宝可梦TRPG综合助手(?:\s+v[^\r\n]+)?\s*$' -and
        $oldText.Contains('pokemon_player_data') -and $oldText.Contains('宝可梦伤害')) {
        if ($oldText -notmatch '(?m)^\s*//\s*@version\s+(\d+\.\d+\.\d+)\s*$') { throw ('Unknown installed version: ' + $file.FullName) }
        $installedVersion = [version]$Matches[1]
        if ($installedVersion -gt [version]'1.39.1') { throw ('A newer Pokemon assistant is installed; refusing downgrade: ' + $file.FullName) }
        $candidates += $file.FullName
    }
}
if ($candidates.Count -ne 1) { throw ('Expected exactly one installed Pokemon assistant, found ' + $candidates.Count + '. No files were changed.') }
$target = $candidates[0]
Write-Host ('Pokemon assistant: ' + $target)
if ($PreflightOnly) { Write-Host 'Preflight passed. No files were changed.'; return }

$sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -eq $sourceHash) {
    Write-Host 'Pokemon assistant v1.39.1 is already installed.'
    return
}
$backupDir = Join-Path $CoreRoot ('plugin-backups\PokemonTRPGAssistant-v1.39.1-js-only\' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
$backupFile = Join-Path $backupDir ([IO.Path]::GetFileName($target))
Copy-Item -LiteralPath $target -Destination $backupFile
@{Target=$target; Backup=$backupFile} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backupDir 'restore-map.json') -Encoding UTF8
try {
    Copy-Item -LiteralPath $source -Destination $target -Force
    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $sourceHash) { throw 'Installed file verification failed.' }
} catch {
    Copy-Item -LiteralPath $backupFile -Destination $target -Force
    throw
}
Write-Host ('Backup: ' + $backupFile)
Write-Host 'Pokemon TRPG Assistant v1.39.1 JS-only compatibility update completed.' -ForegroundColor Green
Write-Host 'SeaDice core, private core executable and all backends were not changed.'
Write-Host 'Reload JavaScript extensions in SeaDice WebUI.' -ForegroundColor Yellow
