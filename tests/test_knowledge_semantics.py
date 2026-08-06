from __future__ import annotations

import pytest

from lexiaodu.knowledge_semantics import suggest_block_disposition


@pytest.mark.parametrize(
    "text",
    [
        "本月分校续报目标及负责人排期",
        "项目招生目标与内部通达进度",
        "本阶段经营目标和转化目标",
    ],
)
def test_internal_business_targets_are_discarded(text: str) -> None:
    usage, reason, scope = suggest_block_disposition(
        source_name="续报方案.docx",
        locator="内部执行",
        text=text,
    )

    assert usage == "discarded"
    assert scope == "tianjin"
    assert "内部经营" in reason
