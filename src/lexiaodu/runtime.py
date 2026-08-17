from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

from lexiaodu import __version__


_LOGGER = logging.getLogger("lexiaodu")
_LATEST_DIAGNOSTIC: str | None = None
_LOG_PATH: Path | None = None


def resource_path(*parts: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root.joinpath(*parts)


def user_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Lexiaodu"
    return Path.home() / ".lexiaodu"


def configure_diagnostics(log_dir: Path) -> None:
    global _LATEST_DIAGNOSTIC, _LOG_PATH
    log_dir.mkdir(parents=True, exist_ok=True)
    _LOG_PATH = log_dir / "lexiaodu.log"
    _LATEST_DIAGNOSTIC = None
    for existing_handler in _LOGGER.handlers:
        existing_handler.close()
    _LOGGER.handlers.clear()
    handler = RotatingFileHandler(
        _LOG_PATH,
        maxBytes=1_000_000,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _LOGGER.addHandler(handler)
    _LOGGER.setLevel(logging.INFO)
    _LOGGER.propagate = False


def record_error(stage: str, error: BaseException) -> str:
    global _LATEST_DIAGNOSTIC
    error_id = uuid4().hex[:8]
    error_types: list[str] = []
    current: BaseException | None = error
    while current is not None and len(error_types) < 4:
        error_types.append(type(current).__name__)
        current = current.__cause__ or current.__context__
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    error_chain = " -> ".join(error_types)
    _LOGGER.error("id=%s stage=%s types=%s", error_id, stage, error_chain)
    _LATEST_DIAGNOSTIC = "\n".join(
        (
            "乐小读诊断信息",
            f"版本：{__version__}",
            f"时间：{timestamp}",
            f"错误编号：{error_id}",
            f"阶段：{stage}",
            f"错误类型：{error_chain}",
            f"日志位置：{_LOG_PATH or '尚未初始化'}",
        )
    )
    return _LATEST_DIAGNOSTIC


def diagnostic_text() -> str:
    if _LATEST_DIAGNOSTIC is not None:
        return _LATEST_DIAGNOSTIC
    return "\n".join(
        (
            "乐小读诊断信息",
            f"版本：{__version__}",
            "当前没有已记录的错误。",
            f"日志位置：{_LOG_PATH or '尚未初始化'}",
        )
    )
