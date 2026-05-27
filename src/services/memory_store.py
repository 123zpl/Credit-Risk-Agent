"""
本地 JSONL 对话记忆存储（Local JSONL Memory Store）

设计原则
--------
1. 单一职责：只负责对话 messages 的读写，不关心业务逻辑
2. 接口稳定：对外暴露 load_messages / append_turn / append_turn_async / delete_session，
   内部实现可随时切换（文件 → Redis → DB）而不影响调用方
3. 可扩展：抽象 BaseMemoryStore 协议，便于后续实现 RedisMemoryStore / DBMemoryStore
4. 无副作用：写失败静默 warning，不影响主流程

存储格式（类 Claude Code 风格）
--------------------------------
.agent_memory/
├── session-abc-123.jsonl   ← 每个 session 一个文件
└── session-def-456.jsonl

每行（一条消息）：
  {"role": "user",      "content": "...", "intent": "",         "ts": "ISO8601"}
  {"role": "assistant", "content": "...", "intent": "data_query","ts": "ISO8601"}

使用方式
--------
  from src.services.memory_store import load_messages, append_turn_async

  # 加载全量历史（max_turns=None 表示不截断）
  messages = load_messages(session_id)

  # 异步追加一轮对话（后台线程写盘，不阻塞主流程）
  append_turn_async(session_id, user_query="...", assistant_reply="...", intent="data_query")

异步写入说明
------------
append_turn_async() 使用 daemon 后台线程写盘，与 metrics_cache.py 的异步刷新模式一致。
写入失败只记 warning，不影响 HTTP 响应返回。
"""

from __future__ import annotations

import json
import logging
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 存储目录（项目根目录下，.gitignore 忽略）
# ---------------------------------------------------------------------------
MEMORY_DIR = Path(".agent_memory")
MAX_TURNS_DEFAULT = None    # None = 加载全量历史，不截断；传整数则只保留最近 N 轮
MAX_CONTENT_CHARS = 8000    # 单条消息最大字符数，防止超长内容撑爆 context

# ── 摘要压缩配置（可按需调整） ────────────────────────────────────────────
COMPRESSION_THRESHOLD = 60000   # 超过此 token 数触发后台摘要
RECENT_TURNS_KEEP     = 5      # 压缩后保留的最近对话轮数（原文不压缩）

# 正在进行后台摘要的 session_id 集合（防止同一 session 重复触发）
_summarizing: set[str] = set()

_SNIP_PENDING_NOTICE = "较早对话暂未纳入摘要，仅保留最近对话原文。"


# ---------------------------------------------------------------------------
# 抽象协议：便于后续扩展为 Redis / DB 实现
# ---------------------------------------------------------------------------

@runtime_checkable
class MemoryStoreProtocol(Protocol):
    """对话记忆存储的最小接口定义。"""

    def load_messages(self, session_id: str, max_turns: Optional[int]) -> list[dict]:
        """加载历史 messages。max_turns=None 表示加载全量；传整数则只保留最近 N 轮。"""
        ...

    def append_turn(
        self,
        session_id: str,
        user_query: str,
        assistant_reply: str,
        intent: str,
    ) -> None:
        """追加一轮对话（user + assistant 各一条）。"""
        ...

    def delete_session(self, session_id: str) -> None:
        """删除指定 session 的全部记忆。"""
        ...


class BaseMemoryStore(ABC):
    """抽象基类，子类只需实现三个方法。"""

    @abstractmethod
    def load_messages(self, session_id: str, max_turns: Optional[int] = MAX_TURNS_DEFAULT) -> list[dict]:
        ...

    @abstractmethod
    def append_turn(
        self,
        session_id: str,
        user_query: str,
        assistant_reply: str,
        intent: str = "",
    ) -> None:
        ...

    @abstractmethod
    def delete_session(self, session_id: str) -> None:
        ...


# ---------------------------------------------------------------------------
# 本地 JSONL 实现（默认实现）
# ---------------------------------------------------------------------------

class JsonlMemoryStore(BaseMemoryStore):
    """
    将对话 messages 存储为本地 JSONL 文件。

    文件路径：{memory_dir}/{session_id}.jsonl
    每行一条消息，文本可读，支持 VS Code / 文本编辑器直接查看。
    """

    def __init__(self, memory_dir: Path = MEMORY_DIR):
        self._dir = memory_dir

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str) -> Path:
        # 替换路径不安全字符，防止目录遍历
        safe_id = session_id.replace("/", "_").replace("\\", "_").replace("..", "_")
        return self._dir / f"{safe_id}.jsonl"

    # ── 公开接口 ──────────────────────────────────────────────────────────

    def load_messages(
        self,
        session_id: str,
        max_turns: Optional[int] = MAX_TURNS_DEFAULT,
    ) -> list[dict]:
        """
        加载历史对话 messages。

        max_turns=None（默认）：加载全量历史，不截断。
        max_turns=N          ：只保留最近 N 轮（每轮 = user + assistant 共 2 条）。

        返回格式：
          [
            {"role": "user",      "content": "...", "intent": "",         "ts": "..."},
            {"role": "assistant", "content": "...", "intent": "data_query","ts": "..."},
            ...
          ]
        """
        path = self._session_path(session_id)
        if not path.exists():
            return []

        lines: list[dict] = []
        try:
            with open(path, encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        lines.append(json.loads(raw))
                    except json.JSONDecodeError:
                        logger.warning(f"[MemoryStore] Skipping malformed line in {path}")
        except OSError as e:
            logger.warning(f"[MemoryStore] Failed to read {path}: {e}")
            return []

        # max_turns=None → 全量返回；有限制则截取最近 N 轮（N*2 条消息）
        if max_turns is None:
            return lines
        max_lines = max_turns * 2
        return lines[-max_lines:] if len(lines) > max_lines else lines

    def append_turn_async(
        self,
        session_id: str,
        user_query: str,
        assistant_reply: str,
        intent: str = "",
    ) -> None:
        """
        异步追加一轮对话（后台 daemon 线程写盘），写完后检查是否需要触发摘要压缩。

        - 写入失败只记 warning，不影响 HTTP 响应返回。
        - 压缩触发失败同样静默处理，不影响主流程。
        """
        store_ref = self

        def _worker():
            store_ref.append_turn(session_id, user_query, assistant_reply, intent)
            _maybe_trigger_summarize(session_id, store_ref)

        threading.Thread(
            target=_worker,
            daemon=True,
            name=f"mem-write-{session_id[:8]}",
        ).start()

    def append_turn(
        self,
        session_id: str,
        user_query: str,
        assistant_reply: str,
        intent: str = "",
    ) -> None:
        """追加一轮对话到 JSONL 文件（同步写盘）。写失败静默警告，不影响主流程。"""
        try:
            self._ensure_dir()
            path = self._session_path(session_id)
            ts = datetime.now(timezone.utc).isoformat()

            user_msg = {
                "role": "user",
                "content": user_query[:MAX_CONTENT_CHARS],
                "intent": "",
                "ts": ts,
            }
            assistant_msg = {
                "role": "assistant",
                "content": assistant_reply[:MAX_CONTENT_CHARS],
                "intent": intent,
                "ts": ts,
            }

            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(user_msg, ensure_ascii=False) + "\n")
                f.write(json.dumps(assistant_msg, ensure_ascii=False) + "\n")

        except OSError as e:
            logger.warning(f"[MemoryStore] Failed to append turn for {session_id}: {e}")

    def delete_session(self, session_id: str) -> None:
        """删除指定 session 的记忆文件。"""
        path = self._session_path(session_id)
        try:
            if path.exists():
                path.unlink()
                logger.info(f"[MemoryStore] Deleted memory for session {session_id}")
        except OSError as e:
            logger.warning(f"[MemoryStore] Failed to delete {path}: {e}")

    def list_sessions(self) -> list[str]:
        """列出所有有记忆的 session_id（用于管理/调试）。"""
        if not self._dir.exists():
            return []
        return [p.stem for p in self._dir.glob("*.jsonl")]

    # ── 摘要压缩相关方法 ──────────────────────────────────────────────────

    def _read_all_lines(self, session_id: str) -> list[dict]:
        """读取全量 JSONL（内部工具方法），跳过损坏行，返回 list[dict]。"""
        path = self._session_path(session_id)
        if not path.exists():
            return []
        lines: list[dict] = []
        try:
            with open(path, encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        lines.append(json.loads(raw))
                    except json.JSONDecodeError:
                        logger.warning(f"[MemoryStore] Skipping malformed line in {path}")
        except OSError as e:
            logger.warning(f"[MemoryStore] Failed to read {path}: {e}")
        return lines

    def write_summary_marker(
        self,
        session_id: str,
        summary_text: str,
        covered: int,
    ) -> None:
        """
        向 JSONL 文件追加一条 type=summary 标记行（append-only）。

        格式：{"type":"summary","content":"...","covered":N,"ts":"ISO8601"}
        - covered: 此 summary 所覆盖的 role 消息总条数（不含 summary 行自身）
        - 文件不存在时静默跳过（不应在无历史时写 summary）
        """
        path = self._session_path(session_id)
        if not path.exists():
            logger.warning(
                f"[MemoryStore] write_summary_marker: file not found for {session_id}"
            )
            return
        try:
            ts = datetime.now(timezone.utc).isoformat()
            marker = {
                "type": "summary",
                "content": summary_text,
                "covered": covered,
                "ts": ts,
            }
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(marker, ensure_ascii=False) + "\n")
            logger.info(
                f"[MemoryStore] Summary marker written for {session_id[:8]}, covered={covered}"
            )
        except OSError as e:
            logger.warning(
                f"[MemoryStore] Failed to write summary marker for {session_id}: {e}"
            )

    def load_context_for_llm(self, session_id: str) -> list[dict]:
        """
        返回发给 LLM 的压缩上下文（Claude Code inline_marker + 读路径混合压缩）。

        逻辑（方案 C）：
        1. 有 summary marker → system 摘要 + summary 之后最近 RECENT_TURNS_KEEP 轮
        2. 无 summary 且 token ≤ 阈值 → 全量 role 消息（短会话）
        3. 无 summary 且 token > 阈值：
           a. 若未在摘要中 → 同步尝试 compact（写 summary marker）
           b. 若已有 summary → 按分支 1 返回
           c. 仍无 summary → snip 最近 RECENT_TURNS_KEEP 轮 + system 提示
           d. 并行触发后台摘要（双保险）
        """
        all_lines = self._read_all_lines(session_id)
        if not all_lines:
            return []

        last_summary_idx = _find_last_summary_idx(all_lines)
        if last_summary_idx >= 0:
            return _build_context_with_summary(all_lines, last_summary_idx)

        role_msgs = _role_messages_from_lines(all_lines)
        if not role_msgs:
            return []

        from src.services.token_counter import count_tokens

        if count_tokens(role_msgs) <= COMPRESSION_THRESHOLD:
            return role_msgs

        if session_id not in _summarizing and _run_summarize(session_id, self):
            all_lines = self._read_all_lines(session_id)
            last_summary_idx = _find_last_summary_idx(all_lines)
            if last_summary_idx >= 0:
                return _build_context_with_summary(all_lines, last_summary_idx)

        if session_id not in _summarizing:
            _maybe_trigger_summarize(session_id, self)

        snipped = _tail_role_messages(role_msgs)
        if len(snipped) < len(role_msgs):
            return [
                {"role": "system", "content": f"对话历史摘要：{_SNIP_PENDING_NOTICE}"},
                *snipped,
            ]
        return snipped


def _find_last_summary_idx(all_lines: list[dict]) -> int:
    last_summary_idx = -1
    for i, line in enumerate(all_lines):
        if line.get("type") == "summary":
            last_summary_idx = i
    return last_summary_idx


def _role_messages_from_lines(all_lines: list[dict], after_idx: int = -1) -> list[dict]:
    start = after_idx + 1 if after_idx >= 0 else 0
    return [
        m for m in all_lines[start:]
        if m.get("role") in ("user", "assistant")
    ]


def _tail_role_messages(role_msgs: list[dict], turns: int = RECENT_TURNS_KEEP) -> list[dict]:
    max_lines = turns * 2
    if len(role_msgs) <= max_lines:
        return role_msgs
    return role_msgs[-max_lines:]


def _build_context_with_summary(all_lines: list[dict], last_summary_idx: int) -> list[dict]:
    summary_text = all_lines[last_summary_idx].get("content", "")
    post_summary = _role_messages_from_lines(all_lines, last_summary_idx)
    recent = _tail_role_messages(post_summary)
    system_msg = {"role": "system", "content": f"对话历史摘要：{summary_text}"}
    return [system_msg] + recent


# ---------------------------------------------------------------------------
# 后台摘要触发（模块私有，在 JsonlMemoryStore.append_turn_async 的 worker 内调用）
# ---------------------------------------------------------------------------

def _maybe_trigger_summarize(session_id: str, store: "JsonlMemoryStore") -> None:
    """
    检查 session 的当前 token 数，超过 COMPRESSION_THRESHOLD 时在后台触发摘要压缩。
    同一 session 同时只允许一个摘要任务运行（_summarizing set 保护）。
    """
    if session_id in _summarizing:
        return

    from src.services.token_counter import count_tokens

    all_lines = store._read_all_lines(session_id)
    if not all_lines:
        return

    last_summary_idx = _find_last_summary_idx(all_lines)
    role_msgs_after_summary = _role_messages_from_lines(all_lines, last_summary_idx)

    if count_tokens(role_msgs_after_summary) <= COMPRESSION_THRESHOLD:
        return

    threading.Thread(
        target=_run_summarize,
        args=(session_id, store),
        daemon=True,
        name=f"summarize-{session_id[:8]}",
    ).start()


def _run_summarize(session_id: str, store: "JsonlMemoryStore") -> bool:
    """
    同步执行摘要压缩：生成 summary marker 并 append 到 JSONL。
    成功返回 True；失败或未写入返回 False。
    """
    if session_id in _summarizing:
        return False

    all_lines = store._read_all_lines(session_id)
    if not all_lines:
        return False

    last_summary_idx = _find_last_summary_idx(all_lines)
    messages_to_compress = _role_messages_from_lines(all_lines, last_summary_idx)
    if not messages_to_compress:
        return False

    _summarizing.add(session_id)
    try:
        from src.services.summarization_agent import SummarizationAgent

        previous_summary: str | None = (
            all_lines[last_summary_idx].get("content")
            if last_summary_idx >= 0
            else None
        )

        agent = SummarizationAgent()
        summary_text = agent.summarize(messages_to_compress, previous_summary)

        if not summary_text:
            logger.warning(
                f"[Summarize] Empty summary for {session_id[:8]}, skipping marker"
            )
            return False

        covered = sum(
            1 for m in all_lines
            if m.get("role") in ("user", "assistant")
        )
        store.write_summary_marker(session_id, summary_text, covered=covered)
        logger.info(
            f"[Summarize] Compressed {len(messages_to_compress)} messages "
            f"for session {session_id[:8]}"
        )
        return True
    except Exception as e:
        logger.warning(f"[Summarize] Failed for {session_id[:8]}: {e}")
        return False
    finally:
        _summarizing.discard(session_id)


def _do_summarize(
    session_id: str,
    store: "JsonlMemoryStore",
    all_lines: list[dict] | None = None,
    last_summary_idx: int | None = None,
) -> None:
    """后台线程入口（兼容旧签名，委托 _run_summarize）。"""
    _run_summarize(session_id, store)


# ---------------------------------------------------------------------------
# LangChain message 转换工具（供 workflow.py 使用）
# ---------------------------------------------------------------------------

def to_langchain_messages(messages: list[dict], current_query: str):
    """
    将 JSONL 格式的 messages 列表转为 LangChain message 对象列表，
    并在末尾追加本轮用户问题。

    支持 role=system（对话历史摘要）、user、assistant。
    供 Supervisor 节点调用，保持完整 messages 结构以利用 KV Cache。
    """
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

    lc_messages = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            lc_messages.append(SystemMessage(content=content))
        elif role == "user":
            lc_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            lc_messages.append(AIMessage(content=content))

    # 追加当前轮的用户问题
    lc_messages.append(HumanMessage(content=current_query))
    return lc_messages


# ---------------------------------------------------------------------------
# 默认单例（模块级全局实例，便于直接 import 使用）
# ---------------------------------------------------------------------------

_default_store = JsonlMemoryStore()


def load_messages(session_id: str, max_turns: Optional[int] = MAX_TURNS_DEFAULT) -> list[dict]:
    """从默认存储加载历史 messages。max_turns=None 加载全量（默认）。"""
    return _default_store.load_messages(session_id, max_turns)


def append_turn(
    session_id: str,
    user_query: str,
    assistant_reply: str,
    intent: str = "",
) -> None:
    """向默认存储同步追加一轮对话（阻塞写盘）。"""
    _default_store.append_turn(session_id, user_query, assistant_reply, intent)


def append_turn_async(
    session_id: str,
    user_query: str,
    assistant_reply: str,
    intent: str = "",
) -> None:
    """向默认存储异步追加一轮对话（后台线程写盘，不阻塞主流程）。"""
    _default_store.append_turn_async(session_id, user_query, assistant_reply, intent)


def delete_session(session_id: str) -> None:
    """从默认存储删除指定 session 的记忆。"""
    _default_store.delete_session(session_id)


def list_sessions() -> list[str]:
    """列出所有有记忆的 session_id。"""
    return _default_store.list_sessions()


def load_context_for_llm(session_id: str) -> list[dict]:
    """从默认存储加载压缩后的上下文（发给 LLM 的版本）。"""
    return _default_store.load_context_for_llm(session_id)


def write_summary_marker(session_id: str, summary_text: str, covered: int) -> None:
    """向默认存储写入 summary 标记行。"""
    _default_store.write_summary_marker(session_id, summary_text, covered)
