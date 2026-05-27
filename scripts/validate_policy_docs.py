"""校验 docs/policies 与 underwriting_policy 关键阈值一致性。"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

POLICIES_DIR = Path(__file__).resolve().parent.parent / "docs" / "policies"

# 必须与 underwriting_policy / COMPLIANCE_RULES 一致的关键数字
REQUIRED_MARKERS = [
    ("36", "年化利率36%"),
    ("20万", "个人贷款20万上限"),
    ("3倍", "年收入3倍"),
]


def validate() -> int:
    if not POLICIES_DIR.exists():
        print(f"[SKIP] {POLICIES_DIR} 不存在")
        return 0

    conflicts = []
    for path in sorted(POLICIES_DIR.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        if re.search(r"3[7-9]\s*%|40\s*%", text) and "36" not in text:
            conflicts.append(f"[CONFLICT] {path.name}: 发现可能错误的利率上限表述")
        for marker, desc in REQUIRED_MARKERS:
            if marker in ("3倍",) and marker not in text and "额度管理办法" in path.name:
                conflicts.append(f"[WARN] {path.name}: 未提及 {desc}")

    for line in conflicts:
        print(line)

    if any(c.startswith("[CONFLICT]") for c in conflicts):
        return 1
    print("校验通过（无严重冲突）")
    return 0


if __name__ == "__main__":
    raise SystemExit(validate())
