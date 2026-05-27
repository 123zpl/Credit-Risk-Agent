"""FastAPI 路由定义"""

import time
import uuid

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from src.config import settings
from src.database import execute_readonly_sql, get_db
from src.graph.workflow import get_workflow, WorkflowState
from src.services.memory_store import (
    load_context_for_llm, append_turn_async,
    MEMORY_DIR, load_messages,
)
from src.services.metrics_cache import get_metrics
from src.services.rate_limiter import acquire_execution_lock, release_execution_lock, DistributedLock
from src.services.bloom_filter import (
    register_session, register_applicant,
    check_session, check_report, check_applicant,
    warmup_bloom_filters,
)
from src.services.health_service import full_health
from src.services.applicant_service import (
    ensure_applicants_table,
    generate_applicants,
    create_applicant_from_submit,
    get_form_options,
)
from src.infra.queue_service import enqueue_underwriting_task, get_task_status, build_approve_status_response
from src.models.underwriting_models import UnderwritingApproveResponse, UnderwritingApproveStatusResponse
from src.models.applicant_submit_models import (
    ApplicantSubmitRequest,
    ApplicantSubmitResponse,
    FormOptionsResponse,
)

router = APIRouter()


# ============================================
# 请求/响应模型
# ============================================

class AnalysisRequest(BaseModel):
    query: str = Field(..., description="用户的自然语言分析请求", min_length=2, max_length=500)
    session_id: str | None = Field(None, description="会话ID，留空自动生成")


class AnalysisResponse(BaseModel):
    session_id: str
    query: str
    intent: str
    report: str
    execution_log: list[dict]
    total_latency_ms: int


class HealthResponse(BaseModel):
    status: str
    mysql: bool
    redis: bool
    milvus: bool = False
    credit_policy_milvus: bool = False
    langsmith_tracing: bool = False
    langsmith_node_tracing: bool = False
    details: dict | None = None


def _workflow_invoke_config(session_id: str, query: str) -> dict:
    """LangSmith：默认仅顶层 trace；LANGSMITH_NODE_TRACING=true 时改由节点级 config。"""
    cfg: dict = {"recursion_limit": 25}
    if not settings.langsmith_node_tracing:
        cfg.update({
            "run_name": "credit_risk_workflow",
            "metadata": {"session_id": session_id, "query": query[:100]},
            "tags": ["credit-risk", "workflow"],
        })
    return cfg


class StrategyUpdateRequest(BaseModel):
    status: str = Field(..., description="新状态: ACTIVE / DISABLED / PENDING_REVIEW")
    approved_by: str = Field("admin", description="审批人")


class ApproveRequest(BaseModel):
    session_id: str | None = None


def _claim_pending_applicant(applicant_id: str) -> int:
    """Atomically claim a PENDING applicant for approval by setting status=RUNNING."""
    from sqlalchemy import text as sa_text

    with get_db() as session:
        result = session.execute(
            sa_text(
                "UPDATE applicants SET status = 'RUNNING' "
                "WHERE applicant_id = :aid AND status = 'PENDING'"
            ),
            {"aid": applicant_id},
        )
        return int(result.rowcount or 0)


def _revert_approval_claim(applicant_id: str):
    """Revert RUNNING claim when enqueue fails."""
    from sqlalchemy import text as sa_text

    with get_db() as session:
        session.execute(
            sa_text(
                "UPDATE applicants SET status = 'PENDING' "
                "WHERE applicant_id = :aid AND status = 'RUNNING'"
            ),
            {"aid": applicant_id},
        )


def _applicant_exists(applicant_id: str) -> bool:
    rows = execute_readonly_sql(
        "SELECT applicant_id FROM applicants WHERE applicant_id = :aid",
        {"aid": applicant_id},
    )
    return len(rows) > 0


# ============================================
# 路由
# ============================================

@router.get("/health", response_model=HealthResponse)
def health_check():
    """健康检查：MySQL、Redis、Milvus、LangSmith 追踪状态"""
    h = full_health()
    return HealthResponse(
        status=h["status"],
        mysql=h["mysql"],
        redis=h["redis"],
        milvus=h["milvus"],
        credit_policy_milvus=h.get("credit_policy_milvus", False),
        langsmith_tracing=h["langsmith_tracing"],
        langsmith_node_tracing=h["langsmith_node_tracing"],
        details=h.get("details"),
    )


@router.post("/analyze", response_model=AnalysisResponse)
def analyze(request: AnalysisRequest):
    """
    执行信贷风控分析（支持多轮会话、防重复提交）。

    多轮对话策略：
    - 历史 messages 从本地 .agent_memory/{session_id}.jsonl 加载（完整内容，KV Cache 友好）
    - 本轮结束后将 user + assistant 两条消息追加到本地文件
    - MySQL analysis_reports 保留完整报告归档（不变）
    """
    session_id = request.session_id or str(uuid.uuid4())

    if not acquire_execution_lock(session_id):
        raise HTTPException(status_code=409, detail="该会话正在分析中，请等待完成后再提交")

    start = time.time()
    try:
        # ── 从本地 JSONL 加载压缩上下文（有摘要标记时返回摘要+最近5轮，无摘要时返回全量）
        history_messages = load_context_for_llm(session_id)

        workflow = get_workflow()
        initial_state = WorkflowState(
            session_id=session_id,
            user_query=request.query,       # 原始问题，不再拼接摘要
            messages=history_messages,      # 完整历史，由各节点转为 LangChain messages
        )

        result = workflow.invoke(
            initial_state.model_dump(),
            _workflow_invoke_config(session_id, request.query),
        )
        total_ms = int((time.time() - start) * 1000)

        intent = result.get("intent", "unknown")
        report = result.get("final_report", "分析未生成结果")

        # ── 异步追加本轮对话到本地 JSONL（后台线程写盘，不阻塞响应返回）────
        append_turn_async(session_id, request.query, report, intent)

        # ── 注册到布隆过滤器（防非法 session_id 查询穿透）─────────────────
        register_session(session_id)

        return AnalysisResponse(
            session_id=result.get("session_id", session_id),
            query=request.query,
            intent=intent,
            report=report,
            execution_log=result.get("execution_log", []),
            total_latency_ms=total_ms,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析执行失败: {str(e)}")
    finally:
        release_execution_lock(session_id)


@router.get("/stats")
def get_stats():
    """获取数据库概览统计（带 Redis 缓存，TTL 5分钟）"""
    try:
        return get_metrics()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}/logs")
def get_session_logs(session_id: str):
    """获取指定会话的 Agent 执行日志"""
    # 布隆过滤器：「一定不存在」时直接拒绝，无需查 DB（防缓存穿透）
    if not check_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    try:
        logs = execute_readonly_sql(
            "SELECT * FROM agent_execution_logs WHERE session_id = :sid ORDER BY step_index",
            {"sid": session_id},
        )
        return {"session_id": session_id, "logs": logs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions")
def list_sessions():
    """
    列出所有本地会话（扫描 .agent_memory 目录）。

    返回按最近活跃时间倒序的会话列表，每条包含：
      - session_id、首条消息预览、最后活跃时间、消息条数
    """
    import json
    from pathlib import Path

    mem_dir = Path(MEMORY_DIR)
    if not mem_dir.exists():
        return {"sessions": []}

    sessions = []
    for f in sorted(mem_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        session_id = f.stem
        try:
            lines = [ln for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if not lines:
                continue
            msgs = []
            for ln in lines:
                try:
                    msgs.append(json.loads(ln))
                except Exception:
                    pass
            # 过滤 summary_marker 系统行，只看真实消息
            user_msgs = [m for m in msgs if m.get("role") == "user"]
            first_preview = user_msgs[0]["content"][:60] if user_msgs else "（空会话）"
            last_ts = msgs[-1].get("ts", "") if msgs else ""
            sessions.append({
                "session_id": session_id,
                "preview": first_preview,
                "last_active": last_ts,
                "message_count": len([m for m in msgs if m.get("role") in ("user", "assistant")]),
            })
        except Exception:
            pass

    return {"sessions": sessions}


@router.get("/sessions/{session_id}/messages")
def get_session_messages(session_id: str):
    """
    获取指定会话的完整对话记录（来自 .agent_memory JSONL）。

    返回格式：[{"role": "user"|"assistant", "content": "...", "intent": "...", "ts": "..."}]
    """
    import json
    from pathlib import Path

    f = Path(MEMORY_DIR) / f"{session_id}.jsonl"
    if not f.exists():
        raise HTTPException(status_code=404, detail="会话不存在")

    messages = []
    for ln in f.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            msg = json.loads(ln)
            # 过滤 summary_marker 系统行
            if msg.get("role") in ("user", "assistant"):
                messages.append({
                    "role": msg["role"],
                    "content": msg.get("content", ""),
                    "intent": msg.get("intent", ""),
                    "ts": msg.get("ts", ""),
                })
        except Exception:
            pass

    return {"session_id": session_id, "messages": messages}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    """
    删除指定会话：
    - 删除 .agent_memory/{session_id}.jsonl 本地文件
    - 删除 MySQL analysis_reports 中该 session 的记录
    """
    import re
    from pathlib import Path
    from sqlalchemy import text as sa_text

    # 防止路径遍历
    if not re.match(r'^[0-9a-f\-]{36}$', session_id):
        raise HTTPException(status_code=400, detail="无效的 session_id 格式")

    deleted_file = False
    f = Path(MEMORY_DIR) / f"{session_id}.jsonl"
    if f.exists():
        f.unlink()
        deleted_file = True

    deleted_reports = 0
    try:
        with get_db() as db:
            result = db.execute(
                sa_text("DELETE FROM analysis_reports WHERE session_id = :sid"),
                {"sid": session_id},
            )
            deleted_reports = result.rowcount
            db.commit()
    except Exception as e:
        pass  # 文件已删，MySQL 失败时不阻塞

    if not deleted_file and deleted_reports == 0:
        raise HTTPException(status_code=404, detail="会话不存在")

    return {
        "session_id": session_id,
        "deleted_file": deleted_file,
        "deleted_reports": deleted_reports,
    }


@router.get("/reports")
def list_reports(limit: int = 20):
    """获取最近的分析报告列表"""
    try:
        reports = execute_readonly_sql(
            "SELECT report_id, session_id, title, query_text, summary, created_at "
            "FROM analysis_reports ORDER BY created_at DESC LIMIT :lim",
            {"lim": limit},
        )
        return {"reports": reports}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reports/{report_id}")
def get_report(report_id: str):
    """获取单个分析报告详情"""
    # 布隆过滤器：「一定不存在」时直接拒绝，无需查 DB（防缓存穿透）
    if not check_report(report_id):
        raise HTTPException(status_code=404, detail="报告不存在")
    try:
        rows = execute_readonly_sql(
            "SELECT * FROM analysis_reports WHERE report_id = :rid",
            {"rid": report_id},
        )
        if not rows:
            raise HTTPException(status_code=404, detail="报告不存在")
        return rows[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/strategies")
def list_strategies(status: str | None = None, limit: int = 20):
    """获取风控策略列表"""
    try:
        if status:
            strategies = execute_readonly_sql(
                "SELECT * FROM risk_strategies WHERE status = :s ORDER BY created_at DESC LIMIT :lim",
                {"s": status, "lim": limit},
            )
        else:
            strategies = execute_readonly_sql(
                "SELECT * FROM risk_strategies ORDER BY created_at DESC LIMIT :lim",
                {"lim": limit},
            )
        return {"strategies": strategies}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/strategies/{strategy_id}")
def update_strategy(strategy_id: str, request: StrategyUpdateRequest):
    """审批/更新策略状态"""
    from sqlalchemy import text as sa_text

    valid_statuses = {"ACTIVE", "DISABLED", "PENDING_REVIEW", "DRAFT"}
    if request.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"无效状态，可选: {valid_statuses}")

    try:
        with get_db() as session:
            result = session.execute(sa_text(
                "UPDATE risk_strategies SET status = :status, approved_by = :approver "
                "WHERE strategy_id = :sid"
            ), {"status": request.status, "approver": request.approved_by, "sid": strategy_id})
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="策略不存在")
        return {"strategy_id": strategy_id, "new_status": request.status}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/strategies/{strategy_id}")
def delete_strategy(strategy_id: str):
    """删除风控策略"""
    from sqlalchemy import text as sa_text
    try:
        with get_db() as session:
            result = session.execute(
                sa_text("DELETE FROM risk_strategies WHERE strategy_id = :sid"),
                {"sid": strategy_id},
            )
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="策略不存在")
        return {"deleted": strategy_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _enqueue_underwriting(applicant_id: str, session_id: str | None = None) -> str:
    """Claim PENDING applicant and enqueue Celery underwriting task."""
    claimed = _claim_pending_applicant(applicant_id)
    if claimed == 0:
        if not _applicant_exists(applicant_id):
            raise HTTPException(status_code=404, detail="申请人不存在")
        raise HTTPException(status_code=409, detail="该申请人状态非PENDING，不能重复审批")
    try:
        return enqueue_underwriting_task(applicant_id, session_id)
    except Exception:
        _revert_approval_claim(applicant_id)
        raise


@router.post("/applicants/generate")
def api_generate_applicants(
    count: int = 20,
    fico_profile: str = "random",
):
    """生成模拟申请人。fico_profile: random | high | medium | low"""
    if fico_profile not in ("random", "high", "medium", "low"):
        raise HTTPException(status_code=400, detail="fico_profile 必须为 random/high/medium/low")
    count = max(1, min(count, 100))
    try:
        applicant_ids = generate_applicants(count=count, fico_profile=fico_profile)
        # 生成成功后批量注册到布隆过滤器
        for aid in applicant_ids:
            register_applicant(aid)
        return {"count": len(applicant_ids), "applicant_ids": applicant_ids}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/applicants")
def list_applicants(status: str | None = None, limit: int = 20):
    """查询申请人列表。"""
    try:
        ensure_applicants_table()
        if status:
            rows = execute_readonly_sql(
                "SELECT * FROM applicants WHERE status = :s ORDER BY created_at DESC LIMIT :lim",
                {"s": status, "lim": limit},
            )
        else:
            rows = execute_readonly_sql(
                "SELECT * FROM applicants ORDER BY created_at DESC LIMIT :lim",
                {"lim": limit},
            )
        return {"applicants": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/applicants/form-options", response_model=FormOptionsResponse)
def api_applicant_form_options():
    """用户贷款申请表单下拉选项。"""
    return FormOptionsResponse.model_validate(get_form_options())


@router.post("/applicants/submit", response_model=ApplicantSubmitResponse)
def api_submit_application(request: ApplicantSubmitRequest):
    """用户提交贷款申请；默认自动触发 Underwriting Agent 审批。"""
    try:
        record = create_applicant_from_submit(request)
        applicant_id = record["applicant_id"]
        register_applicant(applicant_id)

        if not request.auto_start:
            return ApplicantSubmitResponse(
                applicant_id=applicant_id,
                task_id=None,
                status="PENDING",
                message="申请已提交，等待审批",
            )

        task_id = _enqueue_underwriting(applicant_id)
        return ApplicantSubmitResponse(
            applicant_id=applicant_id,
            task_id=task_id,
            status="RUNNING",
            message="申请已提交，Agent 正在审批中",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/applicants/{applicant_id}")
def get_applicant(applicant_id: str):
    """查询申请人详情。"""
    # 布隆过滤器：「一定不存在」时直接拒绝，无需查 DB（防缓存穿透）
    if not check_applicant(applicant_id):
        raise HTTPException(status_code=404, detail="申请人不存在")
    try:
        ensure_applicants_table()
        rows = execute_readonly_sql(
            "SELECT * FROM applicants WHERE applicant_id = :aid",
            {"aid": applicant_id},
        )
        if not rows:
            raise HTTPException(status_code=404, detail="申请人不存在")
        return rows[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/applicants/{applicant_id}/approve", response_model=UnderwritingApproveResponse)
def approve_applicant(applicant_id: str, request: ApproveRequest):
    """异步提交审批任务。"""
    try:
        ensure_applicants_table()
        task_id = _enqueue_underwriting(applicant_id, request.session_id)
        return UnderwritingApproveResponse(
            applicant_id=applicant_id,
            task_id=task_id,
            status="PENDING",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/applicants/{applicant_id}/approve-status", response_model=UnderwritingApproveStatusResponse)
def approve_status(applicant_id: str, task_id: str):
    """查询审批任务状态。"""
    try:
        rows = execute_readonly_sql(
            "SELECT * FROM applicants WHERE applicant_id = :aid",
            {"aid": applicant_id},
        )
        if not rows:
            raise HTTPException(status_code=404, detail="申请人不存在")
        task_status = get_task_status(task_id)
        return build_approve_status_response(applicant_id, task_id, task_status, rows[0])
    except HTTPException:
        raise
    except Exception as validation_error:
        from pydantic import ValidationError

        if isinstance(validation_error, ValidationError):
            raise HTTPException(status_code=500, detail=f"审批状态契约校验失败: {validation_error}") from validation_error
        raise HTTPException(status_code=500, detail=str(validation_error))


@router.post("/applicants/{applicant_id}/reset")
def reset_applicant(applicant_id: str):
    """将僵死的 RUNNING 申请人重置为 MANUAL_REVIEW（用于服务重启后的状态修复）。"""
    try:
        ensure_applicants_table()
        with get_db() as conn:
            result = conn.execute(
                __import__("sqlalchemy").text(
                    "UPDATE applicants SET status='MANUAL_REVIEW', decision_reason='任务中断，已重置为人工复核'"
                    " WHERE applicant_id=:aid AND status='RUNNING'"
                ),
                {"aid": applicant_id},
            )
            conn.commit()
        if result.rowcount == 0:
            rows = execute_readonly_sql(
                "SELECT status FROM applicants WHERE applicant_id = :aid", {"aid": applicant_id}
            )
            if not rows:
                raise HTTPException(status_code=404, detail="申请人不存在")
            raise HTTPException(
                status_code=409,
                detail=f"申请人当前状态为 {rows[0]['status']}，非 RUNNING，无需重置",
            )
        return {"applicant_id": applicant_id, "status": "MANUAL_REVIEW", "message": "已重置"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/applicants/{applicant_id}")
def delete_applicant(applicant_id: str):
    """删除单条申请人（RUNNING 状态禁止删除，防止任务孤儿化）。"""
    try:
        ensure_applicants_table()
        rows = execute_readonly_sql(
            "SELECT status FROM applicants WHERE applicant_id = :aid", {"aid": applicant_id}
        )
        if not rows:
            raise HTTPException(status_code=404, detail="申请人不存在")
        if rows[0]["status"] == "RUNNING":
            raise HTTPException(status_code=409, detail="审批进行中，不允许删除，请先等待审批完成或重置状态")
        with get_db() as conn:
            conn.execute(
                __import__("sqlalchemy").text("DELETE FROM applicants WHERE applicant_id = :aid"),
                {"aid": applicant_id},
            )
            conn.commit()
        return {"applicant_id": applicant_id, "deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/applicants")
def delete_applicants_batch(status: str | None = None):
    """批量删除申请人。status 可选：PENDING/APPROVED/REJECTED/MANUAL_REVIEW；留空则删除全部非 RUNNING。"""
    try:
        ensure_applicants_table()
        import sqlalchemy as sa
        allowed = {"PENDING", "APPROVED", "REJECTED", "MANUAL_REVIEW", "FAILURE"}
        with get_db() as conn:
            if status:
                if status not in allowed:
                    raise HTTPException(status_code=400, detail=f"不支持按状态 {status} 批量删除")
                result = conn.execute(
                    sa.text("DELETE FROM applicants WHERE status = :s"), {"s": status}
                )
            else:
                result = conn.execute(
                    sa.text("DELETE FROM applicants WHERE status != 'RUNNING'")
                )
            conn.commit()
        return {"deleted": result.rowcount, "status_filter": status or "all(非RUNNING)"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class BatchApproveRequest(BaseModel):
    applicant_ids: list[str] | None = Field(None, description="指定要审批的申请人ID列表；为空则批量处理所有PENDING")
    limit: int = Field(50, ge=1, le=200)


@router.post("/applicants/batch-approve")
def batch_approve(req: BatchApproveRequest = Body(default_factory=BatchApproveRequest)):
    """
    批量提交审批任务。
    使用 Redis 分布式锁（DistributedLock）防止并发重复触发批量审批，
    对标 Java 项目中的 Redisson 分布式锁方案。
    """
    # ── Redis 分布式锁：整个批量操作加全局互斥锁 ──────────────────────
    # TTL=120s：足够处理完一批任务，崩溃后自动释放，不会死锁
    with DistributedLock("batch_approve", ttl=120) as acquired:
        if not acquired:
            raise HTTPException(
                status_code=409,
                detail="批量审批任务正在执行中，请等待当前批次完成后再提交",
            )
        try:
            ensure_applicants_table()
            if req.applicant_ids:
                rows = [{"applicant_id": aid} for aid in req.applicant_ids]
            else:
                rows = execute_readonly_sql(
                    "SELECT applicant_id FROM applicants WHERE status = 'PENDING' ORDER BY created_at ASC LIMIT :lim",
                    {"lim": req.limit},
                )
            task_ids = []
            for row in rows:
                applicant_id = row["applicant_id"]
                # 乐观锁（DB 原子更新）：与 Redis 锁形成双重并发保护
                claimed = _claim_pending_applicant(applicant_id)
                if claimed == 0:
                    continue
                try:
                    task_id = enqueue_underwriting_task(applicant_id)
                    task_ids.append({"applicant_id": applicant_id, "task_id": task_id})
                except Exception:
                    _revert_approval_claim(applicant_id)
                    raise
            return {"count": len(task_ids), "tasks": task_ids}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
