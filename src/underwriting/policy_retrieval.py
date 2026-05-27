"""Dual-collection RAG retrieval for underwriting workflow (single invocation point)."""

from __future__ import annotations

import json
import time
from typing import Any

from src.config import settings
from src.infra.rag_search import search_milvus


def build_retrieval_queries(applicant: dict) -> list[str]:
    product = applicant.get("product_type", "")
    purpose = applicant.get("purpose", "")
    amount = float(applicant.get("requested_amount") or 0)
    dti = float(applicant.get("dti") or 0)

    queries = [
        f"{product} 额度管理 授信额度上限",
        f"利率定价 风险定价 {product}",
        f"资金用途 {purpose} 用途管理",
        "负面清单 禁入规则",
    ]
    if dti > 45:
        queries.append("DTI 负债收入比 还款能力")
    if amount > 100000:
        queries.append("大额授信 超额审批 额度审批")
    return queries


def retrieve_policies_payload(applicant: dict, search_fn=search_milvus) -> dict[str, Any]:
    """Search regulation_docs and credit_policies collections; dedupe hits."""
    queries = build_retrieval_queries(applicant)
    all_hits: list[dict] = []

    for q in queries:
        for hit in search_fn(settings.milvus_collection, q, top_k=2):
            item = dict(hit)
            item["collection"] = settings.milvus_collection
            all_hits.append(item)
        for hit in search_fn(settings.credit_policy_collection, q, top_k=3):
            item = dict(hit)
            item["collection"] = settings.credit_policy_collection
            all_hits.append(item)

    seen: set[str] = set()
    deduped: list[dict] = []
    for h in all_hits:
        key = (h.get("text") or "")[:100]
        if key and key not in seen:
            seen.add(key)
            deduped.append(h)

    return {
        "检索时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "检索Query数": len(queries),
        "命中条款数": len(deduped),
        "检索结果": deduped[:15],
    }


def retrieve_policies_from_applicant_info(applicant_info_json: str) -> str:
    """Parse applicant_info tool output and return JSON string for workflow state."""
    try:
        data = json.loads(applicant_info_json)
        applicant = data.get("applicant") or {}
    except Exception:
        applicant = {}
    payload = retrieve_policies_payload(applicant)
    return json.dumps(payload, ensure_ascii=False, indent=2)
