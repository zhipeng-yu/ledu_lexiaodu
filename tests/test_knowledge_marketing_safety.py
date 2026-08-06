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


@pytest.mark.parametrize(
    ("source_name", "text", "expected_usage", "expected_reason"),
    [
        ("课程说明.docx", "今晚截止礼，报名后赠课。", "pending", "完整审核"),
        ("续报节奏.xlsx", "未回复家长需要再次私信触达。", "discarded", "内部触达"),
        ("顾问话术.xlsx", "妈妈您好，课程内容如下。", "discarded", "内部触达"),
    ],
)
def test_activity_requires_review_and_internal_scripts_are_discarded(
    source_name: str,
    text: str,
    expected_usage: str,
    expected_reason: str,
) -> None:
    usage, reason, _ = suggest_block_disposition(
        source_name=source_name,
        locator="执行内容",
        text=text,
    )

    assert usage == expected_usage
    assert expected_reason in reason


def test_classroom_activity_is_not_treated_as_marketing() -> None:
    usage, _, _ = suggest_block_disposition(
        source_name="语文课程说明.docx",
        locator="课程大纲",
        text="课堂活动包含分组阅读和写作练习。",
    )

    assert usage == "advisor"
