<#
.SYNOPSIS
  Hanafuda app: development environment in Docker (Windows).
  Python is NOT installed on the host; everything runs inside containers.

.DESCRIPTION
  Run "setup" once while online. After that every command except "update" works offline.

  setup  : build the image, download Pyodide, run tests  [default]
  start  : start the dev server and open http://localhost:8000 (auto rebuild on save)
  stop   : stop the dev server
  logs   : follow dev server logs
  test   : run tests (pytest)
  shell  : open a shell inside the container
  export : write the static site (PWA) to .\dist for publishing on an HTTPS host
  update : (online) rebuild the image with the latest base image
  clean  : remove containers, volumes and the image

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\setup.ps1 start
#>
param(
  [ValidateSet('setup', 'start', 'stop', 'logs', 'test', 'shell', 'export', 'update', 'clean')]
  [string]$Command = 'setup'
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

$Image = 'hanafuda-app-dev'
$Url = 'http://localhost:8000'

function Invoke-Step([string]$Title, [scriptblock]$Action) {
  Write-Host "`n==> $Title" -ForegroundColor Cyan
  & $Action
  if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
    throw "Step failed: $Title (exit code $LASTEXITCODE)"
  }
}

# Run a native command only to check its exit code. Windows PowerShell 5.1 turns
# redirected stderr into a terminating error under 'Stop', so relax it locally.
function Test-Command([scriptblock]$Action) {
  $ErrorActionPreference = 'Continue'
  & $Action *> $null
  return $LASTEXITCODE -eq 0
}

function Assert-Docker {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker was not found. Install Docker Desktop and re-run.'
  }
  if (Test-Command { docker info }) { return }

  $desktop = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'
  if (-not (Test-Path $desktop)) { $desktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe' }
  if (-not (Test-Path $desktop)) { throw 'Docker is not running. Start Docker Desktop and re-run.' }

  Write-Host 'Starting Docker Desktop...' -ForegroundColor Yellow
  Start-Process $desktop
  for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 2
    if (Test-Command { docker info }) { return }
  }
  throw 'Docker Desktop did not become ready within 3 minutes.'
}

# Only touches the network when something is missing locally
function Initialize-Environment {
  if (-not (Test-Command { docker image inspect $Image })) {
    Invoke-Step 'Building dev image' { docker compose build dev }
  }
  Invoke-Step 'Preparing Pyodide (downloads only if missing)' {
    docker compose run --rm dev python scripts/fetch_pyodide.py
  }
}

function Get-LanAddress {
  Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.PrefixOrigin -in 'Dhcp', 'Manual' -and $_.IPAddress -notlike '169.*' -and $_.InterfaceAlias -notmatch 'vEthernet|WSL|Loopback' } |
    Select-Object -ExpandProperty IPAddress -First 1
}

Assert-Docker

switch ($Command) {
  'setup' {
    Initialize-Environment
    Invoke-Step 'Running tests' { docker compose run --rm dev pytest }
    Write-Host "`nSetup complete (offline-ready). Start with:  .\setup.ps1 start" -ForegroundColor Green
  }
  'start' {
    Initialize-Environment
    Invoke-Step 'Starting dev server' { docker compose up -d dev }
    Write-Host "Waiting for $Url ..."
    for ($i = 0; $i -lt 60; $i++) {
      try { Invoke-WebRequest $Url -UseBasicParsing -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep 1 }
    }
    Start-Process $Url
    Write-Host "PC:    $Url" -ForegroundColor Green
    $lan = Get-LanAddress
    if ($lan) {
      Write-Host "Phone: http://${lan}:8000  (same Wi-Fi; playable, but install/offline needs HTTPS)" -ForegroundColor Green
    }
    Write-Host 'Stop with:  .\setup.ps1 stop'
  }
  'stop'  { Invoke-Step 'Stopping' { docker compose down } }
  'logs'  { docker compose logs -f dev }
  'test'  { Initialize-Environment; Invoke-Step 'Running tests' { docker compose run --rm dev pytest } }
  'shell' { docker compose run --rm dev bash }
  'export' {
    Initialize-Environment
    Invoke-Step 'Building static site into .\dist' { docker compose run --rm dev python scripts/build.py --out /app/dist }
    Write-Host 'Upload the contents of .\dist to any HTTPS static host (e.g. GitHub Pages).' -ForegroundColor Green
  }
  'update' { Invoke-Step 'Rebuilding image with latest base image' { docker compose build --pull dev } }
  'clean' {
    Invoke-Step 'Removing containers and volumes' { docker compose down --volumes }
    if (Test-Command { docker image inspect $Image }) {
      Invoke-Step 'Removing image' { docker image rm $Image }
    }
  }
}
