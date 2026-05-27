"""持久化服务：Agent执行日志、分析报告、风控策略写入 MySQL"""

import json
import uuid
import logging

from sqlalchemy import text

from src.database import get_db
from src.services.bloom_filter import register_report, register_session

logger = logging.getLogger(__name__)


def persist_execution_log(session_id: str, log_entry: dict):
    """将单条 Agent 执行日志写入 agent_execution_logs 表"""
    try:
        with get_db() as session:
            session.execute(text("""
                INSERT INTO agent_execution_logs
                (session_id, agent_name, step_index, thought, action, action_input, observation, token_used, latency_ms)
                VALUES (:sid, :agent, :step, :thought, :action, :input, :obs, :tokens, :latency)
            """), {
                "sid": session_id,
                "agent": log_entry.get("agent", ""),
                "step": log_entry.get("step", 0),
                "thought": log_entry.get("thought", ""),
                "action": log_entry.get("action", ""),
                "input": log_entry.get("action_input", ""),
                "obs": str(log_entry.get("result", ""))[:5000],
                "tokens": log_entry.get("token_used", 0),
                "latency": log_entry.get("latency_ms", 0),
            })
    except Exception as e:
        logger.warning(f"Failed to persist execution log: {e}")


def persist_report(
    session_id: str,
    query: str,
    intent: str,
    report: str,
    data_result: str = "",
    risk_result: str = "",
    strategy_result: str = "",
    compliance_result: str = "",
):
    """将分析报告写入 analysis_reports 表"""
    report_id = str(uuid.uuid4())
    try:
        detail = {
            "data_result": data_result[:3000] if data_result else "",
            "risk_result": risk_result[:3000] if risk_result else "",
            "compliance_result": compliance_result[:3000] if compliance_result else "",
        }
        with get_db() as session:
            session.execute(text("""
                INSERT INTO analysis_reports
                (report_id, session_id, title, query_text, summary, detail, strategies)
                VALUES (:rid, :sid, :title, :query, :summary, :detail, :strategies)
            """), {
                "rid": report_id,
                "sid": session_id,
                "title": f"[{intent}] {query[:80]}",
                "query": query,
                "summary": report[:5000],
                "detail": json.dumps(detail, ensure_ascii=False),
                "strategies": json.dumps(
                    {"strategy_result": strategy_result[:3000]} if strategy_result else {},
                    ensure_ascii=False,
                ),
            })
        # 写入成功后同步注册到布隆过滤器（防止缓存穿透）
        register_report(report_id)
        register_session(session_id)
        return report_id
    except Exception as e:
        logger.warning(f"Failed to persist report: {e}")
        return None


def persist_strategy(session_id: str, strategy_text: str) -> str | None:
    """解析并持久化 Agent 生成的策略到 risk_strategies 表"""
    strategy_id = str(uuid.uuid4())
    try:
        with get_db() as session:
            session.execute(text("""
                INSERT INTO risk_strategies
                (strategy_id, name, description, trigger_condition, action_type, status, created_by)
                VALUES (:sid, :name, :desc, :cond, :action, 'DRAFT', 'agent')
            """), {
                "sid": strategy_id,
                "name": f"Agent策略_{strategy_id[:8]}",
                "desc": strategy_text[:5000],
                "cond": json.dumps({"source": "agent_generated", "session_id": session_id}),
                "action": "MANUAL_REVIEW",
            })
        return strategy_id
    except Exception as e:
        logger.warning(f"Failed to persist strategy: {e}")
        return None
