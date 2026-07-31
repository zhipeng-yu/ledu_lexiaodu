from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


class FeedbackReason(StrEnum):
    ACCURATE = "依据准确"
    CLEAR = "表达清晰"
    READY_TO_SEND = "可直接使用"
    MISSING_FACTS = "缺少依据"
    TONE = "语气不合适"
    RISK = "风险判断不准确"
    OTHER = "其他"


USEFUL_REASONS = (
    FeedbackReason.ACCURATE,
    FeedbackReason.CLEAR,
    FeedbackReason.READY_TO_SEND,
)
UNHELPFUL_REASONS = (
    FeedbackReason.MISSING_FACTS,
    FeedbackReason.TONE,
    FeedbackReason.RISK,
    FeedbackReason.OTHER,
)


@dataclass(frozen=True, slots=True)
class FeedbackSubmission:
    suggestion_id: str
    useful: bool
    reason: FeedbackReason

    def __post_init__(self) -> None:
        if not self.suggestion_id.strip():
            raise ValueError("建议 ID 不能为空")
        allowed = USEFUL_REASONS if self.useful else UNHELPFUL_REASONS
        if self.reason not in allowed:
            raise ValueError("反馈原因与有用状态不匹配")


class FeedbackStore:
    """Persist only structured feedback metadata, never chat or reply text."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def save(self, submission: FeedbackSubmission) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY,
                    suggestion_id TEXT NOT NULL,
                    useful INTEGER NOT NULL CHECK (useful IN (0, 1)),
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO feedback (
                    suggestion_id, useful, reason, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    submission.suggestion_id,
                    int(submission.useful),
                    submission.reason.value,
                    datetime.now(UTC).isoformat(),
                ),
            )
