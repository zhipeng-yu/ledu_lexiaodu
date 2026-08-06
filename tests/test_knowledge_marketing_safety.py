from __future__ import annotations

import pytest

from lexiaodu.knowledge_semantics import suggest_block_disposition


@pytest.mark.parametrize(
    "text",
    [
        "这是语言学习黄金时期，抓住后能事半功倍。",
        "现在开始学习后绝对领先同龄人。",
        "名额紧张而且性价比高。",
        "竞品素养不能踏实教授学科内容。",
    ],
)
def test_unverified_marketing_claims_are_discarded(text: str) -> None:
    usage, reason, _ = suggest_block_disposition(
        source_name="顾问话术.docx",
        locator="课程介绍",
        text=text,
    )

    assert usage == "discarded"
    assert "营销主张" in reason
