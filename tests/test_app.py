from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from lexiaodu.app import (
    OfflineDemoAssistant,
    _build_conversation_assistant_from_environment,
    _configure_application,
    build_parser,
    build_chat_runtime,
)
from lexiaodu.advisor_assistant import OpenAIConversationAssistant
from lexiaodu.chat_context import ContextPackage
from lexiaodu.chat_repository import ConversationRepository
from lexiaodu.chat_window import ChatMainWindow
from lexiaodu.config import AppSettings, ChatSettings
from lexiaodu.font_scaling import ApplicationFontScaler
from lexiaodu.local_crypto import DataCipher


_APPLICATION: QApplication | None = None


def _application() -> QApplication:
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    return _APPLICATION


def _clear_generator_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "LEXIAODU_GENERATOR",
        "ARK_API_KEY",
        "ARK_BASE_URL",
        "ARK_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_default_parser_has_no_legacy_knowledge_or_ocr_actions() -> None:
    help_text = build_parser().format_help().casefold()

    assert "knowledge" not in help_text
    assert "ocr" not in help_text


def test_configure_application_installs_default_font_increase() -> None:
    application = _application()
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
        application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        application.processEvents()


def test_build_assistant_defaults_to_doubao_and_requires_credentials(monkeypatch) -> None:
    _clear_generator_environment(monkeypatch)

    with pytest.raises(ValueError, match="ARK_API_KEY"):
        _build_conversation_assistant_from_environment()


def test_build_assistant_uses_offline_demo_only_when_explicit(monkeypatch) -> None:
    _clear_generator_environment(monkeypatch)
    monkeypatch.setenv("LEXIAODU_GENERATOR", "simulated")

    assert isinstance(
        _build_conversation_assistant_from_environment(),
        OfflineDemoAssistant,
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
def test_build_assistant_rejects_invalid_environment(
    monkeypatch,
    environment,
    message,
) -> None:
    _clear_generator_environment(monkeypatch)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        _build_conversation_assistant_from_environment()


def test_build_assistant_configures_doubao_client(monkeypatch) -> None:
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

    assistant = _build_conversation_assistant_from_environment()

    assert isinstance(assistant, OpenAIConversationAssistant)
    assert captured == {
        "api_key": "test-key",
        "base_url": "https://ark.example/api/v3",
        "timeout": 30.0,
        "max_retries": 2,
    }


def _runtime_settings(tmp_path) -> AppSettings:
    return AppSettings(
        chat=ChatSettings(
            database_path=tmp_path / "chat.sqlite3",
        ),
    )


def test_build_chat_runtime_shows_chat_window_with_single_assistant_worker(
    tmp_path,
    monkeypatch,
) -> None:
    application = _application()
    application.setQuitOnLastWindowClosed(False)
    monkeypatch.setattr(
        "lexiaodu.app.DataCipher.open",
        lambda _path: DataCipher(b"c" * 32),
    )
    runtime = build_chat_runtime(_runtime_settings(tmp_path), OfflineDemoAssistant())

    try:
        assert isinstance(runtime.window, ChatMainWindow)
        assert runtime.window.isVisible()
        assert runtime.assistant_executor._max_workers == 1
    finally:
        runtime.controller.shutdown()
        runtime.window.close()


def test_closing_default_chat_quits_event_loop_and_shuts_down_workers(
    tmp_path,
    monkeypatch,
) -> None:
    application = _application()
    application.setQuitOnLastWindowClosed(False)
    monkeypatch.setattr(
        "lexiaodu.app.DataCipher.open",
        lambda _path: DataCipher(b"c" * 32),
    )
    runtime = build_chat_runtime(_runtime_settings(tmp_path), OfflineDemoAssistant())
    watchdog = QTimer()
    watchdog.setSingleShot(True)
    timed_out: list[bool] = []

    def stop_hung_event_loop() -> None:
        timed_out.append(True)
        application.quit()

    watchdog.timeout.connect(stop_hung_event_loop)
    watchdog.start(500)
    QTimer.singleShot(0, runtime.window.close)

    try:
        application.exec()
    finally:
        watchdog.stop()
        runtime.controller.shutdown()
        runtime.window.close()

    assert timed_out == []
    with pytest.raises(RuntimeError):
        runtime.assistant_executor.submit(lambda: None)


def test_offline_demo_assistant_discloses_limits_without_company_facts() -> None:
    context = ContextPackage((), 1)

    answer = OfflineDemoAssistant().respond(context, "request-id")

    assert "离线演示" in answer
    assert "不会查询或编造公司事实" in answer
