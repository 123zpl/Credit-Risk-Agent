"""查询最近失败的 Celery 任务错误信息"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

task_id = sys.argv[1] if len(sys.argv) > 1 else "34ce2ed3-2385-4234-a6e4-945f8be992c9"

from src.infra.celery_app import celery_app
from celery.result import AsyncResult

r = AsyncResult(task_id, app=celery_app)
print(f"Task ID : {task_id}")
print(f"Status  : {r.status}")
print(f"Result  : {r.result}")
if r.status == "FAILURE":
    print(f"Traceback:\n{r.traceback}")
