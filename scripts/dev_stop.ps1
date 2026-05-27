# 停止本地开发服务（后端/前端端口 + Celery worker）
$ErrorActionPreference = "SilentlyContinue"

$ports = @(8000, 3000, 3001, 8010)

foreach ($port in $ports) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) { continue }
    foreach ($c in $conns) {
        Stop-Process -Id $c.OwningProcess -Force
        Write-Host "Stopped PID $($c.OwningProcess) on port $port"
    }
}

# 额外清理本项目 Celery worker（可能不占上述端口）
$workerKeywords = @(
    "celery -A src.infra.celery_app:celery_app worker",
    "src.infra.celery_app:celery_app worker"
)

$procs = Get-CimInstance Win32_Process
foreach ($p in $procs) {
    $cmd = $p.CommandLine
    if (-not $cmd) { continue }

    $isProjectProc = $cmd -match "agent-cursor"
    if (-not $isProjectProc) { continue }

    $isWorker = $false
    foreach ($kw in $workerKeywords) {
        if ($cmd -match [Regex]::Escape($kw)) {
            $isWorker = $true
            break
        }
    }

    if ($isWorker) {
        Stop-Process -Id $p.ProcessId -Force
        Write-Host "Stopped Celery worker PID $($p.ProcessId)"
    }
}

Write-Host "Done. Ports $($ports -join ', ') and project Celery workers should be free."
