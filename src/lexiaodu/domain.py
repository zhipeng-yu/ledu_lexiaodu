from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ReadingMaterial:
    identifier: str
    title: str
    language: str
    content: str
    source_note: str

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "title",
            "language",
            "content",
            "source_note",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} 必须是非空字符串")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ReadingMaterial:
        try:
            return cls(
                identifier=value["id"],
                title=value["title"],
                language=value["language"],
                content=value["content"],
                source_note=value["source_note"],
            )
        except KeyError as exc:
            raise ValueError(f"演示资料缺少字段: {exc.args[0]}") from exc
