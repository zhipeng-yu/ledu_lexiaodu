from __future__ import annotations

import pytest

from lexiaodu.chat_context import ContextBuilder
from lexiaodu.chat_repository import ConversationRepository
from lexiaodu.local_crypto import DataCipher


@pytest.fixture
def repository(tmp_path) -> ConversationRepository:
    return ConversationRepository(tmp_path / "context.sqlite3", DataCipher(b"x" * 32))


def test_builder_labels_roles_and_never_crosses_conversations(repository) -> None:
    first = repository.create_conversation("first")
    second = repository.create_conversation("second")
    repository.append_user_message(first.id, "FIRST 顾问问题", request_id="first")
    repository.append_assistant_message(
        first.id,
        "FIRST 乐小读回答",
        in_reply_to_request_id="first",
    )
    repository.append_user_message(second.id, "SECOND-SENTINEL", request_id="second")

    package = ContextBuilder(repository, character_budget=200).build(first.id)

    assert package.render_for_model() == (
        "顾问：FIRST 顾问问题\n乐小读：FIRST 乐小读回答"
    )
    assert "SECOND-SENTINEL" not in package.render_for_model()


def test_builder_drops_oldest_complete_messages_when_budget_is_full(repository) -> None:
    conversation = repository.create_conversation("budget")
    repository.append_user_message(
        conversation.id,
        "最早消息" + "甲" * 20,
        request_id="oldest",
    )
    repository.append_assistant_message(
        conversation.id,
        "中间回答" + "乙" * 20,
        in_reply_to_request_id="oldest",
    )
    repository.append_user_message(
        conversation.id,
        "最新问题" + "丙" * 20,
        request_id="latest",
    )

    package = ContextBuilder(repository, character_budget=55).build(conversation.id)
    rendered = package.render_for_model()

    assert "最新问题" in rendered
    assert "最早消息" not in rendered
    assert len(rendered) <= 55
