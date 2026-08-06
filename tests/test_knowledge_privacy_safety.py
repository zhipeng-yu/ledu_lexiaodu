from __future__ import annotations

import pytest

from lexiaodu.knowledge_semantics import suggest_block_disposition


@pytest.mark.parametrize(
    "text",
    [
        "教师信息：辅导团编号 109498，在读班级信息见内部表格",
        "表扬类型：教师案例；员工编号 204867",
    ],
)
def test_staff_profiles_with_identifiers_are_discarded(text: str) -> None:
    usage, reason, _ = suggest_block_disposition(
        source_name="家长会课件.pptx",
        locator="嵌入图片",
        text=text,
    )

    assert usage == "discarded"
    assert reason
