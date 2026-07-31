from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from PySide6.QtWidgets import QApplication

from lexiaodu.advice import AdviceService
from lexiaodu.capture import CaptureError, CaptureResult, QtScreenCapture, screen_bounds
from lexiaodu.config import AppSettings, SettingsError, load_settings
from lexiaodu.domain import centered_region
from lexiaodu.feedback import FeedbackStore
from lexiaodu.generator import SimulatedGenerator
from lexiaodu.knowledge import (
    KnowledgeBase,
    KnowledgeError,
    KnowledgeType,
    format_search_results,
)
from lexiaodu.ocr import PaddleOcrEngine
from lexiaodu.risk import DeterministicRiskRules
from lexiaodu.toolbar import FloatingToolbar
from lexiaodu.workflow import CaptureController


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="乐小读 Day 4 MVP")
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
    parser.add_argument(
        "--rebuild-knowledge",
        action="store_true",
        help="从 policy/style_case 子目录重建本地知识索引",
    )
    parser.add_argument("--search", help="从本地知识索引检索文字")
    parser.add_argument(
        "--knowledge-type",
        choices=[value.value for value in KnowledgeType],
        help="检索类型；policy 与 style_case 不会混合",
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


def _configure_application(application: QApplication, app_name: str) -> None:
    application.setApplicationName(app_name)
    application.setQuitOnLastWindowClosed(False)


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.config)
    except SettingsError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2

    if args.search and args.knowledge_type is None:
        print(
            "检索时必须通过 --knowledge-type 指定 policy 或 style_case",
            file=sys.stderr,
        )
        return 2
    if args.knowledge_type and not args.search:
        print("--knowledge-type 只能与 --search 一起使用", file=sys.stderr)
        return 2

    if args.rebuild_knowledge or args.search:
        knowledge = KnowledgeBase(
            settings.knowledge.root_dir,
            settings.knowledge.database_path,
        )
        try:
            if args.rebuild_knowledge:
                report = knowledge.rebuild()
                print(
                    "知识索引重建完成: "
                    f"{report.document_count} 个文档，"
                    f"{report.chunk_count} 个切片，"
                    f"忽略 {report.ignored_file_count} 个非知识文件"
                )
            if args.search:
                results = knowledge.search(
                    args.search,
                    KnowledgeType(args.knowledge_type),
                )
                print(format_search_results(results))
        except KnowledgeError as exc:
            print(f"知识库错误: {exc}", file=sys.stderr)
            return 1
        return 0

    application = QApplication([sys.argv[0]])
    _configure_application(application, settings.app_name)

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
        advice_service=AdviceService(
            KnowledgeBase(
                settings.knowledge.root_dir,
                settings.knowledge.database_path,
            ),
            SimulatedGenerator(),
            DeterministicRiskRules(),
        ),
        feedback_store=FeedbackStore(
            settings.feedback.database_path,
        ),
    )
    application.aboutToQuit.connect(controller.shutdown)
    _position_toolbar(toolbar, settings)
    toolbar.show()
    exit_code = application.exec()
    del controller
    return exit_code


def main() -> int:
    return run()
