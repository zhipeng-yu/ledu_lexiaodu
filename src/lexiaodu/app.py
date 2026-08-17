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
from PySide6.QtWidgets import QApplication, QMessageBox
from volcengine.viking_knowledgebase import VikingKnowledgeBaseService

from lexiaodu.advisor_assistant import OpenAIConversationAssistant
from lexiaodu.chat_context import ContextBuilder, ContextPackage
from lexiaodu.chat_controller import ChatController, ConversationAssistant
from lexiaodu.chat_repository import ConversationRepository
from lexiaodu.chat_window import ChatMainWindow
from lexiaodu.config import AppSettings, SettingsError, load_settings
from lexiaodu.font_scaling import ApplicationFontScaler
from lexiaodu.local_crypto import DataCipher
from lexiaodu.office_documents import ArkKnowledgeDocumentReader
from lexiaodu.runtime import (
    configure_diagnostics,
    record_error,
    resource_path,
    user_data_dir,
)
from lexiaodu.screenshot_store import ScreenshotStore


@dataclass(slots=True)
class ChatRuntime:
    window: ChatMainWindow
    controller: ChatController
    repository: ConversationRepository
    context_builder: ContextBuilder
    assistant_executor: ThreadPoolExecutor


class OfflineDemoAssistant:
    def respond(self, context: ContextPackage, request_id: str) -> str:
        del context, request_id
        return (
            "这是离线演示回复，不会查询或编造公司事实。"
            "请仅用它检查会话流程，并在正式答复前依据经审核资料人工核实。"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="乐小读")
    parser.add_argument(
        "--config",
        type=Path,
        default=resource_path("config", "app.toml"),
        help="TOML 配置文件路径",
    )
    return parser


def _configure_application(
    application: QApplication,
    app_name: str,
) -> ApplicationFontScaler:
    application.setApplicationName(app_name)
    application.setQuitOnLastWindowClosed(False)
    return ApplicationFontScaler(application)


def _generator_provider() -> str:
    provider = os.environ.get("LEXIAODU_GENERATOR", "doubao").strip().casefold()
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


def _build_knowledge_reader_from_environment() -> ArkKnowledgeDocumentReader | None:
    required = {
        name: os.environ.get(name, "").strip()
        for name in (
            "VOLC_ACCESSKEY",
            "VOLC_SECRETKEY",
            "ARK_KB_COLLECTION",
        )
    }
    if not any(required.values()):
        return None
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError(
            "知识库原文档配置不完整，缺少 " + "、".join(missing)
        )
    access_key = required["VOLC_ACCESSKEY"]
    secret_key = required["VOLC_SECRETKEY"]
    collection_name = required["ARK_KB_COLLECTION"]
    region = os.environ.get("VOLC_REGION", "cn-beijing").strip()
    project = os.environ.get("ARK_KB_PROJECT", "default").strip()
    knowledge_service = VikingKnowledgeBaseService(
        host=os.environ.get(
            "ARK_KB_HOST",
            "api-knowledgebase.mlp.cn-beijing.volces.com",
        ).strip(),
        region=region,
        ak=access_key,
        sk=secret_key,
        scheme="https",
        connection_timeout=30,
        socket_timeout=30,
    )
    collection = knowledge_service.get_collection(
        collection_name,
        project=project,
    )
    return ArkKnowledgeDocumentReader(
        knowledge_service,
        collection,
    )


def _build_conversation_assistant_from_environment() -> ConversationAssistant:
    if _generator_provider() == "simulated":
        return OfflineDemoAssistant()
    client, model = _build_doubao_client()
    return OpenAIConversationAssistant(
        client,
        model,
        knowledge_reader=_build_knowledge_reader_from_environment(),
    )


def _load_runtime_environment() -> None:
    if getattr(sys, "frozen", False):
        load_dotenv(
            resource_path("runtime.env"),
            override=False,
            interpolate=False,
        )
    else:
        load_dotenv()


def _show_startup_error(error: BaseException) -> None:
    detail = record_error("启动", error)
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("乐小读启动失败")
    if isinstance(error, (SettingsError, ValueError)):
        box.setText("乐小读缺少必要配置，无法启动。请联系管理员重新安装。")
    else:
        box.setText("乐小读无法启动。请联系管理员，并复制诊断信息。")
    copy_button = box.addButton(
        "复制诊断信息",
        QMessageBox.ButtonRole.ActionRole,
    )
    box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    if box.clickedButton() is copy_button:
        QApplication.clipboard().setText(detail)


def build_chat_runtime(
    settings: AppSettings,
    assistant: ConversationAssistant,
) -> ChatRuntime:
    cipher = DataCipher.open(settings.chat.database_path.with_suffix(".key"))
    repository = ConversationRepository(settings.chat.database_path, cipher)
    screenshot_store = ScreenshotStore(
        settings.chat.database_path.parent / "chat-images", repository, cipher
    )
    context_builder = ContextBuilder(
        repository,
        screenshot_store,
        character_budget=settings.chat.context_character_budget,
    )
    window = ChatMainWindow()
    assistant_executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="lexiaodu-assistant",
    )
    try:
        controller = ChatController(
            window,
            repository,
            context_builder,
            screenshot_store,
            assistant,
            assistant_executor,
        )
    except BaseException:
        assistant_executor.shutdown(wait=True, cancel_futures=True)
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
        context_builder,
        assistant_executor,
    )


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _load_runtime_environment()
    configure_diagnostics(user_data_dir() / "logs")
    application = QApplication([sys.argv[0]])
    try:
        settings = load_settings(args.config)
        font_scaler = _configure_application(application, settings.app_name)
        assistant = _build_conversation_assistant_from_environment()
        runtime = build_chat_runtime(settings, assistant)
    except Exception as exc:
        _show_startup_error(exc)
        return 2

    try:
        exit_code = application.exec()
    finally:
        runtime.controller.shutdown()
    del runtime
    del font_scaler
    return exit_code


def main() -> int:
    return run()
