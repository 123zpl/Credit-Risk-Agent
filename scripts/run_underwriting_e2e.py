"""Run full underwriting chain: insert applicant -> API approve -> Celery -> poll result."""

from __future__ import annotations

import json
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path

import requests
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.database import get_db
from src.services.applicant_service import ensure_applicants_table

BASE = "http://localhost:8000"
POLL_INTERVAL = 2
POLL_TIMEOUT = 180


def insert_typical_applicant() -> str:
    """借呗 + DTI 48 + 申请15万 — 与 RAG 验证样例一致。"""
    ensure_applicants_table()
    applicant_id = "A" + uuid.uuid4().hex[:15]
    row = {
        "applicant_id": applicant_id,
        "name": "E2E测试申请人",
        "annual_income": Decimal("180000.00"),
        "emp_title": "软件工程师",
        "emp_length": "5 years",
        "home_ownership": "MORTGAGE",
        "province": "广东省",
        "city": "深圳市",
        "dti": Decimal("48.00"),
        "fico_score": 720,
        "delinq_2yrs": 0,
        "inq_last_6mths": 3,
        "revol_util": Decimal("45.00"),
        "open_acc": 8,
        "total_acc": 18,
        "pub_rec": 0,
        "requested_amount": Decimal("150000.00"),
        "requested_term": 24,
        "product_type": "借呗",
        "channel": "APP首页",
        "purpose": "家庭装修",
        "status": "PENDING",
    }
    sql = text(
        """
        INSERT INTO applicants (
            applicant_id, name, annual_income, emp_title, emp_length, home_ownership,
            province, city, dti, fico_score, delinq_2yrs, inq_last_6mths, revol_util,
            open_acc, total_acc, pub_rec, requested_amount, requested_term,
            product_type, channel, purpose, status
        ) VALUES (
            :applicant_id, :name, :annual_income, :emp_title, :emp_length, :home_ownership,
            :province, :city, :dti, :fico_score, :delinq_2yrs, :inq_last_6mths, :revol_util,
            :open_acc, :total_acc, :pub_rec, :requested_amount, :requested_term,
            :product_type, :channel, :purpose, :status
        )
        """
    )
    with get_db() as session:
        session.execute(sql, row)
    return applicant_id


def main() -> int:
    print("=" * 60)
    print("贷前授信审批 — 完整链路 E2E")
    print("=" * 60)

    # 0. Health
    h = requests.get(f"{BASE}/api/v1/health", timeout=10)
    h.raise_for_status()
    health = h.json()
    print("\n[Health]", json.dumps(health, ensure_ascii=False))
    for key in ("mysql", "redis", "milvus", "credit_policy_milvus"):
        if not health.get(key):
            print(f"ERROR: {key} not ready")
            return 1

    # 1. Insert applicant
    aid = insert_typical_applicant()
    print(f"\n[1] 创建申请人: {aid}")
    detail = requests.get(f"{BASE}/api/v1/applicants/{aid}", timeout=10).json()
    app = detail.get("applicant") or detail
    print(
        f"    产品={app.get('product_type')} DTI={app.get('dti')} "
        f"申请额={app.get('requested_amount')} FICO={app.get('fico_score')}"
    )

    # 2. Submit approve (async Celery)
    print(f"\n[2] POST /applicants/{aid}/approve")
    r = requests.post(f"{BASE}/api/v1/applicants/{aid}/approve", json={}, timeout=30)
    if r.status_code == 409:
        print("    409 — 可能已有任务在跑，尝试查 PENDING 申请人...")
        return 1
    r.raise_for_status()
    task_id = r.json()["task_id"]
    print(f"    task_id={task_id}")

    # 3. Poll status
    print(f"\n[3] 轮询 approve-status (最多 {POLL_TIMEOUT}s)...")
    deadline = time.time() + POLL_TIMEOUT
    body = {}
    while time.time() < deadline:
        s = requests.get(
            f"{BASE}/api/v1/applicants/{aid}/approve-status",
            params={"task_id": task_id},
            timeout=30,
        )
        s.raise_for_status()
        body = s.json()
        status = body.get("status")
        print(f"    status={status} applicant_status={body.get('applicant_status')}")
        if status in {"APPROVED", "REJECTED", "MANUAL_REVIEW", "FAILURE", "SUCCESS"}:
            if status in {"APPROVED", "REJECTED", "MANUAL_REVIEW"}:
                break
            if status == "SUCCESS" and body.get("decision"):
                break
            if status == "FAILURE":
                print("    error:", body.get("error_detail"))
                return 1
        if status not in {"PENDING", "RUNNING"} and body.get("decision"):
            break
        time.sleep(POLL_INTERVAL)
    else:
        print("ERROR: 轮询超时")
        return 1

    # 4. Summary
    print("\n" + "=" * 60)
    print("[4] 审批结果")
    print("=" * 60)
    summary_keys = [
        "decision", "risk_score", "risk_grade",
        "suggested_amount", "suggested_rate",
        "decision_reasons", "risk_warnings", "compliance_check",
    ]
    for k in summary_keys:
        if k in body and body[k] is not None:
            print(f"  {k}: {json.dumps(body[k], ensure_ascii=False) if isinstance(body[k], (dict, list)) else body[k]}")

    log = body.get("execution_log") or []
    if log:
        print("\n  execution_log:")
        for entry in log:
            agent = entry.get("agent", "?")
            action = entry.get("action", "?")
            result = entry.get("result", "")
            ms = entry.get("latency_ms", "")
            print(f"    - [{agent}] {action}: {result} ({ms}ms)")

    report = body.get("approval_report") or ""
    if report:
        print("\n  approval_report (前800字):")
        print("  " + report[:800].replace("\n", "\n  "))

    result = body.get("result") or {}
    if isinstance(result, dict):
        decision = result.get("decision") or {}
        if isinstance(decision, dict) and decision.get("approval_report") and not report:
            print("\n  approval_report (from task result, 前800字):")
            print("  " + str(decision["approval_report"])[:800].replace("\n", "\n  "))

    print("\nDone.")
    return 0 if body.get("decision") in {"APPROVED", "REJECTED", "MANUAL_REVIEW"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
