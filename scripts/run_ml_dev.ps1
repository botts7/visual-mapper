# Visual Mapper ML Training Server - Windows Development Script
# Run this on your dev machine with GPU/NPU to train ML models
#
# Usage:
#   .\run_ml_dev.ps1                          # Uses localhost MQTT
#   .\run_ml_dev.ps1 -Broker 192.168.86.66    # Connect to HA MQTT
#   .\run_ml_dev.ps1 -Broker 192.168.86.66 -DQN  # Use Deep Q-Network

param(
    [string]$Broker = "localhost",
    [int]$Port = 1883,
    [string]$Username = "",
    [string]$Password = "",
    [switch]$DQN,
    [switch]$UseNPU
)

$ErrorActionPreference = "Stop"

# Find the backend directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path (Split-Path -Parent $ScriptDir) "backend"

if (-not (Test-Path $BackendDir)) {
    Write-Error "Backend directory not found: $BackendDir"
    exit 1
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Visual Mapper ML Training Server" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "MQTT Broker: $Broker`:$Port" -ForegroundColor Yellow
if ($DQN) {
    Write-Host "Mode: Deep Q-Network (DQN)" -ForegroundColor Green
} else {
    Write-Host "Mode: Q-Table Learning" -ForegroundColor Green
}
if ($UseNPU) {
    Write-Host "Acceleration: NPU (DirectML)" -ForegroundColor Green
}
Write-Host ""

# Build command arguments
$Args = @(
    "ml_components/ml_training_server.py",
    "--broker", $Broker,
    "--port", $Port
)

if ($Username) {
    $Args += "--username", $Username
}
if ($Password) {
    $Args += "--password", $Password
}
if ($DQN) {
    $Args += "--dqn"
}
if ($UseNPU) {
    $Args += "--use-npu"
}

# Set PYTHONPATH and run
$env:PYTHONPATH = $BackendDir
$env:ML_TRAINING = "true"

Push-Location $BackendDir
try {
    Write-Host "Starting ML Training Server..." -ForegroundColor Green
    Write-Host "Press Ctrl+C to stop" -ForegroundColor DarkGray
    Write-Host ""

    python @Args
} finally {
    Pop-Location
}
