from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lexiaodu.runtime import user_data_dir


class SettingsError(ValueError):
    """Raised when a settings file is missing or invalid."""


@dataclass(frozen=True, slots=True)
class ChatSettings:
    database_path: Path = field(
        default_factory=lambda: user_data_dir() / "chat.sqlite3"
    )
    context_character_budget: int = 18000


@dataclass(frozen=True, slots=True)
class AppSettings:
    app_name: str = "乐小读"
    chat: ChatSettings = field(default_factory=ChatSettings)


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
    chat = _table(raw, "chat")

    app_name = app.get("name", "乐小读")
    if not isinstance(app_name, str) or not app_name.strip():
        raise SettingsError("app.name 必须是非空字符串")

    chat_database_path = chat.get("database_path")
    if chat_database_path is None:
        database_path = user_data_dir() / "chat.sqlite3"
    elif isinstance(chat_database_path, str) and chat_database_path.strip():
        database_path = Path(chat_database_path)
    else:
        raise SettingsError("chat.database_path 必须是非空字符串")
    return AppSettings(
        app_name=app_name,
        chat=ChatSettings(
            database_path=database_path,
            context_character_budget=_integer(chat, "context_character_budget", 18000),
        ),
    )
