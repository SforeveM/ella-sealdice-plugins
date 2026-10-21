param(
    [string]$CoreRoot = "",
    [int]$Port = 12152
)

$ErrorActionPreference = "Stop"
$gameRoot = Split-Path -Parent $PSScriptRoot
if (-not $CoreRoot) { $CoreRoot = Split-Path -Parent $gameRoot }
$CoreRoot = [IO.Path]::GetFullPath($CoreRoot)
$backend = [IO.Path]::GetFullPath((Join-Path $gameRoot "backend\bomb_defusal_backend.py"))
$logDir = Join-Path $gameRoot "logs"
$pidFile = Join-Path $logDir "bomb-defusal-backend.pid"
$publicCache = Join-Path $CoreRoot "base64-api\FileSenderCatalog\cache"
$fileSenderBackend = Join-Path $CoreRoot "base64-api\FileSenderCatalog\file_sender_backend.py"
$publicImageExpected = Test-Path -LiteralPath $fileSenderBackend -PathType Leaf
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (Test-Path -LiteralPath $pidFile -PathType Leaf) {
    $oldPid = 0
    [void][int]::TryParse((Get-Content -LiteralPath $pidFile -Raw).Trim(), [ref]$oldPid)
    if ($oldPid -gt 0) {
        $old = $null
        try { $old = Get-CimInstance Win32_Process -Filter "ProcessId=$oldPid" -ErrorAction Stop } catch { }
        $owned = $old -and $old.CommandLine -like "*$backend*"
        if ($owned) {
            try {
                $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
                if ($health.ok -and $health.service -eq "ella-bomb-defusal" -and $health.version -eq "1.0.0" -and (-not $publicImageExpected -or $health.public_image_enabled)) {
                    Write-Host "Bomb Defusal backend is already running. PID: $oldPid" -ForegroundColor Green
                    exit 0
                }
            } catch { }
            Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
        }
    }
}

$candidates = @(
    (Join-Path $CoreRoot "AstrBot-SeaDiceBridge\.venv\Scripts\python.exe"),
    (Join-Path $CoreRoot "python\python.exe")
)
$pyCommand = Get-Command "python.exe" -ErrorAction SilentlyContinue
if ($pyCommand) { $candidates += $pyCommand.Source }
$launcher = $null
foreach ($candidate in $candidates) {
    if (-not $candidate -or -not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
    & $candidate -c "from PIL import Image" 2>$null
    if ($LASTEXITCODE -eq 0) { $launcher = [IO.Path]::GetFullPath($candidate); break }
}
if (-not $launcher) { throw "No Python runtime with Pillow was found. The AstrBot virtual environment normally provides it." }

$stdout = Join-Path $logDir "bomb-defusal-backend.out.log"
$stderr = Join-Path $logDir "bomb-defusal-backend.err.log"
$env:BOMB_API_TOKEN = if ($env:BOMB_API_TOKEN) { $env:BOMB_API_TOKEN } else { "bomb-local" }
if ($publicImageExpected) {
    New-Item -ItemType Directory -Force -Path $publicCache | Out-Null
    $env:BOMB_PUBLIC_CACHE_DIR = $publicCache
    $env:BOMB_PUBLIC_BASE_URL = "https://game-api.example.com"
} else {
    Remove-Item Env:BOMB_PUBLIC_CACHE_DIR -ErrorAction SilentlyContinue
    Write-Host "Warning: FileSenderCatalog was not found; bomb cards will use local CQ images or text fallback." -ForegroundColor Yellow
}
$process = Start-Process `
    -FilePath $launcher `
    -ArgumentList @("`"$backend`"", "--host", "127.0.0.1", "--port", "$Port") `
    -WorkingDirectory $gameRoot `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -WindowStyle Hidden `
    -PassThru
Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ASCII

$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 500
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
        if ($health.ok -and $health.service -eq "ella-bomb-defusal" -and $health.version -eq "1.0.0") { $ready = $true; break }
    } catch { }
}
if (-not $ready) {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    throw "Bomb Defusal backend did not become ready on port $Port. See $stderr"
}
Write-Host "Bomb Defusal backend is ready. PID: $($process.Id) Port: $Port" -ForegroundColor Green
