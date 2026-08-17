from pathlib import Path

import pytest

from lexiaodu.config import SettingsError, load_settings


def test_load_project_settings_uses_local_app_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    settings = load_settings(Path("config/app.toml"))

    assert settings.app_name == "乐小读"
    assert settings.chat.database_path == tmp_path / "Lexiaodu" / "chat.sqlite3"
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


def test_explicit_database_path_is_preserved(tmp_path: Path) -> None:
    path = tmp_path / "explicit.toml"
    path.write_text('[chat]\ndatabase_path = "data/test.sqlite3"\n', encoding="utf-8")

    assert load_settings(path).chat.database_path == Path("data/test.sqlite3")
