"""
Worker 结果截断与 Supervisor 汇总上下文组装。

策略（5.4）：
1. Worker 写入 state 时用 cap_worker_output 限制单段上限，避免 state/DB 膨胀
2. supervisor_respond 按模块分配字符预算，合规 > 策略 > 风险 > 数据
3. 单段超长时用 head + tail 保留首尾，中间插入省略提示（表格/SQL 类内容更友好）
"""
from __future__ import annotations

SYNTHESIS_MAX_CHARS = 8000
WORKER_OUTPUT_MAX_CHARS = 8000

# (state_key, label, default_budget, min_budget, priority 越高越优先保留)
_SECTION_SPECS = (
    ("data_result", "[数据查询结果]", 2800, 400, 1),
    ("risk_result", "[风险分析结果]", 1400, 300, 2),
    ("strategy_result", "[策略建议]", 1600, 400, 3),
    ("compliance_result", "[合规审查结果]", 2200, 600, 4),
)


def smart_truncate_text(text: str, max_chars: int) -> str:
    """保留首尾的智能截断；短于上限则原样返回。"""
    text = text or ""
    if len(text) <= max_chars:
        return text
    if max_chars < 80:
        return text[:max_chars]

    omitted_placeholder = 99999
    notice = f"\n...[已截断，省略 {omitted_placeholder} 字]...\n"
    usable = max_chars - len(notice)
    if usable < 40:
        return text[:max_chars]

    head_len = int(usable * 0.55)
    tail_len = usable - head_len
    omitted = len(text) - head_len - tail_len
    notice = f"\n...[已截断，省略 {omitted} 字]...\n"
    return text[:head_len] + notice + text[-tail_len:]


def cap_worker_output(text: str, max_chars: int = WORKER_OUTPUT_MAX_CHARS) -> str:
    """Worker/工具输出写入 state 前的上限保护。"""
    return smart_truncate_text(text, max_chars)


def _allocate_section_budgets(
    present: list[tuple[str, str, str, int, int, int]],
    max_total: int,
) -> dict[str, int]:
    """按优先级为各模块分配字符预算（合规等高位模块优先保留）。"""
    budgets = {
        key: min(len(text), default)
        for key, text, _label, default, _min_b, _pri in present
    }

    def _total() -> int:
        return sum(budgets.values())

    while _total() > max_total:
        shrinkable = sorted(
            (
                (pri, key, min_b)
                for key, text, _label, _default, min_b, pri in present
                if budgets[key] > min_b
            ),
            key=lambda item: item[0],
        )
        if shrinkable:
            _pri, key, min_b = shrinkable[0]
            step = min(200, budgets[key] - min_b)
            budgets[key] -= step
            continue

        # 已全部压到 min_budget，再从低优先级继续硬缩
        hard_shrink = sorted(
            ((pri, key) for key, _text, _label, _default, _min_b, pri in present if budgets[key] > 120),
            key=lambda item: item[0],
        )
        if not hard_shrink:
            break
        _pri, key = hard_shrink[0]
        budgets[key] -= min(120, budgets[key] - 80)

    return budgets


def build_worker_results_context(
    *,
    data_result: str = "",
    risk_result: str = "",
    strategy_result: str = "",
    compliance_result: str = "",
    max_total: int = SYNTHESIS_MAX_CHARS,
) -> str:
    """
    将各 Worker 结果组装为 supervisor_respond 的上下文。
    超总长时优先压缩数据查询段，尽量保留合规审查结论。
    """
    values = {
        "data_result": data_result,
        "risk_result": risk_result,
        "strategy_result": strategy_result,
        "compliance_result": compliance_result,
    }
    present = [
        (key, values[key], label, default, min_b, pri)
        for key, label, default, min_b, pri in _SECTION_SPECS
        if values.get(key, "").strip()
    ]
    if not present:
        return ""

    budgets = _allocate_section_budgets(present, max_total)
    parts: list[str] = []
    for key, text, label, _default, _min_b, _pri in present:
        parts.append(f"{label}\n{smart_truncate_text(text, budgets[key])}")
    return "\n\n".join(parts)
