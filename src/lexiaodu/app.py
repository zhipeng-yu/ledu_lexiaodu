from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv
from openai import OpenAI
from PySide6.QtWidgets import QApplication

from lexiaodu.advisor_assistant import OpenAIConversationAssistant
from lexiaodu.attachments import AttachmentStore
from lexiaodu.capture import CaptureError, CaptureResult, QtScreenCapture, screen_bounds
from lexiaodu.chat_controller import ChatController, ConversationAssistant
from lexiaodu.chat_window import ChatMainWindow
from lexiaodu.config import AppSettings, SettingsError, load_settings
from lexiaodu.context import ContextBuilder, ContextPackage
from lexiaodu.conversations import ConversationRepository
from lexiaodu.domain import centered_region
from lexiaodu.editor import TranscriptEditor
from lexiaodu.font_scaling import ApplicationFontScaler
from lexiaodu.generator import (
    Generator,
    OpenAICompatibleGenerator,
    SimulatedGenerator,
)
from lexiaodu.knowledge import (
    KnowledgeBase,
    KnowledgeError,
    KnowledgeType,
    format_search_results,
)
from lexiaodu.knowledge_import import (
    KnowledgeImportError,
    KnowledgeImportService,
    format_coverage_report,
    format_link_report,
    format_policy_report,
    format_semantic_report,
)
from lexiaodu.local_crypto import DataCipher
from lexiaodu.ocr import PaddleOcrEngine
from lexiaodu.selection import SelectionOverlay


@dataclass(slots=True)
class ChatRuntime:
    window: ChatMainWindow
    controller: ChatController
    repository: ConversationRepository
    attachments: AttachmentStore
    context_builder: ContextBuilder
    assistant_executor: ThreadPoolExecutor
    ocr_executor: ThreadPoolExecutor


class OfflineDemoAssistant:
    def respond(self, context: ContextPackage, request_id: str) -> str:
        del context, request_id
        return (
            "这是离线演示回复，不会查询或编造公司事实。"
            "请仅用它检查会话流程，并在正式答复前依据经审核资料人工核实。"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="乐小读五日 MVP")
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
        help="检索类型；policy、style_case 与 source 不会混合",
    )
    parser.add_argument(
        "--include-internal",
        action="store_true",
        help="source 检索时同时包含仅内部可查的原文",
    )
    parser.add_argument(
        "--prepare-knowledge-import",
        action="store_true",
        help="扫描新增或变化的来源资料并生成待审核批次",
    )
    parser.add_argument(
        "--knowledge-source-dir",
        type=Path,
        help="覆盖配置中的知识来源目录，仅与准备导入一起使用",
    )
    parser.add_argument(
        "--review-all-knowledge-sources",
        action="store_true",
        help="准备批次时复用现有修订并重新审核全部来源，不重复提取或 OCR",
    )
    parser.add_argument(
        "--policy-upgrade",
        action="store_true",
        help="仅从正式semantic/source准备policy升级批次，不扫描资料或OCR",
    )
    parser.add_argument(
        "--apply-knowledge-import",
        metavar="BATCH_ID",
        help="应用已审核的知识导入批次并重建索引",
    )
    parser.add_argument(
        "--resume-knowledge-import",
        metavar="BATCH_ID",
        help="从最近完成的文件检查点继续被暂停的导入批次",
    )
    parser.add_argument(
        "--knowledge-link-report",
        action="store_true",
        help="统计引用次数、唯一资料以及已入库/未入库数量",
    )
    parser.add_argument(
        "--knowledge-coverage-report",
        action="store_true",
        help="统计原文修订、内容块、字符和图片 OCR 覆盖情况",
    )
    parser.add_argument(
        "--knowledge-semantic-report",
        action="store_true",
        help="统计语义候选、正式记录、来源绑定、领域、关系和活动状态",
    )
    parser.add_argument(
        "--knowledge-policy-report",
        action="store_true",
        help="统计policy文件、章节及semantic/source证据绑定情况",
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


def _configure_application(
    application: QApplication,
    app_name: str,
) -> ApplicationFontScaler:
    application.setApplicationName(app_name)
    application.setQuitOnLastWindowClosed(False)
    return ApplicationFontScaler(application)


def _console_safe_text(value: str, stream: object | None = None) -> str:
    output = stream if stream is not None else sys.stdout
    encoding = getattr(output, "encoding", None) or "utf-8"
    return value.encode(encoding, errors="replace").decode(encoding)


def _build_generator_from_environment() -> Generator:
    provider = _generator_provider()
    if provider == "simulated":
        return SimulatedGenerator()
    client, model = _build_doubao_client()
    return OpenAICompatibleGenerator(
        client,
        model,
        max_tokens=512,
        extra_body={"thinking": {"type": "disabled"}},
    )


def _generator_provider() -> str:
    provider = os.environ.get("LEXIAODU_GENERATOR", "simulated").strip().casefold()
    if provider not in {"simulated", "doubao"}:
        raise ValueError("LEXIAODU_GENERATOR 必须是 simulated 或 doubao")
    return provider


def _build_doubao_client() -> tuple[OpenAI, str]:
    api_key = os.environ.get("ARK_API_KEY", "").strip()
    if not api_key:
        raise ValueError("启用豆包时必须设置 ARK_API_KEY")
    if not api_key.isascii():
        raise ValueError("ARK_API_KEY 包含非 ASCII 字符")
    model = os.environ.get("ARK_MODEL", "").strip()
    if not model:
        raise ValueError("启用豆包时必须设置 ARK_MODEL")
    base_url = os.environ.get(
        "ARK_BASE_URL",
        "https://ark.cn-beijing.volces.com/api/v3",
    ).strip()
    if not base_url.startswith("https://"):
        raise ValueError("ARK_BASE_URL 必须使用 HTTPS")

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=30.0,
        max_retries=2,
    )
    return client, model


def _build_conversation_assistant_from_environment() -> ConversationAssistant:
    if _generator_provider() == "simulated":
        return OfflineDemoAssistant()
    client, model = _build_doubao_client()
    return OpenAIConversationAssistant(client, model)


def build_chat_runtime(
    settings: AppSettings,
    assistant: ConversationAssistant,
) -> ChatRuntime:
    cipher = DataCipher.open(settings.chat.database_path.with_suffix(".key"))
    repository = ConversationRepository(settings.chat.database_path, cipher)
    attachments = AttachmentStore(
        settings.chat.attachment_dir,
        repository,
        cipher,
    )
    attachments.replay_pending_cleanup_jobs()
    context_builder = ContextBuilder(
        repository,
        recent_limit=settings.chat.recent_message_limit,
        related_limit=settings.chat.related_message_limit,
        character_budget=settings.chat.context_character_budget,
    )
    window = ChatMainWindow()
    assistant_executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="lexiaodu-assistant",
    )
    ocr_executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="lexiaodu-chat-ocr",
    )
    try:
        controller = ChatController(
            window,
            repository,
            attachments,
            context_builder,
            assistant,
            QtScreenCapture(),
            PaddleOcrEngine(settings.ocr.model_cache_dir),
            SelectionOverlay,
            TranscriptEditor,
            assistant_executor,
            ocr_executor,
        )
    except BaseException:
        assistant_executor.shutdown(wait=True, cancel_futures=True)
        ocr_executor.shutdown(wait=True, cancel_futures=True)
        raise
    application = QApplication.instance()
    if application is not None:
        application.setQuitOnLastWindowClosed(True)
        window.close_requested.connect(controller.shutdown)
        window.close_requested.connect(application.quit)
        application.aboutToQuit.connect(controller.shutdown)
    window.show()
    return ChatRuntime(
        window,
        controller,
        repository,
        attachments,
        context_builder,
        assistant_executor,
        ocr_executor,
    )


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.config)
    except SettingsError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2

    if args.search and args.knowledge_type is None:
        print(
            "检索时必须通过 --knowledge-type 指定 policy、style_case 或 source",
            file=sys.stderr,
        )
        return 2
    if args.knowledge_type and not args.search:
        print("--knowledge-type 只能与 --search 一起使用", file=sys.stderr)
        return 2
    if args.include_internal and (
        not args.search or args.knowledge_type != KnowledgeType.SOURCE.value
    ):
        print(
            "--include-internal 只能与 source 检索一起使用",
            file=sys.stderr,
        )
        return 2
    if args.knowledge_source_dir and not (
        args.prepare_knowledge_import or args.resume_knowledge_import
    ):
        print(
            "--knowledge-source-dir 只能与知识导入准备或继续命令一起使用",
            file=sys.stderr,
        )
        return 2
    if args.review_all_knowledge_sources and not args.prepare_knowledge_import:
        print(
            "--review-all-knowledge-sources 只能与 --prepare-knowledge-import 一起使用",
            file=sys.stderr,
        )
        return 2
    if args.policy_upgrade and not args.prepare_knowledge_import:
        print(
            "--policy-upgrade 只能与 --prepare-knowledge-import 一起使用",
            file=sys.stderr,
        )
        return 2
    if args.policy_upgrade and (
        args.review_all_knowledge_sources or args.knowledge_source_dir
    ):
        print(
            "policy升级模式不扫描来源，不能指定来源目录或重新审核全部来源",
            file=sys.stderr,
        )
        return 2

    import_actions = sum(
        bool(value)
        for value in (
            args.prepare_knowledge_import,
            args.resume_knowledge_import,
            args.apply_knowledge_import,
            args.knowledge_link_report,
            args.knowledge_coverage_report,
            args.knowledge_semantic_report,
            args.knowledge_policy_report,
        )
    )
    if import_actions > 1:
        print("知识导入准备、应用和报告命令不能同时执行", file=sys.stderr)
        return 2
    if import_actions:
        service = KnowledgeImportService(
            settings.knowledge.root_dir,
            settings.knowledge.database_path,
            settings.knowledge_import.staging_dir,
            (
                PaddleOcrEngine(settings.ocr.model_cache_dir)
                if (
                    (args.prepare_knowledge_import and not args.policy_upgrade)
                    or args.resume_knowledge_import
                )
                else None
            ),
            settings.knowledge_import.excluded_source_parts,
        )
        try:
            if args.prepare_knowledge_import:
                if args.policy_upgrade:
                    report = service.prepare_policy_upgrade()
                else:
                    source_dir = (
                        args.knowledge_source_dir
                        or settings.knowledge_import.source_dir
                    )
                    report = service.prepare(
                        source_dir,
                        review_all_sources=args.review_all_knowledge_sources,
                    )
                print(
                    f"知识导入批次已准备：{report.batch_id}\n"
                    f"审核文件：{report.review_path}\n"
                    f"审核报告：{report.report_path}\n"
                    f"{format_link_report(report.link_report)}"
                )
            elif args.resume_knowledge_import:
                report = service.resume(
                    args.resume_knowledge_import,
                    args.knowledge_source_dir
                    or settings.knowledge_import.source_dir,
                )
                print(
                    f"知识导入批次已继续并准备完成：{report.batch_id}\n"
                    f"审核文件：{report.review_path}\n"
                    f"审核报告：{report.report_path}\n"
                    f"{format_link_report(report.link_report)}"
                )
            elif args.apply_knowledge_import:
                report = service.apply(args.apply_knowledge_import)
                print(
                    f"知识导入批次已应用：{report.batch_id}；"
                    f"写入 {report.output_count} 个知识文件，"
                    f"索引 {report.indexed_document_count} 个文档/"
                    f"{report.indexed_chunk_count} 个切片；"
                    f"{format_link_report(report.link_report)}"
                )
            elif args.knowledge_link_report:
                print(format_link_report(service.link_report()))
            elif args.knowledge_semantic_report:
                print(format_semantic_report(service.semantic_report()))
            elif args.knowledge_policy_report:
                print(format_policy_report(service.policy_report()))
            else:
                print(format_coverage_report(service.coverage_report()))
        except KnowledgeImportError as exc:
            print(f"知识导入错误：{exc}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print(
                "知识导入已暂停；已完成文件已保存，可使用 "
                "--resume-knowledge-import <BATCH_ID> 继续。",
                file=sys.stderr,
            )
            return 130
        return 0

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
                    include_internal=args.include_internal,
                )
                print(_console_safe_text(format_search_results(results)))
        except KnowledgeError as exc:
            print(f"知识库错误: {exc}", file=sys.stderr)
            return 1
        return 0

    load_dotenv()
    application = QApplication([sys.argv[0]])
    font_scaler = _configure_application(application, settings.app_name)

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

    runtime = build_chat_runtime(
        settings,
        _build_conversation_assistant_from_environment(),
    )

    try:
        exit_code = application.exec()
    finally:
        runtime.controller.shutdown()
    del runtime
    del font_scaler
    return exit_code


def main() -> int:
    return run()
