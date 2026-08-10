from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from lexiaodu.advisor_assistant import OpenAIConversationAssistant
from lexiaodu.chat_context import ContextPackage
from lexiaodu.chat_repository import Message


class FakeCompletions:
    def __init__(self) -> None:
        self.options = None

    def create(self, **options):
        self.options = options
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="我理解您担心孩子跟不上，我们先确认目前阅读习惯。"
                    )
                )
            ]
        )


class FakeFiles:
    def __init__(self) -> None:
        self.uploaded = b""
        self.deleted: list[str] = []

    def create(self, *, file, purpose: str):
        assert purpose == "user_data"
        self.uploaded = file.read()
        return SimpleNamespace(id="file-1")

    def retrieve(self, file_id: str):
        assert file_id == "file-1"
        return SimpleNamespace(status="active")

    def delete(self, file_id: str) -> None:
        self.deleted.append(file_id)


class FakeResponses:
    def __init__(self) -> None:
        self.options = None

    def create(self, **options):
        self.options = options
        return SimpleNamespace(output_text="这份原文档建议先确认孩子当前阅读水平。")


class RoutingCompletions:
    def __init__(self) -> None:
        self.options = None

    def create(self, **options):
        self.options = options
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"files":["课程说明.pdf"]}'
                    )
                )
            ]
        )


def test_doubao_assistant_uses_conversation_context_as_primary_chat() -> None:
    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    assistant = OpenAIConversationAssistant(client, "doubao-test")
    message = Message(
        id="message-1",
        conversation_id="conversation-1",
        role="user",
        kind="text",
        body="家长担心孩子基础弱，跟不上课程。",
        request_id="request-1",
        in_reply_to_request_id=None,
        processing_status="processing",
        created_at=datetime.now(UTC),
    )
    context = ContextPackage((message,), 1)

    answer = assistant.respond(context, "request-1")

    assert "先确认" in answer
    assert completions.options["model"] == "doubao-test"
    assert "家长担心孩子基础弱" in completions.options["messages"][1]["content"]
    system = completions.options["messages"][0]["content"]
    assert "顾问" in system
    assert "公司事实" in system
    assert "不要编造" in system
    assert "业务系统" in system
    assert "退款" in system
    assert "文件名" in system


def test_doubao_automatically_selects_and_sends_original_pdf(tmp_path) -> None:
    document_dir = tmp_path / "company_documents"
    document_dir.mkdir()
    pdf = document_dir / "课程说明.pdf"
    raw = b"%PDF-1.4 original bytes"
    pdf.write_bytes(raw)
    files = FakeFiles()
    responses = FakeResponses()
    routing = RoutingCompletions()
    client = SimpleNamespace(
        files=files,
        responses=responses,
        chat=SimpleNamespace(completions=routing),
    )
    assistant = OpenAIConversationAssistant(
        client,
        "doubao-test",
        document_dir=document_dir,
    )
    context = ContextPackage((), 1)

    answer = assistant.respond(context, "request-1")

    assert "原文档" in answer
    assert files.uploaded == raw
    assert files.deleted == ["file-1"]
    content = responses.options["input"][0]["content"]
    assert content[0] == {"type": "input_file", "file_id": "file-1"}
    assert "课程说明.pdf" in routing.options["messages"][1]["content"]
