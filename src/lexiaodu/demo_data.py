from __future__ import annotations

import json
from pathlib import Path

from lexiaodu.domain import ReadingMaterial


class DemoDataError(ValueError):
    """Raised when bundled demonstration data is invalid."""


def load_demo_materials(path: Path) -> list[ReadingMaterial]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DemoDataError(f"演示资料不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DemoDataError(f"演示资料 JSON 格式错误: {exc}") from exc

    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise DemoDataError("仅支持 schema_version=1 的演示资料")
    values = payload.get("materials")
    if not isinstance(values, list):
        raise DemoDataError("materials 必须是数组")

    try:
        return [ReadingMaterial.from_mapping(value) for value in values]
    except (TypeError, ValueError) as exc:
        raise DemoDataError(f"演示资料内容无效: {exc}") from exc
