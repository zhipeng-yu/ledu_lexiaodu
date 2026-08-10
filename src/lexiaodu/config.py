from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SettingsError(ValueError):
    """Raised when a settings file is missing or invalid."""


@dataclass(frozen=True, slots=True)
class CaptureSettings:
    width: int = 480
    height: int = 270


@dataclass(frozen=True, slots=True)
class OcrSettings:
    model_cache_dir: Path = Path("E:/DevCaches/paddlex")


@dataclass(frozen=True, slots=True)
class KnowledgeSettings:
    root_dir: Path = Path("knowledge")
    database_path: Path = Path("data/knowledge.sqlite3")


@dataclass(frozen=True, slots=True)
class KnowledgeImportSettings:
    source_dir: Path = Path("incoming_knowledge")
    staging_dir: Path = Path("artifacts/knowledge-import")
    excluded_source_parts: tuple[str, ...] = ("顾问聊天记录",)


@dataclass(frozen=True, slots=True)
class FeedbackSettings:
    database_path: Path = Path("data/feedback.sqlite3")


@dataclass(frozen=True, slots=True)
class ChatSettings:
    database_path: Path = Path("data/chat.sqlite3")
    attachment_dir: Path = Path("data/chat-attachments")
    recent_message_limit: int = 12
    related_message_limit: int = 4
    context_character_budget: int = 18000


@dataclass(frozen=True, slots=True)
class AppSettings:
    app_name: str = "乐小读"
    capture: CaptureSettings = CaptureSettings()
    ocr: OcrSettings = OcrSettings()
    knowledge: KnowledgeSettings = KnowledgeSettings()
    knowledge_import: KnowledgeImportSettings = KnowledgeImportSettings()
    feedback: FeedbackSettings = FeedbackSettings()
    chat: ChatSettings = ChatSettings()


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
    capture = _table(raw, "capture")
    ocr = _table(raw, "ocr")
    knowledge = _table(raw, "knowledge")
    knowledge_import = _table(raw, "knowledge_import")
    feedback = _table(raw, "feedback")
    chat = _table(raw, "chat")

    app_name = app.get("name", "乐小读")
    if not isinstance(app_name, str) or not app_name.strip():
        raise SettingsError("app.name 必须是非空字符串")

    model_cache_dir = ocr.get("model_cache_dir", "E:/DevCaches/paddlex")
    if not isinstance(model_cache_dir, str) or not model_cache_dir.strip():
        raise SettingsError("ocr.model_cache_dir 必须是非空字符串")

    knowledge_root = knowledge.get("root_dir", "knowledge")
    if not isinstance(knowledge_root, str) or not knowledge_root.strip():
        raise SettingsError("knowledge.root_dir 必须是非空字符串")
    database_path = knowledge.get("database_path", "data/knowledge.sqlite3")
    if not isinstance(database_path, str) or not database_path.strip():
        raise SettingsError("knowledge.database_path 必须是非空字符串")
    import_source_dir = knowledge_import.get("source_dir", "incoming_knowledge")
    if not isinstance(import_source_dir, str) or not import_source_dir.strip():
        raise SettingsError("knowledge_import.source_dir 必须是非空字符串")
    import_staging_dir = knowledge_import.get(
        "staging_dir", "artifacts/knowledge-import"
    )
    if not isinstance(import_staging_dir, str) or not import_staging_dir.strip():
        raise SettingsError("knowledge_import.staging_dir 必须是非空字符串")
    excluded_source_parts = knowledge_import.get(
        "excluded_source_parts", ["顾问聊天记录"]
    )
    if (
        not isinstance(excluded_source_parts, list)
        or not all(
            isinstance(value, str) and value.strip()
            for value in excluded_source_parts
        )
    ):
        raise SettingsError(
            "knowledge_import.excluded_source_parts 必须是非空字符串数组"
        )
    feedback_database_path = feedback.get(
        "database_path", "data/feedback.sqlite3"
    )
    if (
        not isinstance(feedback_database_path, str)
        or not feedback_database_path.strip()
    ):
        raise SettingsError("feedback.database_path 必须是非空字符串")

    chat_database_path = chat.get("database_path", "data/chat.sqlite3")
    if not isinstance(chat_database_path, str) or not chat_database_path.strip():
        raise SettingsError("chat.database_path must be a non-empty string")
    chat_attachment_dir = chat.get("attachment_dir", "data/chat-attachments")
    if not isinstance(chat_attachment_dir, str) or not chat_attachment_dir.strip():
        raise SettingsError("chat.attachment_dir must be a non-empty string")

    return AppSettings(
        app_name=app_name,
        capture=CaptureSettings(
            width=_integer(capture, "width", 480),
            height=_integer(capture, "height", 270),
        ),
        ocr=OcrSettings(model_cache_dir=Path(model_cache_dir)),
        knowledge=KnowledgeSettings(
            root_dir=Path(knowledge_root),
            database_path=Path(database_path),
        ),
        knowledge_import=KnowledgeImportSettings(
            source_dir=Path(import_source_dir),
            staging_dir=Path(import_staging_dir),
            excluded_source_parts=tuple(excluded_source_parts),
        ),
        feedback=FeedbackSettings(
            database_path=Path(feedback_database_path),
        ),
        chat=ChatSettings(
            database_path=Path(chat_database_path),
            attachment_dir=Path(chat_attachment_dir),
            recent_message_limit=_integer(chat, "recent_message_limit", 12),
            related_message_limit=_integer(chat, "related_message_limit", 4),
            context_character_budget=_integer(chat, "context_character_budget", 18000),
        ),
    )
