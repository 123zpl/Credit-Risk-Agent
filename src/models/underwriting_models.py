"""Unified Pydantic output contracts for underwriting flow."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator


class ScoreBreakdown(BaseModel):
    fico: int = 0
    dti: int = 0
    delinq: int = 0
    emp_length: int = 0
    home: int = 0
    revol_util: int = 0
    inquiries: int = 0

    @computed_field
    @property
    def total(self) -> int:
        return (
            self.fico
            + self.dti
            + self.delinq
            + self.emp_length
            + self.home
            + self.revol_util
            + self.inquiries
        )


class ComplianceCheckItem(BaseModel):
    passed: bool
    rule: str


class ComplianceCheckResult(BaseModel):
    checks: dict[str, ComplianceCheckItem]
    overall_passed: bool

    @model_validator(mode="before")
    @classmethod
    def _coerce_checks(cls, data):
        if not isinstance(data, dict):
            return data
        checks = data.get("checks") or {}
        coerced = {}
        for key, val in checks.items():
            if isinstance(val, dict):
                coerced[key] = val
            else:
                coerced[key] = {"passed": bool(val), "rule": str(val)}
        data = dict(data)
        data["checks"] = coerced
        return data


class UnderwritingDecision(BaseModel):
    decision: Literal["APPROVED", "REJECTED", "MANUAL_REVIEW"]
    risk_score: int
    risk_grade: str
    suggested_amount: float
    suggested_rate: float
    score_breakdown: ScoreBreakdown
    decision_reasons: list[str] = Field(default_factory=list)
    risk_warnings: list[str] = Field(default_factory=list)
    compliance_check: ComplianceCheckResult | None = None
    approval_report: str = ""

    @classmethod
    def from_payload(cls, payload: dict) -> "UnderwritingDecision":
        data = dict(payload)
        if "score_breakdown" in data and isinstance(data["score_breakdown"], dict):
            bd = data["score_breakdown"]
            if "total" not in bd:
                bd = dict(bd)
        if "compliance_check" in data and data["compliance_check"]:
            data["compliance_check"] = ComplianceCheckResult.model_validate(data["compliance_check"])
        data.setdefault("approval_report", "")
        return cls.model_validate(data)


class UnderwritingApproveResponse(BaseModel):
    applicant_id: str
    task_id: str
    status: Literal["PENDING"] = "PENDING"


class UnderwritingApproveStatusResponse(BaseModel):
    applicant_id: str
    task_id: str
    status: str
    applicant_status: str | None = None
    decision: str | None = None
    risk_score: int | None = None
    risk_grade: str | None = None
    suggested_amount: float | None = None
    suggested_rate: float | None = None
    score_breakdown: ScoreBreakdown | None = None
    decision_reasons: list[str] = Field(default_factory=list)
    risk_warnings: list[str] = Field(default_factory=list)
    compliance_check: ComplianceCheckResult | None = None
    execution_log: list[dict] = Field(default_factory=list)
    total_latency_ms: int | None = None
    error_detail: str | None = None
    result: dict | None = None
    approval_report: str | None = None

    @classmethod
    def from_task_and_applicant(
        cls,
        applicant_id: str,
        task_id: str,
        task_status: dict,
        applicant_row: dict | None,
        decision_payload: dict | None = None,
    ) -> "UnderwritingApproveStatusResponse":
        normalized = (task_status.get("status") or "PENDING").upper()
        applicant_status = (applicant_row or {}).get("status")
        decision = decision_payload or {}

        if normalized == "SUCCESS" and applicant_status in {"APPROVED", "REJECTED", "MANUAL_REVIEW"}:
            business_status = applicant_status
        elif normalized in {"PENDING", "RUNNING", "FAILURE"}:
            business_status = normalized
        else:
            business_status = applicant_status or normalized

        score_breakdown = None
        if decision.get("score_breakdown"):
            score_breakdown = ScoreBreakdown.model_validate(decision["score_breakdown"])

        compliance = None
        if decision.get("compliance_check"):
            compliance = ComplianceCheckResult.model_validate(decision["compliance_check"])

        reasons = decision.get("decision_reasons") or []
        if isinstance(reasons, str):
            reasons = [reasons]
        warnings = decision.get("risk_warnings") or []
        if isinstance(warnings, str):
            warnings = [warnings]

        return cls(
            applicant_id=applicant_id,
            task_id=task_id,
            status=business_status or normalized,
            applicant_status=applicant_status,
            decision=decision.get("decision") or applicant_status,
            risk_score=decision.get("risk_score") or (applicant_row or {}).get("risk_score"),
            risk_grade=decision.get("risk_grade") or (applicant_row or {}).get("risk_grade"),
            suggested_amount=decision.get("suggested_amount") or (applicant_row or {}).get("approved_amount"),
            suggested_rate=decision.get("suggested_rate") or (applicant_row or {}).get("approved_rate"),
            score_breakdown=score_breakdown,
            decision_reasons=list(reasons),
            risk_warnings=list(warnings),
            compliance_check=compliance,
            execution_log=decision.get("execution_log") or [],
            total_latency_ms=decision.get("total_latency_ms"),
            error_detail=task_status.get("error_detail"),
            result=task_status.get("result"),
            approval_report=decision.get("approval_report") or "",
        )
