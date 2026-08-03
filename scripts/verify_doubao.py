from __future__ import annotations

import os
from time import monotonic

from dotenv import load_dotenv

from lexiaodu.app import _build_generator_from_environment
from lexiaodu.generator import GenerationRequest, OpenAICompatibleGenerator
from lexiaodu.knowledge import KnowledgeType, SearchResult


def main() -> int:
    load_dotenv(override=True)
    if os.environ.get("LEXIAODU_GENERATOR", "").strip().casefold() != "doubao":
        print("[FAIL] .env 中的 LEXIAODU_GENERATOR 不是 doubao")
        return 1

    try:
        generator = _build_generator_from_environment()
    except ValueError as exc:
        print(f"[FAIL] 豆包配置无效：{exc}")
        return 1
    if not isinstance(generator, OpenAICompatibleGenerator):
        print("[FAIL] 未装配 OpenAI 兼容生成器")
        return 1

    request = GenerationRequest(
        transcript="家长：虚构测试场景，课程什么时候开始？",
        policy_results=(
            SearchResult(
                knowledge_type=KnowledgeType.POLICY,
                document_name="虚构课程说明.txt",
                locator="开课安排",
                evidence="具体开课时间以当期课程页面和通知为准。",
                score=1.0,
            ),
        ),
        style_results=(),
    )
    started = monotonic()
    try:
        draft = generator.generate(request)
    except Exception as exc:
        print(f"[FAIL] 豆包调用失败：{type(exc).__name__}: {exc}")
        return 1

    print("[PASS] 豆包鉴权、模型调用和 JSON 结构化输出正常")
    print(f"模型：{os.environ.get('ARK_MODEL', '').strip()}")
    print(f"耗时：{monotonic() - started:.2f}s")
    print(f"顾虑摘要非空：{bool(draft.concern_summary)}")
    print(f"微信回复非空：{bool(draft.wechat_reply)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
