from pathlib import Path

import pytest

from lexiaodu.config import SettingsError, load_settings


def test_load_project_settings() -> None:
    settings = load_settings(Path("config/app.toml"))

    assert settings.app_name == "乐小读"
    assert settings.chat.database_path == Path("data/chat.sqlite3")
    assert settings.chat.context_character_budget == 18000
    assert not hasattr(settings, "capture")
    assert not hasattr(settings, "ocr")
    assert not hasattr(settings, "knowledge")
    assert not hasattr(settings, "knowledge_import")
    assert not hasattr(settings, "feedback")


def test_reject_non_positive_chat_context_character_budget(tmp_path: Path) -> None:
    path = tmp_path / "invalid.toml"
    path.write_text("[chat]\ncontext_character_budget = 0\n", encoding="utf-8")

    with pytest.raises(SettingsError, match="context_character_budget"):
        load_settings(path)
