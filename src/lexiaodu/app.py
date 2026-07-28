from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

from PySide6.QtWidgets import QApplication

from lexiaodu.capture import CaptureError, CaptureResult, QtScreenCapture, screen_bounds
from lexiaodu.config import AppSettings, SettingsError, load_settings
from lexiaodu.domain import centered_region
from lexiaodu.toolbar import FloatingToolbar


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="乐小读 Day 1 MVP")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/app.toml"),
        help="TOML 配置文件路径",
    )
    parser.add_argument(
        "--capture-smoke",
        type=Path,
        metavar="PNG",
        help="截取主屏幕中央区域后退出",
    )
    return parser


def capture_primary_region(
    settings: AppSettings, output_path: Path
) -> CaptureResult:
    screen = QApplication.primaryScreen()
    if screen is None:
        raise CaptureError("没有可用的主屏幕")
    region = centered_region(
        screen_bounds(screen),
        settings.capture.width,
        settings.capture.height,
    )
    return QtScreenCapture().capture(region, output_path)


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

    if args.capture_smoke is not None:
        try:
            result = capture_primary_region(settings, args.capture_smoke)
        except CaptureError as exc:
            print(f"截图失败: {exc}", file=sys.stderr)
            return 1
        print(
            f"截图成功: {result.output_path} "
            f"({result.pixel_width}x{result.pixel_height}, {result.screen_name})"
        )
        return 0

    toolbar = FloatingToolbar(
        settings.app_name,
        settings.toolbar.width,
        settings.toolbar.height,
    )

    def capture_from_toolbar() -> None:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = settings.capture.output_dir / f"capture-{timestamp}.png"
        try:
            result = capture_primary_region(settings, output_path)
        except CaptureError as exc:
            toolbar.set_status(f"失败：{exc}")
        else:
            toolbar.set_status(f"已保存 {result.output_path.name}")

    toolbar.capture_requested.connect(capture_from_toolbar)
    _position_toolbar(toolbar, settings)
    toolbar.show()
    return application.exec()


def main() -> int:
    return run()
