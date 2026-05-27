# 启动 Celery Worker（授信审批异步任务）
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "Starting Celery worker with llm2 env..."
Write-Host "Queue backend: redis://localhost:6379/0"

conda activate llm2
celery -A src.infra.celery_app:celery_app worker -l info -P threads -c 4
