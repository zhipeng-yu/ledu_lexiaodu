from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

from lexiaodu.advisor_assistant import OpenAIConversationAssistant
from lexiaodu.chat_context import ContextPackage
from lexiaodu.chat_repository import Message
from lexiaodu.office_documents import KnowledgeDocument, KnowledgeDocumentError


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


class FakeResponses:
    def __init__(self) -> None:
        self.options = None

    def create(self, **options):
        self.options = options
        return SimpleNamespace(output_text="建议先确认孩子当前阅读水平。")


class RoutingCompletions:
    def __init__(self, document_ids: tuple[str, ...]) -> None:
        self.options = None
        self.document_ids = document_ids

    def create(self, **options):
        self.options = options
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {"document_ids": self.document_ids},
                            ensure_ascii=False,
                        )
                    )
                )
            ]
        )


class FakeKnowledgeReader:
    def __init__(self, documents: tuple[KnowledgeDocument, ...]) -> None:
        self.available = documents
        self.list_calls = 0
        self.query = ""
        self.documents = ()

    def list_documents(self) -> tuple[KnowledgeDocument, ...]:
        self.list_calls += 1
        return self.available

    def retrieve(self, query, documents):
        self.query = query
        self.documents = documents
        return "\n\n".join(
            f"《{document.name}》\n方舟解析的相关内容" for document in documents
        )


class FailingKnowledgeReader(FakeKnowledgeReader):
    def retrieve(self, query, documents):
        raise KnowledgeDocumentError(
            f"方舟未能从知识库原文档检索到内容：《{documents[0].name}》"
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


def test_doubao_selects_cloud_pdf_and_office_without_local_files_api() -> None:
    documents = (
        KnowledgeDocument("doc-pdf", "课程说明.pdf"),
        KnowledgeDocument("doc-docx", "课程介绍.docx"),
    )
    reader = FakeKnowledgeReader(documents)
    responses = FakeResponses()
    routing = RoutingCompletions(("doc-pdf", "doc-docx"))
    client = SimpleNamespace(
        responses=responses,
        chat=SimpleNamespace(completions=routing),
    )
    assistant = OpenAIConversationAssistant(
        client,
        "doubao-test",
        knowledge_reader=reader,
    )
    context = ContextPackage((), 1)

    answer = assistant.respond(context, "request-1")

    assert reader.list_calls == 1
    assert reader.documents == documents
    routing_prompt = routing.options["messages"][1]["content"]
    assert "doc-pdf" in routing_prompt
    assert "课程说明.pdf" in routing_prompt
    assert "doc-docx" in routing_prompt
    assert "课程介绍.docx" in routing_prompt
    content = responses.options["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    assert "方舟知识库" in content[0]["text"]
    assert "《课程说明.pdf》" in content[0]["text"]
    assert "《课程介绍.docx》" in content[0]["text"]
    assert "timeout" not in responses.options
    assert "课程说明.pdf" in answer
    assert "课程介绍.docx" in answer


def test_doubao_allows_office_knowledge_response_to_exceed_default_timeout() -> None:
    documents = (
        KnowledgeDocument("doc-docx", "课程介绍.docx"),
        KnowledgeDocument("doc-xlsx", "课程大纲.xlsx"),
    )
    reader = FakeKnowledgeReader(documents)
    responses = FakeResponses()
    assistant = OpenAIConversationAssistant(
        SimpleNamespace(
            responses=responses,
            chat=SimpleNamespace(
                completions=RoutingCompletions(("doc-docx", "doc-xlsx"))
            ),
        ),
        "doubao-test",
        knowledge_reader=reader,
    )

    assistant.respond(ContextPackage((), 1), "request-1")

    assert responses.options["timeout"] == 120.0


def test_doubao_ignores_unknown_or_duplicate_cloud_document_ids() -> None:
    document = KnowledgeDocument("doc-pdf", "课程说明.pdf")
    reader = FakeKnowledgeReader((document,))
    responses = FakeResponses()
    routing = RoutingCompletions(("missing", "doc-pdf", "doc-pdf"))
    assistant = OpenAIConversationAssistant(
        SimpleNamespace(
            responses=responses,
            chat=SimpleNamespace(completions=routing),
        ),
        "doubao-test",
        knowledge_reader=reader,
    )

    assistant.respond(ContextPackage((), 1), "request-1")

    assert reader.documents == (document,)


def test_doubao_reports_selected_cloud_document_read_failure() -> None:
    document = KnowledgeDocument("doc-docx", "课程介绍.docx")
    reader = FailingKnowledgeReader((document,))
    assistant = OpenAIConversationAssistant(
        SimpleNamespace(
            chat=SimpleNamespace(
                completions=RoutingCompletions(("doc-docx",))
            )
        ),
        "doubao-test",
        knowledge_reader=reader,
    )

    answer = assistant.respond(ContextPackage((), 1), "request-1")

    assert "课程介绍.docx" in answer
    assert "未能" in answer
    assert "不能依据" in answer
