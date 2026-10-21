param(
    [string]$CoreRoot = "",
    [int]$Port = 12152
)

$ErrorActionPreference = "Stop"
$gameRoot = Split-Path -Parent $PSScriptRoot
if (-not $CoreRoot) { $CoreRoot = Split-Path -Parent $gameRoot }
$backend = [IO.Path]::GetFullPath((Join-Path $gameRoot "backend\bomb_defusal_backend.py"))
$pidFile = Join-Path $gameRoot "logs\bomb-defusal-backend.pid"
if (-not (Test-Path -LiteralPath $pidFile -PathType Leaf)) { exit 0 }
$pidValue = 0
[void][int]::TryParse((Get-Content -LiteralPath $pidFile -Raw).Trim(), [ref]$pidValue)
if ($pidValue -gt 0) {
    $process = $null
    try { $process = Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue" -ErrorAction Stop } catch { }
    $owned = $process -and $process.CommandLine -like "*$backend*"
    if (-not $owned) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
            $owned = $health.ok -and $health.service -eq "ella-bomb-defusal" -and [int]$health.pid -eq $pidValue
        } catch { }
    }
    if ($owned) {
        Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            if (-not (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 250
        }
        Write-Host "Stopped Bomb Defusal backend PID: $pidValue"
    }
}
Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
