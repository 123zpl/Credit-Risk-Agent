"""信贷风控 Agent 平台 - FastAPI 入口"""

from dotenv import load_dotenv
load_dotenv(override=True)

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import router
from src.api.export_routes import export_router
from src.services.rate_limiter import RateLimitMiddleware
from src.services.applicant_service import ensure_applicants_on_startup

app = FastAPI(
    title="信贷风控 Agent 平台",
    description="Multi-Agent 协作的智能信贷风控分析系统",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RateLimitMiddleware)

app.include_router(router, prefix="/api/v1")
app.include_router(export_router, prefix="/api/v1")


@app.on_event("startup")
def startup_seed_applicants():
    try:
        ensure_applicants_on_startup(min_count=1, generate_count=20)
    except Exception:
        # Startup should not block API boot when DB is unavailable.
        pass


@app.on_event("startup")
def startup_warmup_bloom_filters():
    """预热布隆过滤器：将已有 ID 从 MySQL 批量写入 Redis，防止重启后合法请求被误拒。"""
    try:
        from src.services.bloom_filter import warmup_bloom_filters
        counts = warmup_bloom_filters()
        print(
            f"[startup] BloomFilter 预热完成 — "
            f"sessions={counts['sessions']}, "
            f"reports={counts['reports']}, "
            f"applicants={counts['applicants']}"
        )
    except Exception as e:
        print(f"[startup] BloomFilter 预热失败（忽略）: {e}")


@app.on_event("startup")
def startup_fix_stale_running():
    """将上次服务崩溃/重启留下的僵死 RUNNING 申请人重置为 MANUAL_REVIEW。"""
    try:
        from src.database import get_db
        import sqlalchemy
        with get_db() as conn:
            result = conn.execute(
                sqlalchemy.text(
                    "UPDATE applicants SET status='MANUAL_REVIEW',"
                    " decision_reason='服务重启，任务中断，已转人工复核'"
                    " WHERE status='RUNNING'"
                )
            )
            conn.commit()
            if result.rowcount:
                print(f"[startup] 修复 {result.rowcount} 条僵死 RUNNING 申请人 → MANUAL_REVIEW")
    except Exception as e:
        print(f"[startup] 修复僵死任务失败（忽略）: {e}")


@app.get("/")
async def root():
    return {
        "name": "信贷风控 Agent 平台",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "健康检查": "/api/v1/health",
            "风控分析": "POST /api/v1/analyze",
            "数据概览": "/api/v1/stats",
        },
    }


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8001)
