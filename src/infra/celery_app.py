"""Celery application bootstrap."""

from celery import Celery

from src.config import settings

celery_app = Celery(
    "credit_underwriting",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=False,
    task_track_started=True,
    task_time_limit=300,
    task_soft_time_limit=240,
)

celery_app.autodiscover_tasks(["src.tasks"])
# Ensure task modules are registered (autodiscover only loads tasks.py by default)
import src.tasks.underwriting_tasks  # noqa: F401, E402
