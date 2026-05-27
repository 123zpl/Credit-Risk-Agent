"""Celery tasks for underwriting workflow."""

from __future__ import annotations

import json
from sqlalchemy import text

from src.database import get_db
from src.graph.workflow import UnderwritingState, build_underwriting_workflow
from src.infra.celery_app import celery_app
from src.tools.underwriting_tools import validate_underwriting_decision


def _format_decision_reason(validated: dict) -> str:
    """Store decision_reasons as a JSON array string for clean frontend parsing."""
    reasons = validated.get("decision_reasons")
    if isinstance(reasons, list) and reasons:
        return json.dumps(reasons, ensure_ascii=False)[:5000]
    # Fallback: compliance_check or plain string
    fallback = validated.get("compliance_check") or validated.get("decision_reason") or ""
    if isinstance(fallback, (list, dict)):
        return json.dumps(fallback, ensure_ascii=False)[:5000]
    return str(fallback)[:5000]


def _update_status(applicant_id: str, status: str) -> int:
    with get_db() as session:
        result = session.execute(
            text("UPDATE applicants SET status = :status WHERE applicant_id = :aid"),
            {"status": status, "aid": applicant_id},
        )
        return int(result.rowcount or 0)


def _persist_decision(applicant_id: str, decision: dict):
    validated = validate_underwriting_decision(decision)
    score_bd = validated.get("score_breakdown")
    with get_db() as session:
        session.execute(
            text(
                """
                UPDATE applicants
                SET status = :status,
                    risk_score = :risk_score,
                    risk_grade = :risk_grade,
                    approved_amount = :approved_amount,
                    approved_rate = :approved_rate,
                    decision_reason = :decision_reason,
                    approval_report = :approval_report,
                    score_breakdown = :score_breakdown,
                    reviewed_at = NOW()
                WHERE applicant_id = :aid
                """
            ),
            {
                "status": validated.get("decision", "MANUAL_REVIEW"),
                "risk_score": validated.get("risk_score"),
                "risk_grade": validated.get("risk_grade"),
                "approved_amount": validated.get("suggested_amount"),
                "approved_rate": validated.get("suggested_rate"),
                "decision_reason": _format_decision_reason(validated),
                "approval_report": str(validated.get("approval_report") or "")[:65535],
                "score_breakdown": json.dumps(score_bd, ensure_ascii=False) if score_bd else None,
                "aid": applicant_id,
            },
        )


def _persist_failure(applicant_id: str, error_message: str):
    with get_db() as session:
        session.execute(
            text(
                """
                UPDATE applicants
                SET status = 'MANUAL_REVIEW',
                    decision_reason = :decision_reason,
                    reviewed_at = NOW()
                WHERE applicant_id = :aid
                """
            ),
            {
                "decision_reason": f"审批任务失败: {error_message}"[:5000],
                "aid": applicant_id,
            },
        )


@celery_app.task(
    bind=True,
    name="run_underwriting_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def run_underwriting_task(self, applicant_id: str, session_id: str | None = None):
    updated = _update_status(applicant_id, "RUNNING")
    if updated == 0:
        raise ValueError("申请人不存在或状态不可更新")

    try:
        workflow = build_underwriting_workflow()
        state = UnderwritingState(
            session_id=session_id or self.request.id,
            applicant_id=applicant_id,
        )
        result = workflow.invoke(state.model_dump(), {"recursion_limit": 20})
        final_decision = result.get("final_decision", {})
        validated = validate_underwriting_decision(final_decision)
        _persist_decision(applicant_id, validated)
        return {"applicant_id": applicant_id, "decision": validated}
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            _persist_failure(applicant_id, str(exc))
        raise
