"""一次性修复数据库中僵死的 RUNNING 申请人 → MANUAL_REVIEW"""
from dotenv import load_dotenv
load_dotenv()

import sqlalchemy
from src.database import get_db

with get_db() as conn:
    r = conn.execute(sqlalchemy.text(
        "UPDATE applicants SET status='MANUAL_REVIEW',"
        " decision_reason='服务重启，任务中断，已转人工复核'"
        " WHERE status='RUNNING'"
    ))
    conn.commit()
    print(f"修复了 {r.rowcount} 条僵死 RUNNING 申请人 → MANUAL_REVIEW")
