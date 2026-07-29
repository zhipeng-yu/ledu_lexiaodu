from pathlib import Path

import pytest

from lexiaodu.config import SettingsError, load_settings


def test_load_project_settings() -> None:
    settings = load_settings(Path("config/app.toml"))

    assert settings.app_name == "乐小读"
    assert settings.capture.width == 480
    assert settings.ocr.model_cache_dir == Path("E:/DevCaches/paddlex")


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
