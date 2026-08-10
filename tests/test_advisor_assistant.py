from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from lexiaodu.advisor_assistant import OpenAIConversationAssistant
from lexiaodu.context import ContextPackage
from lexiaodu.conversations import Message


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
    context = ContextPackage((), None, (message,), (), (), 1)

    answer = assistant.respond(context, "request-1")

    assert "先确认" in answer
    assert completions.options["model"] == "doubao-test"
    assert "家长担心孩子基础弱" in completions.options["messages"][1]["content"]
    system = completions.options["messages"][0]["content"]
    assert "顾问" in system
    assert "公司事实" in system
    assert "不要编造" in system
