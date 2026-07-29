from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from PySide6.QtWidgets import QApplication

from lexiaodu.capture import CaptureError, CaptureResult, QtScreenCapture, screen_bounds
from lexiaodu.config import AppSettings, SettingsError, load_settings
from lexiaodu.domain import centered_region
from lexiaodu.ocr import PaddleOcrEngine
from lexiaodu.toolbar import FloatingToolbar
from lexiaodu.workflow import CaptureController


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="乐小读 Day 2 MVP")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/app.toml"),
        help="TOML 配置文件路径",
    )
    parser.add_argument(
        "--capture-smoke",
        action="store_true",
        help="在内存中截取主屏幕中央区域后退出",
    )
    return parser


def capture_primary_region(settings: AppSettings) -> CaptureResult:
    screen = QApplication.primaryScreen()
    if screen is None:
        raise CaptureError("没有可用的主屏幕")
    region = centered_region(
        screen_bounds(screen),
        settings.capture.width,
        settings.capture.height,
    )
    return QtScreenCapture().capture(region)


def _position_toolbar(toolbar: FloatingToolbar, settings: AppSettings) -> None:
    screen = QApplication.primaryScreen()
    if screen is None:
        return
    available = screen.availableGeometry()
    x = available.x() + (available.width() - toolbar.width()) // 2
    toolbar.move(x, available.y() + settings.toolbar.top_margin)


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.config)
    except SettingsError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2

    application = QApplication([sys.argv[0]])
    application.setApplicationName(settings.app_name)

    if args.capture_smoke:
        try:
            result = capture_primary_region(settings)
        except CaptureError as exc:
            print(f"截图失败: {exc}", file=sys.stderr)
            return 1
        print(
            "内存截图成功: "
            f"{result.pixel_width}x{result.pixel_height}, {result.screen_name}"
        )
        return 0

    toolbar = FloatingToolbar(
        settings.app_name,
        settings.toolbar.width,
        settings.toolbar.height,
    )

    controller = CaptureController(
        toolbar,
        QtScreenCapture(),
        PaddleOcrEngine(settings.ocr.model_cache_dir),
    )
    _position_toolbar(toolbar, settings)
    toolbar.show()
    exit_code = application.exec()
    del controller
    return exit_code


def main() -> int:
    return run()
