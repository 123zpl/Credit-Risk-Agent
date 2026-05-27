"""Underwriting tools for pre-loan credit decision flow."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from src.database import execute_readonly_sql
from src.models.underwriting_models import ComplianceCheckResult, ScoreBreakdown, UnderwritingDecision
from src.tools.rag_tools import COMPLIANCE_RULES
from src.underwriting.underwriting_policy import score_applicant
from src.config import settings
from src.infra.rag_search import search_milvus


def _fetch_applicant(applicant_id: str) -> dict:
    rows = execute_readonly_sql(
        "SELECT * FROM applicants WHERE applicant_id = :aid",
        {"aid": applicant_id},
    )
    if not rows:
        raise ValueError("申请人不存在")
    return rows[0]


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _calc_percentiles(applicant: dict) -> dict:
    rows = execute_readonly_sql(
        """
        SELECT
            COUNT(*) as total_cnt,
            SUM(CASE WHEN annual_income <= :income THEN 1 ELSE 0 END) as income_lt,
            SUM(CASE WHEN fico_score_low <= :fico THEN 1 ELSE 0 END) as fico_lt,
            SUM(CASE WHEN dti <= :dti THEN 1 ELSE 0 END) as dti_lt
        FROM user_profiles
        WHERE annual_income IS NOT NULL AND fico_score_low IS NOT NULL AND dti IS NOT NULL
        """,
        {
            "income": _safe_float(applicant.get("annual_income")),
            "fico": int(applicant.get("fico_score") or 0),
            "dti": _safe_float(applicant.get("dti")),
        },
    )
    if not rows or not rows[0].get("total_cnt"):
        return {"income_pct": 0, "fico_pct": 0, "dti_pct": 0}
    r = rows[0]
    total = max(1, int(r["total_cnt"]))
    return {
        "income_pct": round(_safe_float(r.get("income_lt")) / total * 100, 2),
        "fico_pct": round(_safe_float(r.get("fico_lt")) / total * 100, 2),
        "dti_pct": round(_safe_float(r.get("dti_lt")) / total * 100, 2),
    }


def calculate_risk_score_payload(applicant: dict) -> dict:
    return score_applicant(applicant)


def check_underwriting_compliance_payload(applicant: dict, suggested_amount: float, suggested_rate: float) -> dict:
    checks = {}
    rate_pass = suggested_rate <= COMPLIANCE_RULES["interest_rate_cap"]["threshold"]
    checks["interest_rate"] = {
        "passed": rate_pass,
        "rule": COMPLIANCE_RULES["interest_rate_cap"]["rule"],
    }

    amount_pass = suggested_amount <= COMPLIANCE_RULES["loan_amount_limit"]["threshold"]
    checks["loan_amount"] = {
        "passed": amount_pass,
        "rule": COMPLIANCE_RULES["loan_amount_limit"]["rule"],
    }

    income = _safe_float(applicant.get("annual_income"), 0.0)
    income_cap_pass = suggested_amount <= income * 3 if income > 0 else False
    checks["income_multiple"] = {
        "passed": income_cap_pass,
        "rule": "批准额度不超过年收入3倍",
    }

    purpose = str(applicant.get("purpose") or "")
    purpose_pass = purpose not in {"赌博", "违规投资"}
    checks["purpose"] = {
        "passed": purpose_pass,
        "rule": "借款用途需合规",
    }
    payload = {"checks": checks, "overall_passed": all(v["passed"] for v in checks.values())}
    ComplianceCheckResult.model_validate(payload)
    return payload


def _match_similar_sql(
    fico_lo: int,
    fico_hi: int,
    dti_lo: float,
    dti_hi: float,
    income_lo: float,
    income_hi: float,
    home: str | None,
    emp: str | None,
    top_k: int,
) -> dict:
    clauses = [
        "u.fico_score_low BETWEEN :fico_lo AND :fico_hi",
        "u.dti BETWEEN :dti_lo AND :dti_hi",
        "u.annual_income BETWEEN :income_lo AND :income_hi",
    ]
    params: dict[str, Any] = {
        "fico_lo": fico_lo,
        "fico_hi": fico_hi,
        "dti_lo": dti_lo,
        "dti_hi": dti_hi,
        "income_lo": income_lo,
        "income_hi": income_hi,
        "lim": top_k,
    }
    if home:
        clauses.append("u.home_ownership = :home")
        params["home"] = home
    if emp:
        clauses.append("u.emp_length = :emp")
        params["emp"] = emp

    where_sql = " AND ".join(clauses)
    rows = execute_readonly_sql(
        f"""
        SELECT
            COUNT(*) AS match_count,
            ROUND(SUM(CASE WHEN l.overdue_level='M1' THEN 1 ELSE 0 END)/COUNT(*), 4) AS m1_rate,
            ROUND(SUM(CASE WHEN l.overdue_level='M2' THEN 1 ELSE 0 END)/COUNT(*), 4) AS m2_rate,
            ROUND(SUM(CASE WHEN l.overdue_level IN ('M3','M3+') THEN 1 ELSE 0 END)/COUNT(*), 4) AS m3_rate,
            ROUND(SUM(CASE WHEN l.loan_status='违约' THEN 1 ELSE 0 END)/COUNT(*), 4) AS default_rate,
            ROUND(SUM(CASE WHEN l.loan_status='核销' THEN 1 ELSE 0 END)/COUNT(*), 4) AS chargeoff_rate,
            ROUND(AVG(l.loan_amount), 2) AS avg_loan_amount,
            ROUND(AVG(l.interest_rate), 2) AS avg_interest_rate,
            ROUND(AVG(u.annual_income), 2) AS avg_income,
            ROUND(AVG(u.dti), 2) AS avg_dti,
            ROUND(AVG(u.fico_score_low), 2) AS avg_fico
        FROM user_profiles u
        JOIN loan_records l ON l.user_id = u.user_id
        WHERE {where_sql}
        LIMIT :lim
        """,
        params,
    )
    return rows[0] if rows else {}


def match_similar_users_payload(applicant: dict, top_k: int = 100, min_matches: int = 10) -> dict:
    fico = int(applicant.get("fico_score") or 0)
    dti = _safe_float(applicant.get("dti"))
    income = _safe_float(applicant.get("annual_income"))
    home = applicant.get("home_ownership")
    emp = applicant.get("emp_length")

    relax_steps = [
        {"fico_delta": 30, "dti_delta": 5, "income_ratio": 0.2, "home": home, "emp": emp},
        {"fico_delta": 30, "dti_delta": 5, "income_ratio": 0.2, "home": home, "emp": None},
        {"fico_delta": 30, "dti_delta": 5, "income_ratio": 0.2, "home": None, "emp": None},
        {"fico_delta": 50, "dti_delta": 10, "income_ratio": 0.35, "home": None, "emp": None},
        {"fico_delta": 80, "dti_delta": 15, "income_ratio": 0.5, "home": None, "emp": None},
    ]

    stats: dict = {}
    relaxation_level = 0
    for idx, step in enumerate(relax_steps):
        stats = _match_similar_sql(
            fico_lo=fico - step["fico_delta"],
            fico_hi=fico + step["fico_delta"],
            dti_lo=dti - step["dti_delta"],
            dti_hi=dti + step["dti_delta"],
            income_lo=income * (1 - step["income_ratio"]),
            income_hi=income * (1 + step["income_ratio"]),
            home=step["home"],
            emp=step["emp"],
            top_k=top_k,
        )
        relaxation_level = idx
        if int(stats.get("match_count") or 0) >= min_matches:
            break

    return {
        "match_count": int(stats.get("match_count") or 0),
        "relaxation_level": relaxation_level,
        "risk_distribution": {
            "M1": _safe_float(stats.get("m1_rate")),
            "M2": _safe_float(stats.get("m2_rate")),
            "M3+": _safe_float(stats.get("m3_rate")),
            "default_rate": _safe_float(stats.get("default_rate")),
            "chargeoff_rate": _safe_float(stats.get("chargeoff_rate")),
        },
        "averages": {
            "loan_amount": _safe_float(stats.get("avg_loan_amount")),
            "interest_rate": _safe_float(stats.get("avg_interest_rate")),
            "income": _safe_float(stats.get("avg_income")),
            "dti": _safe_float(stats.get("avg_dti")),
            "fico": _safe_float(stats.get("avg_fico")),
        },
    }


@tool
def get_applicant_info(applicant_id: str) -> str:
    """获取申请人信息与分位数画像。"""
    try:
        applicant = _fetch_applicant(applicant_id)
        return json.dumps(
            {
                "applicant": applicant,
                "percentiles": _calc_percentiles(applicant),
            },
            ensure_ascii=False,
            default=str,
        )
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
def match_similar_users(applicant_id: str, top_k: int = 100) -> str:
    """匹配历史相似用户并返回风险分布统计。"""
    try:
        applicant = _fetch_applicant(applicant_id)
        payload = match_similar_users_payload(applicant, top_k=top_k)
        return json.dumps(payload, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
def calculate_risk_score(applicant_id: str) -> str:
    """按固定评分规则计算申请人风险分和等级。"""
    try:
        applicant = _fetch_applicant(applicant_id)
        payload = calculate_risk_score_payload(applicant)
        ScoreBreakdown.model_validate(payload["score_breakdown"])
        return json.dumps(payload, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
def check_underwriting_compliance(applicant_id: str, suggested_amount: float, suggested_rate: float) -> str:
    """检查授信建议的合规性。"""
    try:
        applicant = _fetch_applicant(applicant_id)
        payload = check_underwriting_compliance_payload(applicant, suggested_amount, suggested_rate)
        return json.dumps(payload, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def validate_underwriting_decision(payload: dict) -> dict:
    """Validate and normalize underwriting decision payload."""
    data = dict(payload)
    data.setdefault("approval_report", "")
    return UnderwritingDecision.from_payload(data).model_dump()


@tool
def search_credit_policies(query: str) -> str:
    """搜索行内授信政策知识库（credit_policies collection）。仅用于模块化测试；workflow 节点直接调用 policy_retrieval。"""
    try:
        hits = search_milvus(settings.credit_policy_collection, query, top_k=5)
    except Exception as e:
        return json.dumps({"检索方式": "授信政策库不可用", "错误": str(e)}, ensure_ascii=False)

    if not hits:
        return json.dumps({"检索方式": "授信政策库无匹配", "提示": "未找到相关政策条款"}, ensure_ascii=False)

    return json.dumps(
        {
            "检索方式": "语义检索(Milvus-授信政策库)",
            "查询内容": query,
            "相关政策条款": hits,
        },
        ensure_ascii=False,
        indent=2,
    )
