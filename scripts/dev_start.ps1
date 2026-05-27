# 启动后端 API（单进程，无热加载）
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "Starting Docker services (MySQL + Redis)..."
docker compose up -d

Write-Host "Starting Celery worker in a new PowerShell window..."
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "cd `"$((Join-Path $PSScriptRoot ".."))`"; conda activate llm2; celery -A src.infra.celery_app:celery_app worker -l info -P threads -c 4 -n worker@%h"
)

Write-Host "Starting backend on http://0.0.0.0:8001 ..."
Write-Host "Tip: run scripts/dev_stop.ps1 before restart to avoid duplicate processes."
conda activate llm2
python app.py
