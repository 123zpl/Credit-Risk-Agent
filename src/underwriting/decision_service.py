"""Underwriting decision service with agent integration and rule fallback."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from src.models.underwriting_models import UnderwritingDecision
from src.underwriting.underwriting_policy import make_underwriting_decision, score_applicant


def _extract_json_text(content: str) -> dict:
    if not content:
        return {}
    text = content.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            return {}
    return {}


def build_rule_decision(
    applicant: dict,
    similar: dict,
    score_payload: dict,
) -> dict:
    risk_grade = str(score_payload.get("risk_grade") or "G")
    overdue_rate = float((similar.get("risk_distribution") or {}).get("M3+") or 1.0)
    req_amt = float(applicant.get("requested_amount") or 0)
    policy = make_underwriting_decision(risk_grade, overdue_rate, req_amt, applicant)
    return {
        "decision": policy["decision"],
        "risk_score": int(score_payload.get("total_score") or 0),
        "risk_grade": risk_grade,
        "suggested_amount": policy["suggested_amount"],
        "suggested_rate": policy["suggested_rate"],
        "score_breakdown": score_payload.get("score_breakdown") or {},
        "decision_reasons": policy["decision_reasons"],
        "risk_warnings": policy["risk_warnings"],
    }


def invoke_underwriting_decision(
    applicant: dict,
    similar: dict,
    score_payload: dict | None = None,
    agent_factory: Callable[[], Any] | None = None,
    use_agent: bool = True,
) -> dict:
    """Run agent decision when available; fall back to deterministic rules."""
    if score_payload is None:
        score_payload = score_applicant(applicant)

    rule_decision = build_rule_decision(applicant, similar, score_payload)
    if not use_agent:
        return rule_decision

    try:
        from src.agents.underwriting_agent import create_underwriting_agent

        factory = agent_factory or create_underwriting_agent
        agent = factory()
        prompt = (
            "请基于以下数据给出审批结论，输出严格 JSON，字段包含："
            "decision,risk_score,risk_grade,suggested_amount,suggested_rate,"
            "score_breakdown,decision_reasons,risk_warnings。\n"
            f"applicant={json.dumps(applicant, ensure_ascii=False, default=str)}\n"
            f"similar={json.dumps(similar, ensure_ascii=False, default=str)}\n"
            f"score={json.dumps(score_payload, ensure_ascii=False, default=str)}"
        )
        response = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
        messages = response.get("messages") if isinstance(response, dict) else None
        content = ""
        if messages:
            content = getattr(messages[-1], "content", "") or str(messages[-1])
        elif isinstance(response, dict):
            content = str(response.get("output") or response.get("content") or "")
        else:
            content = str(response)

        parsed = _extract_json_text(content)
        if not parsed.get("decision"):
            return rule_decision

        merged = {**rule_decision, **parsed}
        merged["score_breakdown"] = parsed.get("score_breakdown") or rule_decision["score_breakdown"]
        UnderwritingDecision.from_payload(merged)
        return merged
    except Exception:
        return rule_decision
