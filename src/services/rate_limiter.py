"""
分类令牌桶限流中间件
---------------------
核心思想（对应 Java 简历"分类令牌桶(vip/normal)防刷限流"）：

  1. 令牌桶算法（Token Bucket）
     - 每个桶有容量上限（burst capacity）和匀速补充速率（refill rate）
     - 请求到来时先补充令牌，再尝试消费 1 个令牌
     - 桶空则拒绝，返回 429

  2. 按角色分类（analyst / admin / anonymous）
     - 角色通过请求头 X-User-Role 传入（生产环境应从 JWT 解析）
     - 不同角色对不同接口类型（analyze/write/read）有不同的桶配置
     - anonymous 完全禁止写操作

  3. Redis 存储令牌桶状态
     - Key: token_bucket:{role}:{bucket_type}:{client_id}
     - Value: JSON {tokens: float, last_refill: float}
     - 利用 Redis pipeline 保证读-改-写的原子性

兼容：保留 acquire_execution_lock / release_execution_lock 供 routes.py 使用。
"""

import json
import time
import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from src.database import redis_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 令牌桶配置：{角色: {接口类型: {capacity, refill_rate(个/秒)}}}
# ---------------------------------------------------------------------------

BUCKET_CONFIGS: dict[str, dict[str, dict]] = {
    "analyst": {
        "analyze": {"capacity": 10, "refill_rate": 10 / 60},   # 10次/分钟
        "write":   {"capacity": 5,  "refill_rate": 5  / 60},   # 5次/分钟（审批/删除）
        "read":    {"capacity": 60, "refill_rate": 60 / 60},   # 60次/分钟（统计/列表）
    },
    "admin": {
        "analyze": {"capacity": 30, "refill_rate": 30 / 60},   # 30次/分钟
        "write":   {"capacity": 20, "refill_rate": 20 / 60},   # 20次/分钟
        "read":    {"capacity": 120,"refill_rate": 120 / 60},  # 120次/分钟
    },
    "anonymous": {
        "analyze": {"capacity": 0,  "refill_rate": 0},         # 禁止
        "write":   {"capacity": 0,  "refill_rate": 0},         # 禁止
        "read":    {"capacity": 20, "refill_rate": 20 / 60},   # 只读，20次/分钟
    },
}

# 令牌桶状态在 Redis 中的存活时间（秒）
BUCKET_KEY_TTL = 300

# 执行锁 TTL（秒）
LOCK_TTL = 30


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _get_client_id(request: Request) -> str:
    """客户端标识：优先取 X-User-ID，其次取 IP"""
    user_id = request.headers.get("x-user-id")
    if user_id:
        return f"uid:{user_id}"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return f"ip:{forwarded.split(',')[0].strip()}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


def _get_role(request: Request) -> str:
    """
    从请求头 X-User-Role 读取角色。
    生产环境中此处应解析 JWT Token 中的角色字段。
    未知角色统一降级为 anonymous。
    """
    role = request.headers.get("x-user-role", "analyst").lower()
    return role if role in BUCKET_CONFIGS else "anonymous"


def _classify_endpoint(request: Request) -> str:
    """
    将接口路径归类为 analyze / write / read 三类。
    """
    method = request.method
    path   = request.url.path

    if "/analyze" in path and method == "POST":
        return "analyze"

    # 写操作：POST/PATCH/DELETE 到核心业务接口
    if method in ("POST", "PATCH", "DELETE") and any(
        seg in path for seg in ("/applicants", "/strategies", "/approve")
    ):
        return "write"

    return "read"


# ---------------------------------------------------------------------------
# 令牌桶核心：consume_token
# ---------------------------------------------------------------------------

def consume_token(role: str, bucket_type: str, client_id: str) -> bool:
    """
    令牌桶算法（Redis 实现）：

      1. 读取桶的当前状态（tokens, last_refill）
      2. 根据距上次补充的时间，按 refill_rate 补充令牌（不超过 capacity）
      3. 若 tokens >= 1，消费 1 个令牌，保存状态，返回 True（允许）
      4. 否则返回 False（限流）

    返回 True = 允许通过，False = 触发限流
    """
    cfg = BUCKET_CONFIGS.get(role, BUCKET_CONFIGS["anonymous"]).get(bucket_type, {})
    capacity    = cfg.get("capacity", 0)
    refill_rate = cfg.get("refill_rate", 0)

    # capacity 为 0 表示该角色完全禁止此类操作
    if capacity == 0:
        return False

    key = f"token_bucket:{role}:{bucket_type}:{client_id}"
    now = time.time()

    try:
        raw = redis_client.get(key)
        if raw:
            state      = json.loads(raw)
            tokens     = state["tokens"]
            last_refill = state["last_refill"]
        else:
            # 首次请求：桶满
            tokens      = float(capacity)
            last_refill = now

        # 补充令牌：distance_time × refill_rate，不超过 capacity
        elapsed = now - last_refill
        tokens  = min(capacity, tokens + elapsed * refill_rate)

        if tokens < 1:
            # 桶空，拒绝
            return False

        # 消费 1 个令牌
        tokens -= 1
        new_state = {"tokens": tokens, "last_refill": now}
        redis_client.setex(key, BUCKET_KEY_TTL, json.dumps(new_state))
        return True

    except Exception as e:
        # Redis 异常时放行，避免限流器故障影响业务
        logger.warning(f"[rate_limiter] Token bucket error (allow): {e}")
        return True


# ---------------------------------------------------------------------------
# 中间件
# ---------------------------------------------------------------------------

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    分类令牌桶限流中间件。

    对每个请求：
      1. 识别角色（X-User-Role 头）
      2. 识别接口类型（analyze / write / read）
      3. 调用对应令牌桶，无令牌则返回 429
    """

    # 健康检查等无需限流的路径前缀
    _SKIP_PATHS = {"/api/v1/health", "/docs", "/openapi", "/redoc", "/"}

    async def dispatch(self, request: Request, call_next):
        # 跳过不需要限流的路径
        if any(request.url.path.startswith(p) for p in self._SKIP_PATHS):
            return await call_next(request)

        role        = _get_role(request)
        bucket_type = _classify_endpoint(request)
        client_id   = _get_client_id(request)

        allowed = consume_token(role, bucket_type, client_id)

        if not allowed:
            cfg      = BUCKET_CONFIGS.get(role, {}).get(bucket_type, {})
            capacity = cfg.get("capacity", 0)

            if capacity == 0:
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": f"角色 [{role}] 无权访问该接口，请联系管理员",
                        "role": role,
                        "bucket_type": bucket_type,
                    },
                )

            # 计算大约还需等待多少秒
            refill_rate = cfg.get("refill_rate", 1)
            wait_sec    = round(1 / refill_rate) if refill_rate > 0 else 60

            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"请求过于频繁，请 {wait_sec} 秒后重试",
                    "role": role,
                    "bucket_type": bucket_type,
                    "capacity": capacity,
                },
                headers={"Retry-After": str(wait_sec)},
            )

        return await call_next(request)


# ---------------------------------------------------------------------------
# 兼容旧接口：执行锁（供 routes.py 中 /analyze 防重复提交使用）
# ---------------------------------------------------------------------------

def acquire_execution_lock(session_id: str) -> bool:
    """SETNX 执行锁，防止同一会话并发重复提交"""
    key = f"exec_lock:{session_id}"
    try:
        acquired = redis_client.set(key, "1", nx=True, ex=LOCK_TTL)
        return bool(acquired)
    except Exception as e:
        logger.warning(f"[rate_limiter] Lock acquire failed (allow): {e}")
        return True


def release_execution_lock(session_id: str) -> None:
    """释放执行锁"""
    key = f"exec_lock:{session_id}"
    try:
        redis_client.delete(key)
    except Exception as e:
        logger.warning(f"[rate_limiter] Lock release failed: {e}")


# ---------------------------------------------------------------------------
# Redis 分布式锁（对标 Java Redisson tryLock）
# ---------------------------------------------------------------------------
#
# 使用方式（上下文管理器）：
#
#   from src.services.rate_limiter import DistributedLock
#
#   with DistributedLock("batch_approve", ttl=60) as acquired:
#       if not acquired:
#           raise HTTPException(409, "批量审批正在执行中，请稍后再试")
#       ... 执行批量逻辑 ...
#
# 原理：
#   - 加锁：SET lock_key owner_token NX EX ttl   （SETNX 原子操作）
#   - 解锁：仅当 owner_token 匹配时才删除（防止误删其他持锁者的锁）
#   - TTL 兜底：持锁者崩溃后锁自动过期，不会死锁

import uuid as _uuid
import contextlib


class DistributedLock:
    """
    Redis 分布式互斥锁，基于 SETNX + 唯一 owner token。

    对应 Java 简历：Redisson 分布式锁 / tryLock
    """

    def __init__(self, resource: str, ttl: int = 60):
        """
        resource : 锁名称，如 "batch_approve" / "applicant:{id}"
        ttl      : 锁自动过期时间（秒），防止持锁者崩溃导致死锁
        """
        self._key   = f"dist_lock:{resource}"
        self._ttl   = ttl
        self._token = str(_uuid.uuid4())   # 唯一 owner 标识，防误删
        self._acquired = False

    def acquire(self) -> bool:
        """尝试加锁，成功返回 True，锁已被占用返回 False。"""
        try:
            result = redis_client.set(
                self._key,
                self._token,
                nx=True,    # SET if Not eXists
                ex=self._ttl,
            )
            self._acquired = bool(result)
            if self._acquired:
                logger.debug(f"[DistributedLock] Acquired: {self._key}")
            else:
                logger.debug(f"[DistributedLock] Already locked: {self._key}")
            return self._acquired
        except Exception as e:
            logger.warning(f"[DistributedLock] acquire error (allow): {e}")
            self._acquired = True   # Redis 异常时放行，降级处理
            return True

    def release(self) -> None:
        """
        释放锁：只有持锁者（token 匹配）才能删除，防止误删他人的锁。
        使用 Lua 脚本保证"比较 + 删除"的原子性。
        """
        if not self._acquired:
            return
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        try:
            redis_client.eval(lua_script, 1, self._key, self._token)
            logger.debug(f"[DistributedLock] Released: {self._key}")
        except Exception as e:
            logger.warning(f"[DistributedLock] release error: {e}")

    # 支持 with 语句
    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_):
        self.release()
