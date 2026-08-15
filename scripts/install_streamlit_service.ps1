# Install Streamlit dashboard as a Windows service (survives PowerShell close / reboot).
#
# Run ONCE on the production server as Administrator:
#   cd C:\apps\hospital-chatbot
#   powershell -ExecutionPolicy Bypass -File .\scripts\install_streamlit_service.ps1
#
# Requires NSSM on PATH, or at C:\tools\nssm\nssm.exe / C:\nssm\nssm.exe
# Download: https://nssm.cc/download  (win64\nssm.exe)

$ErrorActionPreference = 'Stop'

$AppRoot = 'C:\apps\hospital-chatbot'
$ServiceName = 'HospitalChatbotDashboard'
$DisplayName = 'Hospital Chatbot Dashboard (Streamlit)'
$Port = 8501

if (-not (Test-Path $AppRoot)) {
    throw "App root not found: $AppRoot"
}

$streamlit = Join-Path $AppRoot 'venv\Scripts\streamlit.exe'
if (-not (Test-Path $streamlit)) {
    $streamlit = Join-Path $AppRoot '.venv\Scripts\streamlit.exe'
}
if (-not (Test-Path $streamlit)) {
    throw 'streamlit.exe not found under venv or .venv'
}

function Find-Nssm {
    $candidates = @(
        (Get-Command nssm -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
        'C:\tools\nssm\nssm.exe',
        'C:\nssm\nssm.exe',
        'C:\Program Files\nssm\nssm.exe',
        'C:\ProgramData\nssm\nssm.exe'
    ) | Where-Object { $_ -and (Test-Path $_) }
    if ($candidates) { return $candidates[0] }
    return $null
}

$nssm = Find-Nssm
if (-not $nssm) {
    Write-Host @'
NSSM not found. Install it, then re-run this script:

  1. Download NSSM: https://nssm.cc/download
  2. Extract win64\nssm.exe to C:\tools\nssm\nssm.exe
  3. Re-run: powershell -ExecutionPolicy Bypass -File .\scripts\install_streamlit_service.ps1

'@
    throw 'NSSM not found'
}

Write-Host "==> Using NSSM: $nssm"
Write-Host "==> Streamlit: $streamlit"

$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "==> Stopping existing service $ServiceName"
    & $nssm stop $ServiceName confirm 2>$null
    Start-Sleep -Seconds 2
    & $nssm remove $ServiceName confirm
    Start-Sleep -Seconds 1
}

$params = "run dashboard/streamlit_app.py --server.address 0.0.0.0 --server.port $Port --browser.gatherUsageStats false"

Write-Host "==> Installing $ServiceName"
& $nssm install $ServiceName $streamlit $params
& $nssm set $ServiceName AppDirectory $AppRoot
& $nssm set $ServiceName DisplayName $DisplayName
& $nssm set $ServiceName Start SERVICE_AUTO_START
& $nssm set $ServiceName AppStdout (Join-Path $AppRoot 'logs\streamlit_stdout.log')
& $nssm set $ServiceName AppStderr (Join-Path $AppRoot 'logs\streamlit_stderr.log')
& $nssm set $ServiceName AppRotateFiles 1
& $nssm set $ServiceName AppRotateBytes 10485760

$logsDir = Join-Path $AppRoot 'logs'
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

Write-Host "==> Starting $ServiceName"
& $nssm start $ServiceName
Start-Sleep -Seconds 2
Get-Service $ServiceName

Write-Host @"

Dashboard service installed.
  URL:  http://196.219.86.38:$Port/
  Cmds: Get-Service $ServiceName
        Restart-Service $ServiceName
        Get-Content $AppRoot\logs\streamlit_stderr.log -Tail 40

Close PowerShell safely — Streamlit keeps running.
"@
