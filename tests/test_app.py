from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from lexiaodu.app import (
    _build_generator_from_environment,
    _configure_application,
)
from lexiaodu.font_scaling import ApplicationFontScaler
from lexiaodu.generator import OpenAICompatibleGenerator, SimulatedGenerator


def _clear_generator_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "LEXIAODU_GENERATOR",
        "ARK_API_KEY",
        "ARK_BASE_URL",
        "ARK_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_configure_application_installs_default_font_increase() -> None:
    application = QApplication.instance() or QApplication([])
    original_font = QFont(application.font())
    original_name = application.applicationName()
    original_quit_policy = application.quitOnLastWindowClosed()
    original_delta = application.property(
        "_lexiaodu_font_delta_points"
    )
    base_font = QFont(original_font)
    base_font.setPointSizeF(10.0)
    application.setFont(base_font)

    scaler = _configure_application(application, "乐小读")

    try:
        assert isinstance(scaler, ApplicationFontScaler)
        assert application.applicationName() == "乐小读"
        assert not application.quitOnLastWindowClosed()
        assert scaler.current_point_size == pytest.approx(11.0)
    finally:
        if isinstance(scaler, ApplicationFontScaler):
            application.removeEventFilter(scaler)
            scaler.deleteLater()
        application.setProperty(
            "_lexiaodu_font_delta_points",
            original_delta,
        )
        application.setFont(original_font)
        application.setApplicationName(original_name)
        application.setQuitOnLastWindowClosed(original_quit_policy)
        application.processEvents()


def test_build_generator_defaults_to_local_simulation(monkeypatch) -> None:
    _clear_generator_environment(monkeypatch)

    assert isinstance(
        _build_generator_from_environment(),
        SimulatedGenerator,
    )


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"LEXIAODU_GENERATOR": "unknown"}, "simulated 或 doubao"),
        ({"LEXIAODU_GENERATOR": "doubao"}, "ARK_API_KEY"),
        (
            {
                "LEXIAODU_GENERATOR": "doubao",
                "ARK_API_KEY": "test-key",
            },
            "ARK_MODEL",
        ),
        (
            {
                "LEXIAODU_GENERATOR": "doubao",
                "ARK_API_KEY": "中文-key",
                "ARK_MODEL": "model",
            },
            "非 ASCII",
        ),
        (
            {
                "LEXIAODU_GENERATOR": "doubao",
                "ARK_API_KEY": "test-key",
                "ARK_MODEL": "model",
                "ARK_BASE_URL": "http://ark.example/api/v3",
            },
            "HTTPS",
        ),
    ],
)
def test_build_generator_rejects_invalid_environment(
    monkeypatch,
    environment,
    message,
) -> None:
    _clear_generator_environment(monkeypatch)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        _build_generator_from_environment()


def test_build_generator_configures_doubao_client(monkeypatch) -> None:
    _clear_generator_environment(monkeypatch)
    monkeypatch.setenv("LEXIAODU_GENERATOR", "doubao")
    monkeypatch.setenv("ARK_API_KEY", "test-key")
    monkeypatch.setenv("ARK_MODEL", "doubao-test-model")
    monkeypatch.setenv("ARK_BASE_URL", "https://ark.example/api/v3")
    captured = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr("lexiaodu.app.OpenAI", fake_openai)

    generator = _build_generator_from_environment()

    assert isinstance(generator, OpenAICompatibleGenerator)
    assert captured == {
        "api_key": "test-key",
        "base_url": "https://ark.example/api/v3",
        "timeout": 30.0,
        "max_retries": 2,
    }
