from pathlib import Path

import pytest

from lexiaodu.config import SettingsError, load_settings


def test_load_project_settings() -> None:
    settings = load_settings(Path("config/app.toml"))

    assert settings.app_name == "乐小读"
    assert settings.capture.width == 480
    assert settings.ocr.model_cache_dir == Path("E:/DevCaches/paddlex")
    assert settings.knowledge.root_dir == Path("knowledge")
    assert settings.knowledge.database_path == Path("data/knowledge.sqlite3")
    assert settings.knowledge_import.source_dir == Path(
        "E:/Download/word,excle文档汇总/word,excle文档汇总/乐读/数据"
    )
    assert settings.knowledge_import.staging_dir == Path(
        "artifacts/knowledge-import"
    )
    assert settings.knowledge_import.excluded_source_parts == (
        "顾问聊天记录",
    )
    assert settings.feedback.database_path == Path("data/feedback.sqlite3")
    assert settings.chat.database_path == Path("data/chat.sqlite3")
    assert settings.chat.attachment_dir == Path("data/chat-attachments")
    assert settings.chat.recent_message_limit == 12
    assert settings.chat.related_message_limit == 4
    assert settings.chat.context_character_budget == 18000


def test_reject_non_positive_capture_size(tmp_path: Path) -> None:
    path = tmp_path / "invalid.toml"
    path.write_text("[capture]\nwidth = 0\n", encoding="utf-8")

    with pytest.raises(SettingsError, match="width"):
        load_settings(path)


def test_reject_empty_ocr_cache_path(tmp_path: Path) -> None:
    path = tmp_path / "invalid.toml"
    path.write_text('[ocr]\nmodel_cache_dir = "  "\n', encoding="utf-8")

    with pytest.raises(SettingsError, match="model_cache_dir"):
        load_settings(path)


def test_reject_empty_knowledge_database_path(tmp_path: Path) -> None:
    path = tmp_path / "invalid.toml"
    path.write_text('[knowledge]\ndatabase_path = "  "\n', encoding="utf-8")

    with pytest.raises(SettingsError, match="database_path"):
        load_settings(path)


def test_reject_empty_feedback_database_path(tmp_path: Path) -> None:
    path = tmp_path / "invalid.toml"
    path.write_text(
        '[feedback]\ndatabase_path = "  "\n',
        encoding="utf-8",
    )

    with pytest.raises(SettingsError, match="feedback.database_path"):
        load_settings(path)


def test_reject_non_positive_chat_context_character_budget(tmp_path: Path) -> None:
    path = tmp_path / "invalid.toml"
    path.write_text("[chat]\ncontext_character_budget = 0\n", encoding="utf-8")

    with pytest.raises(SettingsError, match="context_character_budget"):
        load_settings(path)
