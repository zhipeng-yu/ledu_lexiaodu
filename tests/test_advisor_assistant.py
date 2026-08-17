from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from lexiaodu.advisor_assistant import AdvisorAssistantError, OpenAIConversationAssistant
from lexiaodu.chat_context import ContextImage, ContextPackage
from lexiaodu.chat_repository import Message
from lexiaodu.office_documents import KnowledgeDocument, KnowledgeDocumentError


class FakeCompletions:
    def __init__(self, content: str | None = None) -> None:
        self.options = None
        self.content = content or json.dumps(
            {
                "mode": "clarify",
                "consultant_message": "目前还缺少会影响建议判断的具体情况。",
                "questions": ["请先确认家长具体担心哪一方面？"],
                "parent_message": "",
            },
            ensure_ascii=False,
        )

    def create(self, **options):
        self.options = options
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=self.content
                    )
                )
            ]
        )


class FakeResponses:
    def __init__(self, output_text: str | None = None) -> None:
        self.options = None
        self.output_text = output_text or json.dumps(
            {
                "mode": "advice",
                "consultant_message": "建议先确认孩子当前水平，再结合资料说明安排。",
                "questions": [],
                "parent_message": "您好，我们会结合孩子当前情况说明合适的安排。",
            },
            ensure_ascii=False,
        )

    def create(self, **options):
        self.options = options
        return SimpleNamespace(output_text=self.output_text)


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


class RoutingThenResponseCompletions:
    def __init__(self, document_ids: tuple[str, ...], response_content: str) -> None:
        self.document_ids = document_ids
        self.response_content = response_content
        self.options = []

    def create(self, **options):
        self.options.append(options)
        content = (
            json.dumps(
                {"document_ids": self.document_ids},
                ensure_ascii=False,
            )
            if len(self.options) == 1
            else self.response_content
        )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content)
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


class RetrievalForbiddenKnowledgeReader(FakeKnowledgeReader):
    def retrieve(self, query, documents):
        raise AssertionError("文档路由返回空数组时不应调用知识检索")


class FailingKnowledgeReader(FakeKnowledgeReader):
    def retrieve(self, query, documents):
        raise KnowledgeDocumentError(
            f"方舟未能从知识库原文档检索到内容：《{documents[0].name}》"
        )


def _message(body: str, *, role: str = "user", id: str = "message") -> Message:
    return Message(
        id=id,
        conversation_id="conversation",
        role=role,
        kind="text",
        body=body,
        request_id=id if role == "user" else None,
        in_reply_to_request_id=None,
        processing_status="processing",
        created_at=datetime.now(UTC),
    )


def _chat_system_prompt() -> str:
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

    assert "目前还缺少" in answer
    assert "请先确认" in answer
    assert completions.options["model"] == "doubao-test"
    assert "家长担心孩子基础弱" in completions.options["messages"][1]["content"]
    return completions.options["messages"][0]["content"]


def test_doubao_chat_prompt_addresses_consultant_not_parent() -> None:
    system = _chat_system_prompt()

    assert "正在使用应用并与您对话的人是公司顾问" in system
    assert "家长是顾问需要沟通和服务的对象" in system
    assert "不要把顾问当作或称作家长" in system


def test_doubao_prompt_keeps_consultant_out_of_teaching_role_on_both_paths() -> None:
    message = Message(
        id="message-role-boundary",
        conversation_id="conversation-role-boundary",
        role="user",
        kind="text",
        body="线上上课，孩子自控力差，容易走神、摸手机。",
        request_id="request-role-boundary",
        in_reply_to_request_id=None,
        processing_status="processing",
        created_at=datetime.now(UTC),
    )
    context = ContextPackage((message,), 1)
    chat_completions = FakeCompletions()
    OpenAIConversationAssistant(
        SimpleNamespace(chat=SimpleNamespace(completions=chat_completions)),
        "doubao-test",
    ).respond(context, "request-role-boundary")

    document = KnowledgeDocument("doc-docx", "线上课程说明.docx")
    knowledge_responses = FakeResponses()
    OpenAIConversationAssistant(
        SimpleNamespace(
            responses=knowledge_responses,
            chat=SimpleNamespace(
                completions=RoutingCompletions(("doc-docx",))
            ),
        ),
        "doubao-test",
        knowledge_reader=FakeKnowledgeReader((document,)),
    ).respond(context, "request-role-boundary")

    chat_instructions = chat_completions.options["messages"][0]["content"]
    knowledge_instructions = knowledge_responses.options["instructions"]
    assert knowledge_instructions == chat_instructions
    assert "顾问老师" in chat_instructions
    assert "不是孩子的授课老师" in chat_instructions
    assert "课堂盯课" in chat_instructions
    assert "提醒孩子" in chat_instructions
    assert "观察课堂表现" in chat_instructions
    assert "授课" in chat_instructions
    assert "讲题" in chat_instructions
    assert "批改作业" in chat_instructions
    assert "管理纪律" in chat_instructions
    assert "执行教学干预" in chat_instructions
    assert "家长话术必须始终站在顾问身份表达" in chat_instructions
    assert "实际责任人" in chat_instructions
    assert "有公司知识或实际流程依据" in chat_instructions
    assert "没有依据时只能提示顾问核实" in chat_instructions


def test_doubao_chat_prompt_asks_consultant_only_for_critical_missing_details() -> None:
    system = _chat_system_prompt()

    assert "信息不足" in system
    assert "向顾问说明还缺什么" in system
    assert "一至两个最关键的问题" in system
    assert "不要假装直接询问家长" in system


def test_screenshot_prompt_forbids_inventing_illegible_content() -> None:
    system = _chat_system_prompt()

    assert "截图文字看不清时，不得还原或编造内容，只追问一个必要问题" in system


def test_doubao_chat_prompt_requires_advice_then_copy_ready_parent_text() -> None:
    system = _chat_system_prompt()

    assert "信息充分" in system
    assert "给顾问的建议" in system
    assert "可直接发给家长" in system
    assert "一段可独立完整复制的纯文本话术" in system
    assert "内部分析、来源列表或操作说明" in system


def test_doubao_chat_prompt_bounds_company_facts_and_case_learning() -> None:
    system = _chat_system_prompt()

    assert "顾问" in system
    assert "公司事实" in system
    assert "不要编造" in system
    assert "聊天案例只能影响表达方式" in system
    assert "不得作为公司事实来源" in system
    assert "业务系统" in system
    assert "退款" in system
    assert "文件名" in system


def test_doubao_chat_uses_strict_schema_and_renders_clarification() -> None:
    completions = FakeCompletions()
    assistant = OpenAIConversationAssistant(
        SimpleNamespace(chat=SimpleNamespace(completions=completions)),
        "doubao-test",
    )

    answer = assistant.respond(ContextPackage((), 1), "request-1")

    assert answer == (
        "目前还缺少会影响建议判断的具体情况。\n\n"
        "1. 请先确认家长具体担心哪一方面？"
    )
    response_format = completions.options["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    schema = response_format["json_schema"]["schema"]
    assert set(schema["required"]) == {
        "mode",
        "consultant_message",
        "questions",
        "parent_message",
    }
    assert completions.options["messages"][1]["content"] == ""


def test_doubao_can_chat_normally_without_advisor_template() -> None:
    completions = FakeCompletions(
        json.dumps(
            {
                "mode": "chat",
                "consultant_message": "当然可以，我们可以像普通聊天一样交流。",
                "questions": [],
                "parent_message": "",
            },
            ensure_ascii=False,
        )
    )
    assistant = OpenAIConversationAssistant(
        SimpleNamespace(chat=SimpleNamespace(completions=completions)),
        "doubao-test",
    )

    answer = assistant.respond(ContextPackage((), 1), "request-chat")

    assert answer == "当然可以，我们可以像普通聊天一样交流。"
    system = completions.options["messages"][0]["content"]
    assert "通用 AI 助手" in system
    assert "不要把所有消息都理解成家长沟通任务" in system
    schema = completions.options["response_format"]["json_schema"]["schema"]
    assert "chat" in schema["properties"]["mode"]["enum"]


def test_doubao_chat_sends_screenshot_as_high_detail_image() -> None:
    completions = FakeCompletions()
    assistant = OpenAIConversationAssistant(
        SimpleNamespace(chat=SimpleNamespace(completions=completions)),
        "doubao-test",
    )
    context = ContextPackage(
        messages=(),
        context_version=1,
        image=ContextImage("image/png", b"LONG-SCREENSHOT"),
    )

    assistant.respond(context, "request-1")

    content = completions.options["messages"][1]["content"]
    assert len(content) == 2
    assert content[0] == {"type": "text", "text": ""}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["detail"] == "high"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_doubao_reports_actionable_error_when_screenshot_analysis_fails() -> None:
    class FailingCompletions:
        def create(self, **options):
            raise RuntimeError("unsupported image")

    assistant = OpenAIConversationAssistant(
        SimpleNamespace(chat=SimpleNamespace(completions=FailingCompletions())),
        "doubao-test",
    )
    context = ContextPackage(
        messages=(),
        context_version=1,
        image=ContextImage("image/png", b"LONG-SCREENSHOT"),
    )

    with pytest.raises(AdvisorAssistantError, match="ARK_MODEL 支持图片理解"):
        assistant.respond(context, "request-1")


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


def test_doubao_knowledge_routing_and_response_send_the_screenshot() -> None:
    document = KnowledgeDocument("doc-pdf", "课程说明.pdf")
    reader = FakeKnowledgeReader((document,))
    responses = FakeResponses()
    routing = RoutingCompletions(("doc-pdf",))
    assistant = OpenAIConversationAssistant(
        SimpleNamespace(
            responses=responses,
            chat=SimpleNamespace(completions=routing),
        ),
        "doubao-test",
        knowledge_reader=reader,
    )
    context = ContextPackage(
        messages=(),
        context_version=1,
        image=ContextImage("image/png", b"LONG-SCREENSHOT"),
    )

    assistant.respond(context, "request-1")

    routing_content = routing.options["messages"][1]["content"]
    assert routing_content == [
        {
            "type": "text",
            "text": "可选原文档（文档 ID\t文件名）：\ndoc-pdf\t课程说明.pdf",
        },
        {
            "type": "image_url",
            "image_url": {
                "url": "data:image/png;base64,TE9ORy1TQ1JFRU5TSE9U",
                "detail": "high",
            },
        },
    ]
    content = responses.options["input"][0]["content"]
    assert len(content) == 2
    assert content[0]["type"] == "input_text"
    assert "方舟知识库" in content[0]["text"]
    assert content[1] == {
        "type": "input_image",
        "image_url": "data:image/png;base64,TE9ORy1TQ1JFRU5TSE9U",
        "detail": "high",
    }


def test_doubao_gives_direct_advice_when_document_route_is_empty() -> None:
    document = KnowledgeDocument("doc-docx", "课程政策.docx")
    reader = RetrievalForbiddenKnowledgeReader((document,))
    response_content = json.dumps(
        {
            "mode": "advice",
            "consultant_message": "建议先回应孩子的受挫感，再把难题拆成较小步骤。",
            "questions": [],
            "parent_message": "能理解孩子遇到难题会有挫败感，可以先从会做的部分开始，再逐步处理卡住的题目。",
        },
        ensure_ascii=False,
    )
    completions = RoutingThenResponseCompletions((), response_content)
    assistant = OpenAIConversationAssistant(
        SimpleNamespace(chat=SimpleNamespace(completions=completions)),
        "doubao-test",
        knowledge_reader=reader,
    )
    context = ContextPackage(
        (
            Message(
                id="message-homework",
                conversation_id="conversation-homework",
                role="user",
                kind="text",
                body="课后题太难，孩子做不来。",
                request_id="request-homework",
                in_reply_to_request_id=None,
                processing_status="processing",
                created_at=datetime.now(UTC),
            ),
        ),
        1,
    )

    answer = assistant.respond(context, "request-homework")

    assert reader.list_calls == 1
    assert len(completions.options) == 2
    assert answer == (
        "给顾问的建议\n建议先回应孩子的受挫感，再把难题拆成较小步骤。\n\n"
        "可直接发给家长\n"
        "能理解孩子遇到难题会有挫败感，可以先从会做的部分开始，再逐步处理卡住的题目。"
    )
    assert document.name not in answer


def test_doubao_uses_knowledge_document_for_course_policy_facts() -> None:
    document = KnowledgeDocument("doc-policy", "课程政策.docx")
    reader = FakeKnowledgeReader((document,))
    responses = FakeResponses(
        json.dumps(
            {
                "mode": "advice",
                "consultant_message": "可以依据《课程政策.docx》说明适用的课程政策。",
                "questions": [],
                "parent_message": "您好，我根据孩子的情况为您说明适用的课程政策。",
            },
            ensure_ascii=False,
        )
    )
    assistant = OpenAIConversationAssistant(
        SimpleNamespace(
            responses=responses,
            chat=SimpleNamespace(
                completions=RoutingCompletions(("doc-policy",))
            ),
        ),
        "doubao-test",
        knowledge_reader=reader,
    )
    context = ContextPackage(
        (
            Message(
                id="message-policy",
                conversation_id="conversation-policy",
                role="user",
                kind="text",
                body="家长想了解线上课程的请假和补课政策。",
                request_id="request-policy",
                in_reply_to_request_id=None,
                processing_status="processing",
                created_at=datetime.now(UTC),
            ),
        ),
        1,
    )

    answer = assistant.respond(context, "request-policy")

    assert reader.documents == (document,)
    assert "家长想了解线上课程的请假和补课政策" in reader.query
    evidence_prompt = responses.options["input"][0]["content"][0]["text"]
    assert "《课程政策.docx》\n方舟解析的相关内容" in evidence_prompt
    consultant_text, parent_text = answer.split("可直接发给家长", 1)
    assert "《课程政策.docx》" in consultant_text
    assert "课程政策.docx" not in parent_text


def test_doubao_routes_and_retrieves_for_the_latest_question() -> None:
    document = KnowledgeDocument("doc-outline", "二年级数学课程大纲.docx")
    reader = FakeKnowledgeReader((document,))
    responses = FakeResponses()
    routing = RoutingCompletions(("doc-outline",))
    assistant = OpenAIConversationAssistant(
        SimpleNamespace(
            responses=responses,
            chat=SimpleNamespace(completions=routing),
        ),
        "doubao-test",
        knowledge_reader=reader,
    )
    context = ContextPackage(
        (
            _message("家长问我们和学而思的区别。", id="old-user"),
            _message(
                "这里是上一题的课程对比回答。",
                role="assistant",
                id="old-answer",
            ),
            _message("数学二年级课程大纲", id="latest-user"),
        ),
        1,
    )

    assistant.respond(context, "latest-request")

    assert reader.query == "数学二年级课程大纲"
    routing_system = routing.options["messages"][0]["content"]
    assert "只根据最新一条用户消息" in routing_system
    routing_prompt = routing.options["messages"][1]["content"]
    assert "当前用户消息（本轮唯一回答目标）：\n数学二年级课程大纲" in routing_prompt


def test_no_link_requirement_persists_across_later_turns() -> None:
    document = KnowledgeDocument("doc-outline", "二年级数学课程大纲.docx")
    reader = FakeKnowledgeReader((document,))
    responses = FakeResponses(
        json.dumps(
            {
                "mode": "advice",
                "consultant_message": "课程大纲见 https://internal.example/outline 。",
                "questions": [],
                "parent_message": "文字版大纲可参考[课程页](https://example.com/course)。",
            },
            ensure_ascii=False,
        )
    )
    assistant = OpenAIConversationAssistant(
        SimpleNamespace(
            responses=responses,
            chat=SimpleNamespace(
                completions=RoutingCompletions(("doc-outline",))
            ),
        ),
        "doubao-test",
        knowledge_reader=reader,
    )
    context = ContextPackage(
        (
            _message("后面都不要发链接，只发文字。", id="preference"),
            _message("数学二年级课程大纲", id="latest"),
        ),
        1,
    )

    answer = assistant.respond(context, "latest-request")

    assert "http" not in answer
    assert "](" not in answer
    assert "课程页" in answer


def test_doubao_knowledge_response_uses_same_consultant_answer_contract() -> None:
    document = KnowledgeDocument("doc-docx", "课程介绍.docx")
    reader = FakeKnowledgeReader((document,))
    responses = FakeResponses(
        json.dumps(
            {
                "mode": "advice",
                "consultant_message": "可以依据《课程介绍.docx》说明。",
                "questions": [],
                "parent_message": "您好，可以结合孩子情况了解课程安排。",
            },
            ensure_ascii=False,
        )
    )
    assistant = OpenAIConversationAssistant(
        SimpleNamespace(
            responses=responses,
            chat=SimpleNamespace(
                completions=RoutingCompletions(("doc-docx",))
            ),
        ),
        "doubao-test",
        knowledge_reader=reader,
    )

    assistant.respond(ContextPackage((), 1), "request-1")

    instructions = responses.options["instructions"]
    prompt = responses.options["input"][0]["content"][0]["text"]
    assert "正在使用应用并与您对话的人是公司顾问" in instructions
    assert "一至两个最关键的问题" in instructions
    assert "给顾问的建议" in instructions
    assert "可直接发给家长" in instructions
    assert "来源文件名只能出现在“给顾问的建议”" in instructions
    assert "不要编造" in instructions
    assert "正在使用应用并与您对话的人是公司顾问" not in prompt
    assert "方舟知识库" in prompt
    response_format = responses.options["text"]["format"]
    assert response_format["type"] == "json_schema"
    assert response_format["strict"] is True
    schema = response_format["schema"]
    assert schema["properties"]["mode"]["enum"] == ["chat", "clarify", "advice"]
    assert schema["properties"]["questions"]["maxItems"] == 2
    assert schema["properties"]["consultant_message"]["minLength"] == 1
    assert schema["properties"]["parent_message"]["minLength"] == 0


def test_doubao_realtime_status_forces_advice_with_business_system_verification() -> None:
    completions = FakeCompletions(
        json.dumps(
            {
                "mode": "advice",
                "consultant_message": "需要先核实名额和订单状态。",
                "questions": [],
                "parent_message": "您好，我正在为您核实名额和订单状态，确认后及时同步。",
            },
            ensure_ascii=False,
        )
    )
    assistant = OpenAIConversationAssistant(
        SimpleNamespace(chat=SimpleNamespace(completions=completions)),
        "doubao-test",
    )
    context = ContextPackage(
        (
            Message(
                id="message-realtime",
                conversation_id="conversation-realtime",
                role="user",
                kind="text",
                body="家长问今天是否还有名额，订单付款后 App 还没显示。",
                request_id="request-realtime",
                in_reply_to_request_id=None,
                processing_status="processing",
                created_at=datetime.now(UTC),
            ),
        ),
        1,
    )

    answer = assistant.respond(context, "request-realtime")

    response_format = completions.options["response_format"]
    schema = response_format["json_schema"]["schema"]
    assert schema["properties"]["mode"]["enum"] == ["advice"]
    assert schema["properties"]["questions"]["maxItems"] == 0
    assert schema["properties"]["consultant_message"]["minLength"] == 1
    assert schema["properties"]["parent_message"]["minLength"] == 1
    assert answer.startswith("给顾问的建议\n")
    assert "业务系统" in answer
    assert "\n\n可直接发给家长\n" in answer


def test_doubao_knowledge_renders_advice_and_copy_ready_parent_text() -> None:
    document = KnowledgeDocument("doc-docx", "课程介绍.docx")
    reader = FakeKnowledgeReader((document,))
    responses = FakeResponses(
        json.dumps(
            {
                "mode": "advice",
                "consultant_message": "可以依据资料说明课程安排。",
                "questions": [],
                "parent_message": "您好，课程会结合孩子当前情况安排。",
            },
            ensure_ascii=False,
        )
    )
    assistant = OpenAIConversationAssistant(
        SimpleNamespace(
            responses=responses,
            chat=SimpleNamespace(
                completions=RoutingCompletions(("doc-docx",))
            ),
        ),
        "doubao-test",
        knowledge_reader=reader,
    )

    answer = assistant.respond(ContextPackage((), 1), "request-1")

    assert answer == (
        "给顾问的建议\n可以依据资料说明课程安排。\n\n"
        "依据原文件：《课程介绍.docx》\n\n"
        "可直接发给家长\n您好，课程会结合孩子当前情况安排。"
    )


def test_missing_source_names_are_inserted_before_copy_ready_parent_text() -> None:
    document = KnowledgeDocument("doc-docx", "课程介绍.docx")
    reader = FakeKnowledgeReader((document,))
    responses = FakeResponses(
        json.dumps(
            {
                "mode": "advice",
                "consultant_message": "可以依据公司资料说明课程安排。",
                "questions": [],
                "parent_message": "您好，课程会结合孩子当前情况安排。",
            },
            ensure_ascii=False,
        )
    )
    assistant = OpenAIConversationAssistant(
        SimpleNamespace(
            responses=responses,
            chat=SimpleNamespace(
                completions=RoutingCompletions(("doc-docx",))
            ),
        ),
        "doubao-test",
        knowledge_reader=reader,
    )

    answer = assistant.respond(ContextPackage((), 1), "request-1")

    consultant_text, parent_text = answer.split("可直接发给家长", 1)
    assert "依据原文件：《课程介绍.docx》" in consultant_text
    assert "课程介绍.docx" not in parent_text


def test_source_names_in_parent_text_are_moved_to_consultant_advice() -> None:
    document = KnowledgeDocument("doc-docx", "课程介绍.docx")
    reader = FakeKnowledgeReader((document,))
    responses = FakeResponses(
        json.dumps(
            {
                "mode": "advice",
                "consultant_message": "可以说明课程安排。",
                "questions": [],
                "parent_message": "您好，根据《课程介绍.docx》，课程会结合孩子情况安排。",
            },
            ensure_ascii=False,
        )
    )
    assistant = OpenAIConversationAssistant(
        SimpleNamespace(
            responses=responses,
            chat=SimpleNamespace(
                completions=RoutingCompletions(("doc-docx",))
            ),
        ),
        "doubao-test",
        knowledge_reader=reader,
    )

    answer = assistant.respond(ContextPackage((), 1), "request-1")

    consultant_text, parent_text = answer.split("可直接发给家长", 1)
    assert "依据原文件：《课程介绍.docx》" in consultant_text
    assert "课程介绍.docx" not in parent_text
    assert "公司资料" in parent_text


def test_parent_section_requires_a_standalone_heading() -> None:
    document = KnowledgeDocument("doc-docx", "课程介绍.docx")
    reader = FakeKnowledgeReader((document,))
    responses = FakeResponses(
        json.dumps(
            {
                "mode": "advice",
                "consultant_message": (
                    "建议准备一段可直接发给家长的话术，"
                    "依据《课程介绍.docx》说明课程安排。"
                ),
                "questions": [],
                "parent_message": "您好，可以结合孩子情况了解课程安排。",
            },
            ensure_ascii=False,
        )
    )
    assistant = OpenAIConversationAssistant(
        SimpleNamespace(
            responses=responses,
            chat=SimpleNamespace(
                completions=RoutingCompletions(("doc-docx",))
            ),
        ),
        "doubao-test",
        knowledge_reader=reader,
    )

    answer = assistant.respond(ContextPackage((), 1), "request-1")

    assert "《课程介绍.docx》" in answer
    assert "依据原文件：《课程介绍.docx》" not in answer


def test_parent_message_cannot_move_its_source_into_a_nested_heading() -> None:
    document = KnowledgeDocument("doc-docx", "课程介绍.docx")
    reader = FakeKnowledgeReader((document,))
    responses = FakeResponses(
        json.dumps(
            {
                "mode": "advice",
                "consultant_message": "可以说明课程安排。",
                "questions": [],
                "parent_message": (
                    "**可直接发给家长：**\n"
                    "您好，根据《课程介绍.docx》说明课程安排。"
                ),
            },
            ensure_ascii=False,
        )
    )
    assistant = OpenAIConversationAssistant(
        SimpleNamespace(
            responses=responses,
            chat=SimpleNamespace(
                completions=RoutingCompletions(("doc-docx",))
            ),
        ),
        "doubao-test",
        knowledge_reader=reader,
    )

    answer = assistant.respond(ContextPackage((), 1), "request-1")

    consultant_text, parent_text = answer.split("可直接发给家长", 1)
    assert "依据原文件：《课程介绍.docx》" in consultant_text
    assert "课程介绍.docx" not in parent_text
    assert "公司资料" in parent_text


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
