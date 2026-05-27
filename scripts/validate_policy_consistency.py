"""
入库前校验：政策/法规 Markdown 文档与代码权威规则源的一致性。

用法:
  python scripts/validate_policy_consistency.py
  python scripts/validate_policy_consistency.py --strict
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.underwriting import underwriting_policy as policy

# Mirrors src/tools/rag_tools.COMPLIANCE_RULES (avoid langchain import)
COMPLIANCE_THRESHOLDS = {
    "interest_rate_cap": 36.0,
    "loan_amount_limit": 200000,
}

POLICIES_DIR = ROOT / "docs" / "policies"
REGULATIONS_DIR = ROOT / "docs" / "regulations"


def _load_docs(directory: Path) -> dict[str, str]:
    texts: dict[str, str] = {}
    for path in sorted(set(directory.glob("*.md")) | set(directory.glob("*.txt"))):
        texts[path.name] = path.read_text(encoding="utf-8")
    return texts


def _all_text(docs: dict[str, str]) -> str:
    return "\n".join(docs.values())


def _must_contain(label: str, corpus: str, needles: list[str]) -> list[str]:
    errors = []
    for needle in needles:
        if needle not in corpus:
            errors.append(f"[{label}] 缺少必需片段: {needle!r}")
    return errors


def _must_contain_in_file(filename: str, content: str, needles: list[str]) -> list[str]:
    errors = []
    for needle in needles:
        if needle not in content:
            errors.append(f"[{filename}] 缺少必需片段: {needle!r}")
    return errors


def validate_global_thresholds(corpus: str) -> list[str]:
    rate_cap = COMPLIANCE_THRESHOLDS["interest_rate_cap"]
    amount_cap = COMPLIANCE_THRESHOLDS["loan_amount_limit"]
    return _must_contain(
        "全局阈值",
        corpus,
        [
            str(int(rate_cap)),
            "36%",
            str(int(amount_cap)),
            "20万",
            "年收入",
            "3倍",
            "负面清单",
            "禁入规则",
            "DTI",
            "还款能力",
            "大额授信",
            "资金用途",
            "用途管理",
        ],
    )


def validate_scoring_alignment(corpus: str) -> list[str]:
    errors: list[str] = []
    # FICO tiers
    for fragment in ["600", "650", "700", "750", "400分", "300分", "200分", "100分"]:
        if fragment not in corpus:
            errors.append(f"[评分] 缺少 FICO 相关片段: {fragment!r}")

    # DTI
    for fragment in ["50%", "30%", "200分", "100分", "0分"]:
        if fragment not in corpus:
            errors.append(f"[评分-DTI] 缺少: {fragment!r}")

    # Grades
    for grade in ["A级", "B级", "C级", "D级", "E级", "F级", "G级"]:
        if grade not in corpus:
            errors.append(f"[等级] 缺少: {grade!r}")

    for total in ["800", "700", "600", "500", "400", "300"]:
        if total not in corpus:
            errors.append(f"[等级总分] 缺少: {total!r}")

    return errors


def validate_decision_alignment(corpus: str) -> list[str]:
    return _must_contain(
        "审批决策",
        corpus,
        [
            "APPROVED",
            "REJECTED",
            "MANUAL_REVIEW",
            "100%",
            "70%",
            "50%",
            "10%",
            "15%",
            "25%",
        ],
    )


def validate_rate_table(corpus: str) -> list[str]:
    expected = {
        "A": policy.suggest_rate_for_grade("A"),
        "C": policy.suggest_rate_for_grade("C"),
        "D": policy.suggest_rate_for_grade("D"),
        "F": policy.suggest_rate_for_grade("F"),
    }
    errors: list[str] = []
    for grade, rate in expected.items():
        rate_str = f"{rate:.1f}%"
        if rate_str not in corpus and str(rate) not in corpus:
            errors.append(f"[利率表] 缺少等级 {grade} 对应利率 {rate_str}")
    return errors


def validate_per_file(docs: dict[str, str]) -> list[str]:
    errors: list[str] = []

    if "授信审批管理办法.md" in docs:
        errors.extend(
            _must_contain_in_file(
                "授信审批管理办法.md",
                docs["授信审批管理办法.md"],
                ["负面清单", "禁入规则", "FICO", "revol_util", "inq_last_6mths"],
            )
        )

    if "额度管理办法.md" in docs:
        errors.extend(
            _must_contain_in_file(
                "额度管理办法.md",
                docs["额度管理办法.md"],
                ["200000", "100000", "额度管理", "授信额度上限"],
            )
        )

    if "风险定价管理办法.md" in docs:
        errors.extend(
            _must_contain_in_file(
                "风险定价管理办法.md",
                docs["风险定价管理办法.md"],
                ["36%", "10.0%", "12.5%", "18.0%", "24.0%", "风险定价"],
            )
        )

    if "互联网贷款管理办法.md" in docs:
        errors.extend(
            _must_contain_in_file(
                "互联网贷款管理办法.md",
                docs["互联网贷款管理办法.md"],
                ["第十四条", "赌博", "违规投资", "200000"],
            )
        )

    purpose_blacklist = {"赌博", "违规投资"}
    for bad in purpose_blacklist:
        if bad not in _all_text(docs):
            errors.append(f"[用途禁入] 全库缺少禁入用途: {bad!r}")

    return errors


def validate_code_snippets_match(corpus: str, strict: bool) -> list[str]:
    """Spot-check that documented score outcomes match live policy functions."""
    errors: list[str] = []
    samples = [
        (650, policy.score_fico(650), 200),
        (720, policy.score_fico(720), 300),
        (55.0, policy.score_dti(55.0), 0),
        (25.0, policy.score_dti(25.0), 200),
        (4, policy.score_delinq(4), -100),
        (0, policy.score_delinq(0), 100),
    ]
    if strict:
        for _inp, actual, expected in samples:
            if actual != expected:
                errors.append(f"[strict] 代码评分漂移: 期望 {expected} 实际 {actual}")
    return errors


def validate_no_stale_txt_if_md_present() -> list[str]:
    errors: list[str] = []
    for directory in (POLICIES_DIR, REGULATIONS_DIR):
        md_names = {p.stem for p in directory.glob("*.md")}
        for txt in directory.glob("*.txt"):
            if txt.stem in md_names:
                errors.append(
                    f"[重复] {txt.relative_to(ROOT)} 与同名 .md 并存，请删除 .txt 避免重复入库"
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate policy/regulation docs vs code")
    parser.add_argument("--strict", action="store_true", help="Also run live policy function spot checks")
    args = parser.parse_args()

    policy_docs = _load_docs(POLICIES_DIR)
    reg_docs = _load_docs(REGULATIONS_DIR)
    all_docs = {**policy_docs, **reg_docs}

    if not all_docs:
        print("ERROR: 未找到任何 .md/.txt 政策或法规文件")
        return 1

    corpus = _all_text(all_docs)
    errors: list[str] = []
    errors.extend(validate_no_stale_txt_if_md_present())
    errors.extend(validate_global_thresholds(corpus))
    errors.extend(validate_scoring_alignment(corpus))
    errors.extend(validate_decision_alignment(corpus))
    errors.extend(validate_rate_table(corpus))
    errors.extend(validate_per_file(all_docs))
    errors.extend(validate_code_snippets_match(corpus, args.strict))

    print(f"已检查 {len(all_docs)} 个文件（policies={len(policy_docs)}, regulations={len(reg_docs)}）")

    if errors:
        print(f"\n发现 {len(errors)} 个问题:\n")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("全部一致性校验通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
