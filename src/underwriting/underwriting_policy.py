"""Single source of truth for underwriting scoring and decision rules."""

from __future__ import annotations

from typing import Any


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _parse_emp_years(emp: str) -> int:
    emp = str(emp or "")
    if "10+" in emp:
        return 10
    nums = "".join(ch for ch in emp if ch.isdigit())
    return int(nums) if nums else 0


def score_fico(fico: int) -> int:
    if fico < 600:
        return 0
    if fico < 650:
        return 100
    if fico < 700:
        return 200
    if fico < 750:
        return 300
    return 400


def score_dti(dti: float) -> int:
    if dti > 50:
        return 0
    if dti >= 30:
        return 100
    return 200


def score_delinq(delinq: int) -> int:
    return -100 if delinq > 3 else (0 if delinq >= 1 else 100)


def score_emp_length(emp_years: int) -> int:
    return 0 if emp_years < 2 else (50 if emp_years <= 5 else 100)


def score_home(home: str) -> int:
    home = str(home or "").upper()
    if home == "OWN":
        return 100
    if home == "MORTGAGE":
        return 50
    return 0


def score_revol_util(revol: float) -> int:
    if revol > 70:
        return 0
    if revol >= 30:
        return 50
    return 100


def score_inquiries(inq: int) -> int:
    return -50 if inq > 5 else (0 if inq >= 2 else 50)


def grade_from_total_score(total: int) -> str:
    if total >= 800:
        return "A"
    if total >= 700:
        return "B"
    if total >= 600:
        return "C"
    if total >= 500:
        return "D"
    if total >= 400:
        return "E"
    if total >= 300:
        return "F"
    return "G"


def score_applicant(applicant: dict) -> dict:
    fico = int(applicant.get("fico_score") or 0)
    dti = _safe_float(applicant.get("dti"))
    delinq = int(applicant.get("delinq_2yrs") or 0)
    emp_years = _parse_emp_years(str(applicant.get("emp_length") or ""))
    home = str(applicant.get("home_ownership") or "")
    revol = _safe_float(applicant.get("revol_util"))
    inq = int(applicant.get("inq_last_6mths") or 0)

    breakdown = {
        "fico": score_fico(fico),
        "dti": score_dti(dti),
        "delinq": score_delinq(delinq),
        "emp_length": score_emp_length(emp_years),
        "home": score_home(home),
        "revol_util": score_revol_util(revol),
        "inquiries": score_inquiries(inq),
    }
    total = sum(breakdown.values())
    return {
        "score_breakdown": breakdown,
        "total_score": total,
        "risk_grade": grade_from_total_score(total),
    }


def rule_based_decision(risk_grade: str, overdue_rate: float) -> dict:
    grade = (risk_grade or "G").upper()
    if grade in {"A", "B"} and overdue_rate <= 0.10:
        return {"decision": "APPROVED", "amount_ratio": 1.0}
    if grade == "C" or overdue_rate <= 0.15:
        return {"decision": "APPROVED", "amount_ratio": 0.7}
    if grade in {"D", "E"} or overdue_rate <= 0.25:
        return {"decision": "MANUAL_REVIEW", "amount_ratio": 0.5}
    return {"decision": "REJECTED", "amount_ratio": 0.0}


def suggest_rate_for_grade(risk_grade: str) -> float:
    grade = (risk_grade or "G").upper()
    if grade in {"A", "B"}:
        return 10.0
    if grade == "C":
        return 12.5
    if grade in {"D", "E"}:
        return 18.0
    return 24.0


def build_decision_reasons(risk_grade: str, overdue_rate: float, applicant: dict) -> list[str]:
    fico = int(applicant.get("fico_score") or 0)
    dti = _safe_float(applicant.get("dti"))
    reasons = [
        f"历史同类用户M3+逾期率{overdue_rate * 100:.1f}%",
        f"FICO评分{fico}，风险等级{risk_grade}",
    ]
    if dti >= 45:
        reasons.append(f"DTI为{dti:.1f}%，处于偏高区间")
    return reasons


def build_risk_warnings(applicant: dict) -> list[str]:
    warnings: list[str] = []
    dti = _safe_float(applicant.get("dti"))
    if dti >= 45:
        warnings.append(f"DTI偏高({dti:.1f}%)，建议关注还款能力")
    inq = int(applicant.get("inq_last_6mths") or 0)
    if inq > 5:
        warnings.append(f"近6月信用查询{inq}次，存在多头借贷风险")
    return warnings


def make_underwriting_decision(
    risk_grade: str,
    overdue_rate: float,
    requested_amount: float,
    applicant: dict | None = None,
) -> dict:
    base = rule_based_decision(risk_grade, overdue_rate)
    suggested_amount = round(float(requested_amount or 0) * base["amount_ratio"], 2)
    applicant = applicant or {}
    return {
        "decision": base["decision"],
        "suggested_amount": suggested_amount,
        "suggested_rate": suggest_rate_for_grade(risk_grade),
        "decision_reasons": build_decision_reasons(risk_grade, overdue_rate, applicant),
        "risk_warnings": build_risk_warnings(applicant),
    }
