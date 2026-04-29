# CropGuard Launcher
# Double-click to start the dashboard. Opens automatically in your browser.

$WSL_APP_PATH = "/home/lorepinillos/sayari-cropguard"
$PORT         = 8050
$URL          = "http://localhost:$PORT"

Write-Host ""
Write-Host "  CropGuard | Sayariy-Resurgiendo" -ForegroundColor Cyan
Write-Host "  Agricultural Stress Monitor — Lambayeque, Peru" -ForegroundColor Gray
Write-Host ""

# Kill any previous instance on this port
$old = Get-Process -Name "python*" -ErrorAction SilentlyContinue |
       Where-Object { $_.CommandLine -like "*app.py*" }
if ($old) {
    $old | Stop-Process -Force
    Write-Host "  Stopped previous instance." -ForegroundColor Yellow
}

# Start the Dash app inside WSL
Write-Host "  Starting dashboard..." -ForegroundColor White
$wslJob = Start-Process -FilePath "wsl.exe" `
    -ArgumentList "-e", "bash", "-c", "cd $WSL_APP_PATH && python3 app/app.py" `
    -WindowStyle Hidden -PassThru

# Wait for the server to be ready (max 20 seconds)
Write-Host "  Waiting for server" -NoNewline -ForegroundColor White
$ready = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    Write-Host "." -NoNewline -ForegroundColor Gray
    try {
        $r = Invoke-WebRequest -Uri $URL -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch {}
}
Write-Host ""

if ($ready) {
    Write-Host "  Dashboard is live at $URL" -ForegroundColor Green
    Start-Process $URL
    Write-Host ""
    Write-Host "  Press ENTER to stop the server." -ForegroundColor Gray
    Read-Host | Out-Null
} else {
    Write-Host "  Server did not start in time. Check WSL is running." -ForegroundColor Red
}

# Cleanup
Stop-Process -Id $wslJob.Id -ErrorAction SilentlyContinue
Write-Host "  CropGuard stopped." -ForegroundColor Gray
