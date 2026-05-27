# 启动前端 Vite 开发服务器
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\frontend")

Write-Host "Starting frontend on http://localhost:3000 ..."
npm run dev
