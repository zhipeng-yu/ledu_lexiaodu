import sqlite3
from pathlib import Path

import pytest

from lexiaodu.feedback import (
    FeedbackReason,
    FeedbackStore,
    FeedbackSubmission,
)


def test_feedback_store_persists_only_structured_metadata(
    tmp_path: Path,
) -> None:
    database = tmp_path / "feedback.sqlite3"
    store = FeedbackStore(database)
    store.save(
        FeedbackSubmission(
            suggestion_id="suggestion-123",
            useful=False,
            reason=FeedbackReason.MISSING_FACTS,
        )
    )

    with sqlite3.connect(database) as connection:
        columns = [
            row[1]
            for row in connection.execute("PRAGMA table_info(feedback)")
        ]
        record = connection.execute(
            "SELECT suggestion_id, useful, reason FROM feedback"
        ).fetchone()

    assert columns == [
        "id",
        "suggestion_id",
        "useful",
        "reason",
        "created_at",
    ]
    assert "transcript" not in columns
    assert "chat" not in columns
    assert "reply" not in columns
    assert record == ("suggestion-123", 0, "缺少依据")


def test_feedback_reason_must_match_usefulness() -> None:
    with pytest.raises(ValueError, match="不匹配"):
        FeedbackSubmission(
            suggestion_id="suggestion-123",
            useful=True,
            reason=FeedbackReason.MISSING_FACTS,
        )
