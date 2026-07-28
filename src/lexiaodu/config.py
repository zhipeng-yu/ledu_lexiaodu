from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SettingsError(ValueError):
    """Raised when a settings file is missing or invalid."""


@dataclass(frozen=True, slots=True)
class ToolbarSettings:
    width: int = 360
    height: int = 52
    top_margin: int = 24


@dataclass(frozen=True, slots=True)
class CaptureSettings:
    width: int = 480
    height: int = 270
    output_dir: Path = Path("artifacts")


@dataclass(frozen=True, slots=True)
class AppSettings:
    app_name: str = "乐小读"
    toolbar: ToolbarSettings = ToolbarSettings()
    capture: CaptureSettings = CaptureSettings()


def _table(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise SettingsError(f"[{name}] 必须是 TOML 表")
    return value


def _integer(
    table: dict[str, Any], name: str, default: int, *, allow_zero: bool = False
) -> int:
    value = table.get(name, default)
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        qualifier = "非负" if allow_zero else "正"
        raise SettingsError(f"{name} 必须是{qualifier}整数")
    return value


def load_settings(path: Path) -> AppSettings:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SettingsError(f"配置文件不存在: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(f"配置文件格式错误: {exc}") from exc

    app = _table(raw, "app")
    toolbar = _table(raw, "toolbar")
    capture = _table(raw, "capture")

    app_name = app.get("name", "乐小读")
    if not isinstance(app_name, str) or not app_name.strip():
        raise SettingsError("app.name 必须是非空字符串")

    output_dir = capture.get("output_dir", "artifacts")
    if not isinstance(output_dir, str) or not output_dir.strip():
        raise SettingsError("capture.output_dir 必须是非空字符串")

    return AppSettings(
        app_name=app_name,
        toolbar=ToolbarSettings(
            width=_integer(toolbar, "width", 360),
            height=_integer(toolbar, "height", 52),
            top_margin=_integer(toolbar, "top_margin", 24, allow_zero=True),
        ),
        capture=CaptureSettings(
            width=_integer(capture, "width", 480),
            height=_integer(capture, "height", 270),
            output_dir=Path(output_dir),
        ),
    )
