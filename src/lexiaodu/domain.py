from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ScreenRegion:
    """A rectangle in Qt logical desktop coordinates."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("截图区域的宽和高必须为正整数")

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def is_within(self, bounds: ScreenRegion) -> bool:
        return (
            self.x >= bounds.x
            and self.y >= bounds.y
            and self.right <= bounds.right
            and self.bottom <= bounds.bottom
        )


def centered_region(
    bounds: ScreenRegion, desired_width: int, desired_height: int
) -> ScreenRegion:
    """Return a centered region, clamped to the supplied screen bounds."""

    if desired_width <= 0 or desired_height <= 0:
        raise ValueError("截图区域的目标宽和高必须为正整数")
    width = min(desired_width, bounds.width)
    height = min(desired_height, bounds.height)
    return ScreenRegion(
        x=bounds.x + (bounds.width - width) // 2,
        y=bounds.y + (bounds.height - height) // 2,
        width=width,
        height=height,
    )


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
