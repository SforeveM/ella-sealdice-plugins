param(
    [string]$CoreRoot = "C:\SeaDice",
    [switch]$SkipBackendStart,
    [switch]$SkipScheduledTask,
    [switch]$SkipRestart
)

$ErrorActionPreference = "Stop"
$packageRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$CoreRoot = [IO.Path]::GetFullPath($CoreRoot)
$sumFile = Join-Path $packageRoot "SHA256SUMS"
if (-not (Test-Path -LiteralPath $CoreRoot -PathType Container)) { throw "SeaDice root does not exist: $CoreRoot" }
if (-not (Test-Path -LiteralPath $sumFile -PathType Leaf)) { throw "Package is missing SHA256SUMS." }

foreach ($line in Get-Content -LiteralPath $sumFile -Encoding UTF8) {
    if (-not $line.Trim()) { continue }
    $parts = $line -split '\s{2,}', 2
    if ($parts.Count -ne 2) { throw "Invalid SHA256SUMS line: $line" }
    $relative = $parts[1].Replace('/', [IO.Path]::DirectorySeparatorChar)
    if ($relative.Contains('..')) { throw "Unsafe manifest path: $relative" }
    $source = Join-Path $packageRoot $relative
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Package payload is missing: $relative" }
    $actual = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $parts[0].ToLowerInvariant()) { throw "Package hash mismatch: $relative" }
}
Write-Host "Package hashes verified." -ForegroundColor Green

$scriptDir = Join-Path $CoreRoot "data\default\scripts"
$gameRoot = Join-Path $CoreRoot "bomb-defusal-game"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = Join-Path $CoreRoot "plugin-backups\BombDefusalGame-v1.0.0\$stamp"
New-Item -ItemType Directory -Force -Path $scriptDir, $backup | Out-Null

$oldStop = Join-Path $gameRoot "scripts\Stop-BombDefusalBackend.ps1"
if (-not $SkipBackendStart -and (Test-Path -LiteralPath $oldStop -PathType Leaf)) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $oldStop -CoreRoot $CoreRoot
}
$legacy = Get-ChildItem -LiteralPath $scriptDir -File | Where-Object { $_.Name -match '^BombDefusalGame_v[0-9].*\.js$' }
foreach ($item in $legacy) { Move-Item -LiteralPath $item.FullName -Destination (Join-Path $backup $item.Name) -Force }
if (Test-Path -LiteralPath $gameRoot -PathType Container) {
    Move-Item -LiteralPath $gameRoot -Destination (Join-Path $backup "bomb-defusal-game") -Force
}

New-Item -ItemType Directory -Force -Path $gameRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $packageRoot "backend") -Destination $gameRoot -Recurse -Force
Copy-Item -LiteralPath (Join-Path $packageRoot "scripts") -Destination $gameRoot -Recurse -Force
Copy-Item -LiteralPath (Join-Path $packageRoot "README.md") -Destination $gameRoot -Force
Copy-Item -LiteralPath (Join-Path $packageRoot "requirements.txt") -Destination $gameRoot -Force
$pluginTarget = Join-Path $scriptDir "BombDefusalGame_v1.0.0.js"
Copy-Item -LiteralPath (Join-Path $packageRoot "sealdice\BombDefusalGame_v1.0.0.js") -Destination $pluginTarget -Force

$startScript = Join-Path $gameRoot "scripts\Start-BombDefusalBackend.ps1"
if (-not $SkipBackendStart) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startScript -CoreRoot $CoreRoot -Port 12152
    if ($LASTEXITCODE -ne 0) { throw "Bomb Defusal backend failed to start. Exit code: $LASTEXITCODE" }
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:12152/health" -TimeoutSec 5
    if (-not $health.ok -or $health.service -ne "ella-bomb-defusal" -or $health.version -ne "1.0.0") { throw "Bomb Defusal backend health check failed." }
} else {
    Write-Host "Bomb Defusal backend start skipped for verification."
}

try {
    if ($SkipScheduledTask) { throw [OperationCanceledException]::new("SKIP_TASK") }
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`" -CoreRoot `"$CoreRoot`" -Port 12152"
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    Register-ScheduledTask -TaskName "Ella-BombDefusal-Backend" -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
    Write-Host "Scheduled task installed: Ella-BombDefusal-Backend"
} catch {
    if ($_.Exception.Message -eq "SKIP_TASK") { Write-Host "Scheduled task skipped for verification." }
    else { Write-Host "Warning: scheduled task creation failed. Re-run as Administrator." -ForegroundColor Yellow }
}

$coreExe = Join-Path $CoreRoot "sealdice-core.exe"
if ($SkipRestart) {
    Write-Host "SeaDice restart skipped for verification. Reload JS extensions in WebUI."
} elseif (Test-Path -LiteralPath $coreExe -PathType Leaf) {
    $resolvedExe = [IO.Path]::GetFullPath($coreExe)
    $running = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and [IO.Path]::GetFullPath($_.ExecutablePath) -eq $resolvedExe }
    foreach ($process in $running) { Stop-Process -Id $process.ProcessId -Force; Write-Host "Stopped SeaDice PID: $($process.ProcessId)" }
    Start-Sleep -Seconds 2
    $started = Start-Process -FilePath $resolvedExe -WorkingDirectory $CoreRoot -WindowStyle Hidden -PassThru
    Write-Host "SeaDice started. PID: $($started.Id)" -ForegroundColor Green
} else {
    Write-Host "Warning: sealdice-core.exe was not found. Reload extensions in WebUI." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Bomb Defusal Game v1.0.0 installed successfully." -ForegroundColor Green
Write-Host "SeaDice plugin: $pluginTarget"
Write-Host "Image backend: http://127.0.0.1:12152"
Write-Host "Public images: https://game-api.example.com/images/"
Write-Host "Wallet compatibility: fishingSystemV2 / _pokemon_fish_v1 / coins"
Write-Host "Backup: $backup"
Write-Host "Commands: .bomb (Chinese aliases are documented in README.md)."
