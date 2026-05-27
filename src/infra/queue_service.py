"""Queue service wrappers for underwriting async tasks."""

from celery.result import AsyncResult

from src.infra.celery_app import celery_app
from src.models.underwriting_models import UnderwritingApproveStatusResponse
from src.tasks.underwriting_tasks import run_underwriting_task


def enqueue_underwriting_task(applicant_id: str, session_id: str | None = None) -> str:
    task = run_underwriting_task.delay(applicant_id, session_id)
    return task.id


def _normalize_state(state: str) -> str:
    s = (state or "").upper()
    if s == "STARTED":
        return "RUNNING"
    if s in {"PENDING", "SUCCESS", "FAILURE"}:
        return s
    if s == "RETRY":
        return "RUNNING"
    return "PENDING"


def get_task_status(task_id: str) -> dict:
    result = AsyncResult(task_id, app=celery_app)
    normalized = _normalize_state(result.state)
    payload: dict = {
        "task_id": task_id,
        "status": normalized,
        "result": result.result if normalized == "SUCCESS" else None,
        "error_detail": None,
    }
    if normalized == "FAILURE":
        payload["error_detail"] = str(result.result)
    return payload


def _extract_decision_payload(task_status: dict, applicant_row: dict | None) -> dict | None:
    raw_result = task_status.get("result")
    if isinstance(raw_result, dict):
        decision = raw_result.get("decision")
        if isinstance(decision, dict):
            return decision
        if decision is None and raw_result.get("risk_score") is not None:
            return raw_result

    if applicant_row and applicant_row.get("status") in {"APPROVED", "REJECTED", "MANUAL_REVIEW"}:
        return {
            "decision": applicant_row.get("status"),
            "risk_score": applicant_row.get("risk_score"),
            "risk_grade": applicant_row.get("risk_grade"),
            "suggested_amount": applicant_row.get("approved_amount"),
            "suggested_rate": applicant_row.get("approved_rate"),
            "decision_reasons": [applicant_row.get("decision_reason") or ""],
        }
    return None


def build_approve_status_response(
    applicant_id: str,
    task_id: str,
    task_status: dict,
    applicant_row: dict | None,
) -> UnderwritingApproveStatusResponse:
    decision_payload = _extract_decision_payload(task_status, applicant_row)
    response = UnderwritingApproveStatusResponse.from_task_and_applicant(
        applicant_id=applicant_id,
        task_id=task_id,
        task_status=task_status,
        applicant_row=applicant_row,
        decision_payload=decision_payload,
    )
    return UnderwritingApproveStatusResponse.model_validate(response.model_dump())
