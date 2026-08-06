from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lexiaodu.advice import AdviceService
from lexiaodu.config import load_settings
from lexiaodu.generator import SimulatedGenerator
from lexiaodu.knowledge import KnowledgeBase, KnowledgeError


DEFAULT_CASES = (
    Path(__file__).parents[1]
    / "tests"
    / "fixtures"
    / "anonymized_advisor_eval.json"
)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="运行匿名化顾问知识评测")
    parser.add_argument("--config", type=Path, default=Path("config/app.toml"))
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    args = parser.parse_args()
    settings = load_settings(args.config)
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    service = AdviceService(
        KnowledgeBase(
            settings.knowledge.root_dir,
            settings.knowledge.database_path,
        ),
        SimulatedGenerator(),
    )
    safety_failed = False
    covered = 0
    for case in cases:
        try:
            suggestion = service.create(str(case["question"]))
        except KnowledgeError as exc:
            print(f"[FAIL] {case['id']}：{exc}")
            safety_failed = True
            continue
        combined = " ".join(
            [suggestion.wechat_reply]
            + [result.evidence for result in suggestion.facts]
        )
        leaked = [
            phrase for phrase in case["forbidden"] if phrase in combined
        ]
        requires_system = bool(case["requires_system_lookup"])
        system_ok = (
            not requires_system
            or (
                not suggestion.facts
                and "系统" in suggestion.concern_summary
            )
        )
        internal_ok = (
            case["id"] != "internal_information_block"
            or not suggestion.facts
        )
        if leaked or not system_ok or not internal_ok:
            print(
                f"[FAIL] {case['id']}：禁用表述={leaked or '无'}，"
                f"系统门槛={system_ok}，内部隔离={internal_ok}"
            )
            safety_failed = True
            continue
        if suggestion.facts:
            covered += 1
            names = [result.document_name for result in suggestion.facts]
            print(f"[PASS] {case['id']}：检索 {len(names)} 条，{names}")
        elif requires_system or case["id"] == "internal_information_block":
            print(f"[PASS] {case['id']}：按门槛不使用知识事实")
        else:
            print(f"[REVIEW] {case['id']}：暂无顾问可用事实")
    print(
        f"汇总：{len(cases)} 题，知识命中 {covered} 题，"
        f"安全失败 {'是' if safety_failed else '否'}"
    )
    return int(safety_failed)


if __name__ == "__main__":
    raise SystemExit(main())
