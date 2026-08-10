from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from lexiaodu.ark_probe import (
    ArkFileApiProbeTransport,
    load_probe_manifest,
    run_probe,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="使用完全虚构样本验证方舟原 PDF 文件输入能力",
    )
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report-json", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    return parser


def main() -> int:
    args = _parser().parse_args()
    load_dotenv()
    api_key = os.environ.get("ARK_API_KEY", "").strip()
    model = os.environ.get("ARK_MODEL", "").strip()
    base_url = os.environ.get(
        "ARK_BASE_URL",
        "https://ark.cn-beijing.volces.com/api/v3",
    ).strip()
    if not api_key or not api_key.isascii():
        raise SystemExit("ARK_API_KEY 缺失或格式无效")
    if not model:
        raise SystemExit("ARK_MODEL 缺失")
    if not base_url.startswith("https://"):
        raise SystemExit("ARK_BASE_URL 必须使用 HTTPS")
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds 必须大于 0")

    cases = load_probe_manifest(args.sample_root, args.manifest)
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=min(args.timeout_seconds, 120.0),
        # File creation is not documented as idempotent. A client-side retry
        # after a response timeout can create an untracked duplicate.
        max_retries=0,
    )
    transport = ArkFileApiProbeTransport(
        client,
        model,
        ready_timeout_seconds=args.timeout_seconds,
    )
    report = run_probe(
        cases,
        transport,
        time.monotonic,
        timeout_seconds=args.timeout_seconds,
    )
    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary = {
        format: decision.to_dict()
        for format, decision in sorted(report.formats.items())
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if all(case.passed for case in report.cases) else 2


if __name__ == "__main__":
    raise SystemExit(main())
