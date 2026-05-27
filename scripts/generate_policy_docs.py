"""
从 underwriting_policy.py 反推生成授信政策文档（需 LLM API）。

运行: python scripts/generate_policy_docs.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_openai import ChatOpenAI

from src.config import settings

POLICIES_DIR = Path(__file__).resolve().parent.parent / "docs" / "policies"


def extract_rules_from_policy() -> dict:
    return {
        "评分规则": {
            "FICO评分": {
                "映射": [
                    {"区间": "<600", "得分": 0},
                    {"区间": "600-649", "得分": 100},
                    {"区间": "650-699", "得分": 200},
                    {"区间": "700-749", "得分": 300},
                    {"区间": "≥750", "得分": 400},
                ],
            },
            "DTI负债收入比": {
                "映射": [
                    {"区间": ">50%", "得分": 0},
                    {"区间": "30%-50%", "得分": 100},
                    {"区间": "<30%", "得分": 200},
                ],
            },
        },
        "等级映射": {
            "映射": [
                {"总分": "≥800", "等级": "A"},
                {"总分": "700-799", "等级": "B"},
                {"总分": "600-699", "等级": "C"},
                {"总分": "500-599", "等级": "D"},
                {"总分": "400-499", "等级": "E"},
                {"总分": "300-399", "等级": "F"},
                {"总分": "<300", "等级": "G"},
            ],
        },
        "决策规则": {
            "规则": [
                {"条件": "A/B级且同类M3+逾期率≤10%", "决策": "APPROVED", "额度比例": "100%"},
                {"条件": "C级或同类M3+逾期率≤15%", "决策": "APPROVED", "额度比例": "70%"},
                {"条件": "D/E级或同类M3+逾期率≤25%", "决策": "MANUAL_REVIEW", "额度比例": "50%"},
                {"条件": "F/G级或同类M3+逾期率>25%", "决策": "REJECTED", "额度比例": "0%"},
            ],
        },
        "利率定价": {
            "映射": [
                {"等级": "A/B", "利率": "10.0%"},
                {"等级": "C", "利率": "12.5%"},
                {"等级": "D/E", "利率": "18.0%"},
                {"等级": "F/G", "利率": "24.0%"},
            ],
        },
        "硬合规红线": {
            "利率上限": "年化利率不超过36%",
            "额度上限": "个人贷款不超过20万元",
            "收入倍数": "批准额度不超过年收入3倍",
            "用途禁入": "不得用于赌博、违规投资",
        },
    }


POLICY_TOPICS = [
    {"filename": "授信审批管理办法.txt", "focus": "审批决策规则", "rules_to_include": ["决策规则", "等级映射"]},
    {"filename": "额度管理办法.txt", "focus": "额度管理", "rules_to_include": ["决策规则", "硬合规红线"]},
    {"filename": "风险定价管理办法.txt", "focus": "利率定价", "rules_to_include": ["利率定价", "硬合规红线"]},
    {"filename": "贷前调查与审核操作规程.txt", "focus": "审核流程", "rules_to_include": ["评分规则"]},
    {"filename": "负面清单与禁入规则.txt", "focus": "禁入条件", "rules_to_include": ["硬合规红线", "评分规则"]},
    {"filename": "资金用途管理规定.txt", "focus": "资金用途", "rules_to_include": ["硬合规红线"]},
    {"filename": "贷后监控与风险预警管理办法.txt", "focus": "贷后监控", "rules_to_include": []},
]

GENERATION_SYSTEM_PROMPT = """你是一家中国持牌消费金融公司的合规部文档撰写专家。
将系统内置授信规则展开为红头文件格式。所有量化阈值必须与提供的规则数据完全一致，不得修改数字。"""


def _subset_rules(rules: dict, paths: list[str]) -> dict:
    out = {}
    for path in paths:
        parts = path.split(".")
        d = rules
        for p in parts:
            d = d.get(p, {})
        out[parts[-1]] = d
    return out


def generate_policy_docs() -> list[str]:
    os.makedirs(POLICIES_DIR, exist_ok=True)
    rules = extract_rules_from_policy()
    llm = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0.2,
    )

    generated = []
    for topic in POLICY_TOPICS:
        relevant = _subset_rules(rules, topic["rules_to_include"]) if topic["rules_to_include"] else {}
        prompt = (
            f"{GENERATION_SYSTEM_PROMPT}\n\n"
            f"规则数据:\n{json.dumps(relevant, ensure_ascii=False, indent=2)}\n\n"
            f"主题: {topic['focus']}\n文件名: {topic['filename']}\n请生成文件正文:"
        )
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        filepath = POLICIES_DIR / topic["filename"]
        filepath.write_text(content, encoding="utf-8")
        generated.append(str(filepath))
        print(f"  ✓ {topic['filename']} ({len(content)} chars)")
    return generated


if __name__ == "__main__":
    files = generate_policy_docs()
    print(f"\n生成完成，共 {len(files)} 份 → {POLICIES_DIR}")
