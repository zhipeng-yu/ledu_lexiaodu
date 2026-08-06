from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from lexiaodu.config import load_settings
from lexiaodu.knowledge import KnowledgeBase, KnowledgeError, KnowledgeType


@dataclass(frozen=True, slots=True)
class QueryCheck:
    query: str
    knowledge_type: KnowledgeType
    expected_document: str


CHECKS = (
    QueryCheck(
        "天津小学三年级数学课程内容怎么安排",
        KnowledgeType.POLICY,
        "小学数学.txt",
    ),
    QueryCheck(
        "初中物理班型定位适合什么学生",
        KnowledgeType.POLICY,
        "初中物理.txt",
    ),
    QueryCheck(
        "线上直播课回放和设备有什么要求",
        KnowledgeType.POLICY,
        "通用师资与学习服务.txt",
    ),
    QueryCheck(
        "家长担心线上课时间太长如何温和回复",
        KnowledgeType.STYLE_CASE,
        "线上体验与课堂时长.txt",
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 Day 5 固定查询 Top 3")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/app.toml"),
        help="TOML 配置文件路径",
    )
    args = parser.parse_args()
    settings = load_settings(args.config)
    knowledge = KnowledgeBase(
        settings.knowledge.root_dir,
        settings.knowledge.database_path,
    )
    failed = False
    for check in CHECKS:
        try:
            results = knowledge.search(check.query, check.knowledge_type)
        except KnowledgeError as exc:
            print(f"[FAIL] {check.query}：{exc}")
            failed = True
            continue
        names = [result.document_name for result in results]
        try:
            rank = names.index(check.expected_document) + 1
        except ValueError:
            print(
                f"[FAIL] {check.query}：{check.expected_document} 未进入 Top 3；"
                f"实际结果：{names or '无'}"
            )
            failed = True
        else:
            print(
                f"[PASS] {check.query}：{check.expected_document}，排名 {rank}"
            )
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
