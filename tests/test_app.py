from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QTimer
from PySide6.QtGui import QColor, QFont, QImage
from PySide6.QtWidgets import QApplication

from lexiaodu.app import (
    OfflineDemoAssistant,
    _build_generator_from_environment,
    _configure_application,
    _ui_mode_from_environment,
    build_chat_runtime,
    build_legacy_runtime,
    run,
)
from lexiaodu.attachments import AttachmentStore
from lexiaodu.chat_window import ChatMainWindow
from lexiaodu.config import (
    AppSettings,
    ChatSettings,
    FeedbackSettings,
    KnowledgeSettings,
    OcrSettings,
)
from lexiaodu.context import ContextPackage
from lexiaodu.conversations import ConversationRepository
from lexiaodu.font_scaling import ApplicationFontScaler
from lexiaodu.generator import OpenAICompatibleGenerator, SimulatedGenerator
from lexiaodu.local_crypto import DataCipher
from lexiaodu.toolbar import FloatingToolbar


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


class _InertOcr:
    def preload(self) -> None:
        pass


def _runtime_settings(tmp_path) -> AppSettings:
    return AppSettings(
        ocr=OcrSettings(tmp_path / "ocr-cache"),
        knowledge=KnowledgeSettings(
            tmp_path / "knowledge",
            tmp_path / "knowledge.sqlite3",
        ),
        feedback=FeedbackSettings(tmp_path / "feedback.sqlite3"),
        chat=ChatSettings(
            database_path=tmp_path / "chat.sqlite3",
            attachment_dir=tmp_path / "attachments",
        ),
    )


def test_ui_mode_defaults_to_chat_and_legacy_requires_explicit_value(
    monkeypatch,
) -> None:
    monkeypatch.delenv("LEXIAODU_UI_MODE", raising=False)
    assert _ui_mode_from_environment() == "chat"

    monkeypatch.setenv("LEXIAODU_UI_MODE", "legacy")
    assert _ui_mode_from_environment() == "legacy"


def test_build_chat_runtime_shows_chat_window_with_independent_single_workers(
    tmp_path,
    monkeypatch,
) -> None:
    application = _application()
    application.setQuitOnLastWindowClosed(False)
    monkeypatch.setattr(
        "lexiaodu.app.DataCipher.open",
        lambda _path: DataCipher(b"c" * 32),
    )
    monkeypatch.setattr(
        "lexiaodu.app.PaddleOcrEngine",
        lambda _path: _InertOcr(),
    )

    runtime = build_chat_runtime(_runtime_settings(tmp_path), OfflineDemoAssistant())

    try:
        assert isinstance(runtime.window, ChatMainWindow)
        assert runtime.window.isVisible()
        assert not any(
            isinstance(widget, FloatingToolbar)
            for widget in application.topLevelWidgets()
        )
        assert runtime.assistant_executor is not runtime.ocr_executor
        assert runtime.assistant_executor._max_workers == 1
        assert runtime.ocr_executor._max_workers == 1
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
    monkeypatch.setattr(
        "lexiaodu.app.PaddleOcrEngine",
        lambda _path: _InertOcr(),
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
    with pytest.raises(RuntimeError):
        runtime.ocr_executor.submit(lambda: None)


def test_chat_startup_replays_pending_attachment_cleanup_idempotently_and_scoped(
    tmp_path,
    monkeypatch,
) -> None:
    _application()
    settings = _runtime_settings(tmp_path)
    cipher = DataCipher(b"c" * 32)
    monkeypatch.setattr("lexiaodu.app.DataCipher.open", lambda _path: cipher)
    monkeypatch.setattr(
        "lexiaodu.app.PaddleOcrEngine",
        lambda _path: _InertOcr(),
    )
    repository = ConversationRepository(settings.chat.database_path, cipher)
    attachments = AttachmentStore(
        settings.chat.attachment_dir,
        repository,
        cipher,
    )
    deleted = repository.create_conversation("deleted cleanup scope")
    active = repository.create_conversation("active cleanup scope")
    image = QImage(2, 2, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    deleted_attachment = attachments.save_image(deleted.id, image)
    active_attachment = attachments.save_image(active.id, image)
    repository.delete_conversation(deleted.id)

    assert deleted_attachment.encrypted_path.exists()
    assert len(repository.list_cleanup_jobs(deleted.id, "delete_attachment")) == 1

    runtime = build_chat_runtime(settings, OfflineDemoAssistant())
    try:
        assert not deleted_attachment.encrypted_path.exists()
        assert active_attachment.encrypted_path.exists()
        assert repository.list_cleanup_jobs(deleted.id, "delete_attachment") == ()
    finally:
        runtime.controller.shutdown()
        runtime.window.close()

    reopened_runtime = build_chat_runtime(settings, OfflineDemoAssistant())
    try:
        assert not deleted_attachment.encrypted_path.exists()
        assert active_attachment.encrypted_path.exists()
        assert repository.list_cleanup_jobs(deleted.id, "delete_attachment") == ()
    finally:
        reopened_runtime.controller.shutdown()
        reopened_runtime.window.close()


def test_build_legacy_runtime_shows_existing_toolbar(tmp_path, monkeypatch) -> None:
    application = _application()
    application.setQuitOnLastWindowClosed(True)
    monkeypatch.setattr(
        "lexiaodu.app.PaddleOcrEngine",
        lambda _path: _InertOcr(),
    )

    runtime = build_legacy_runtime(
        _runtime_settings(tmp_path),
        SimulatedGenerator(),
    )

    try:
        assert isinstance(runtime.toolbar, FloatingToolbar)
        assert runtime.toolbar.isVisible()
        assert not application.quitOnLastWindowClosed()
    finally:
        runtime.controller.shutdown()
        runtime.toolbar.close()


def test_invalid_ui_mode_exits_before_qt_or_runtime_construction(
    tmp_path,
    monkeypatch,
) -> None:
    config = tmp_path / "app.toml"
    config.write_text("", encoding="utf-8")
    monkeypatch.setenv("LEXIAODU_UI_MODE", "unsupported")

    def unexpected_application(_argv):
        raise AssertionError("invalid mode must not construct QApplication")

    monkeypatch.setattr("lexiaodu.app.QApplication", unexpected_application)

    assert run(["--config", str(config)]) == 2


def test_offline_demo_assistant_discloses_limits_without_company_facts() -> None:
    context = ContextPackage((), None, (), (), (), 1)

    answer = OfflineDemoAssistant().respond(context, "request-id")

    assert "离线演示" in answer
    assert "不会查询或编造公司事实" in answer
