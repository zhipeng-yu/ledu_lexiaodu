from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from lexiaodu.advisor_assistant import OpenAIConversationAssistant
from lexiaodu.chat_context import ContextPackage
from lexiaodu.chat_repository import Message
from lexiaodu.office_documents import OfficeDocumentError


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
    def __init__(self, filename: str = "课程说明.pdf") -> None:
        self.options = None
        self.filename = filename

    def create(self, **options):
        self.options = options
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=f'{{"files":["{self.filename}"]}}'
                    )
                )
            ]
        )


class FakeOfficeReader:
    def __init__(self) -> None:
        self.query = ""
        self.documents = ()

    def retrieve(self, query, documents):
        self.query = query
        self.documents = documents
        return "《课程介绍.docx》\n适合需要巩固阅读基础的孩子。"


class FailingOfficeReader:
    def retrieve(self, query, documents):
        raise OfficeDocumentError("方舟未能解析 Office 原文档《课程介绍.docx》")


def test_doubao_assistant_uses_conversation_context_as_primary_chat(tmp_path) -> None:
    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    assistant = OpenAIConversationAssistant(
        client,
        "doubao-test",
        document_dir=tmp_path / "company_documents",
    )
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


def test_doubao_uses_selected_office_document_in_answer(tmp_path) -> None:
    document_dir = tmp_path / "company_documents"
    document_dir.mkdir()
    docx = document_dir / "课程介绍.docx"
    docx.write_bytes(b"original docx bytes")
    office_reader = FakeOfficeReader()
    responses = FakeResponses()
    routing = RoutingCompletions("课程介绍.docx")
    client = SimpleNamespace(
        responses=responses,
        chat=SimpleNamespace(completions=routing),
    )
    assistant = OpenAIConversationAssistant(
        client,
        "doubao-test",
        document_dir=document_dir,
        office_reader=office_reader,
    )
    context = ContextPackage((), 1)

    answer = assistant.respond(context, "request-1")

    assert "课程介绍.docx" in answer
    assert office_reader.documents == (docx,)
    content = responses.options["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    assert "方舟知识库" in content[0]["text"]
    assert "《课程介绍.docx》" in content[0]["text"]
    assert "适合需要巩固阅读基础" in content[0]["text"]


def test_doubao_reports_selected_office_read_failure(tmp_path) -> None:
    document_dir = tmp_path / "company_documents"
    document_dir.mkdir()
    (document_dir / "课程介绍.docx").write_bytes(b"broken")
    assistant = OpenAIConversationAssistant(
        SimpleNamespace(
            chat=SimpleNamespace(
                completions=RoutingCompletions("课程介绍.docx")
            )
        ),
        "doubao-test",
        document_dir=document_dir,
        office_reader=FailingOfficeReader(),
    )

    answer = assistant.respond(ContextPackage((), 1), "request-1")

    assert "课程介绍.docx" in answer
    assert "未能解析" in answer
    assert "不能依据" in answer
