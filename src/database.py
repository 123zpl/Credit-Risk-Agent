from contextlib import contextmanager

import redis
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from src.config import settings

engine = create_engine(
    settings.mysql_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

redis_client = redis.Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    db=settings.redis_db,
    decode_responses=True,
)


@contextmanager
def get_db() -> Session:
    """获取数据库会话的上下文管理器"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def execute_readonly_sql(sql: str, params: dict | None = None) -> list[dict]:
    """安全执行只读SQL，返回字典列表。白名单模式，仅允许 SELECT/WITH。"""
    sql_stripped = sql.strip().lstrip("(").upper()
    if not (sql_stripped.startswith("SELECT") or sql_stripped.startswith("WITH")):
        raise ValueError("只允许 SELECT/WITH 查询")
    if ";" in sql.rstrip(";"):
        raise ValueError("不允许多条 SQL 语句")

    with get_db() as session:
        result = session.execute(text(sql), params or {})
        columns = list(result.keys())
        rows = result.fetchall()
        return [dict(zip(columns, row)) for row in rows]


def check_connections() -> dict:
    """检查 MySQL 和 Redis 连接状态"""
    status = {"mysql": False, "redis": False}
    try:
        with get_db() as session:
            session.execute(text("SELECT 1"))
        status["mysql"] = True
    except Exception as e:
        status["mysql_error"] = str(e)

    try:
        redis_client.ping()
        status["redis"] = True
    except Exception as e:
        status["redis_error"] = str(e)

    return status
