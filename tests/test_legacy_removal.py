from __future__ import annotations

from importlib.util import find_spec
from types import SimpleNamespace

import lexiaodu.app as app
import lexiaodu.chat as chat
from lexiaodu.config import load_settings


class _Application:
    def __init__(self, _argv) -> None:
        pass

    def exec(self) -> int:
        return 0


class _Controller:
    def __init__(self) -> None:
        self.shutdown_called = False

    def shutdown(self) -> None:
        self.shutdown_called = True


def test_legacy_environment_value_cannot_restore_floating_toolbar(
    tmp_path,
    monkeypatch,
) -> None:
    config = tmp_path / "app.toml"
    config.write_text("", encoding="utf-8")
    controller = _Controller()
    chat_calls = []

    monkeypatch.setenv("LEXIAODU_UI_MODE", "legacy")
    monkeypatch.setattr(app, "QApplication", _Application)
    monkeypatch.setattr(app, "_configure_application", lambda *_args: object())
    monkeypatch.setattr(
        app,
        "build_chat_runtime",
        lambda settings, assistant: (
            chat_calls.append((settings, assistant))
            or SimpleNamespace(controller=controller)
        ),
    )
    monkeypatch.setattr(
        app,
        "build_legacy_runtime",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("legacy runtime must not be reachable")
        ),
        raising=False,
    )

    assert app.run(["--config", str(config)]) == 0
    assert len(chat_calls) == 1
    assert controller.shutdown_called


def test_legacy_toolbar_and_workflow_modules_are_removed() -> None:
    assert find_spec("lexiaodu.toolbar") is None
    assert find_spec("lexiaodu.workflow") is None
    assert not hasattr(chat, "AiChatDialog")
    assert not hasattr(app, "LegacyRuntime")
    assert not hasattr(app, "build_legacy_runtime")
    assert not hasattr(app, "_ui_mode_from_environment")


def test_settings_no_longer_expose_toolbar_configuration(tmp_path) -> None:
    config = tmp_path / "app.toml"
    config.write_text("", encoding="utf-8")

    assert not hasattr(load_settings(config), "toolbar")
