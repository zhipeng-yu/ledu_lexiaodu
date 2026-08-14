from __future__ import annotations

import pytest

from lexiaodu.chat_context import ContextBuilder
from lexiaodu.chat_repository import ConversationRepository
from lexiaodu.local_crypto import DataCipher
from lexiaodu.screenshot_store import ScreenshotStore


@pytest.fixture
def repository(tmp_path) -> ConversationRepository:
    return ConversationRepository(tmp_path / "context.sqlite3", DataCipher(b"x" * 32))


def test_builder_requires_screenshot_store(repository) -> None:
    with pytest.raises(TypeError, match="screenshot_store"):
        ContextBuilder(repository, character_budget=200)


def test_builder_labels_roles_and_never_crosses_conversations(repository, tmp_path) -> None:
    first = repository.create_conversation("first")
    second = repository.create_conversation("second")
    repository.append_user_message(first.id, "FIRST 顾问问题", request_id="first")
    repository.append_assistant_message(
        first.id,
        "FIRST 乐小读回答",
        in_reply_to_request_id="first",
    )
    repository.append_user_message(second.id, "SECOND-SENTINEL", request_id="second")

    package = ContextBuilder(
        repository,
        ScreenshotStore(tmp_path / "chat-images", repository, DataCipher(b"x" * 32)),
        character_budget=200,
    ).build(first.id)

    assert package.render_for_model() == (
        "顾问：FIRST 顾问问题\n乐小读：FIRST 乐小读回答"
    )
    assert "SECOND-SENTINEL" not in package.render_for_model()


def test_builder_drops_oldest_complete_messages_when_budget_is_full(repository, tmp_path) -> None:
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

    package = ContextBuilder(
        repository,
        ScreenshotStore(tmp_path / "chat-images", repository, DataCipher(b"x" * 32)),
        character_budget=55,
    ).build(conversation.id)
    rendered = package.render_for_model()

    assert "最新问题" in rendered
    assert "最早消息" not in rendered
    assert len(rendered) <= 55


def test_builder_uses_request_image_then_latest_context_image(tmp_path) -> None:
    cipher = DataCipher(b"i" * 32)
    repository = ConversationRepository(tmp_path / "chat.sqlite3", cipher)
    store = ScreenshotStore(tmp_path / "chat-images", repository, cipher)
    conversation = repository.create_conversation("images")
    first = repository.append_user_message(
        conversation.id, "第一张", request_id="first", kind="image"
    )
    store.save(conversation.id, first.id, b"FIRST", "image/png", 10, 100)
    text = repository.append_user_message(
        conversation.id, "继续分析", request_id="text"
    )
    builder = ContextBuilder(repository, store, character_budget=1000)

    assert builder.build(
        conversation.id, request_message_id=first.id
    ).image.data == b"FIRST"
    assert builder.build(
        conversation.id, request_message_id=text.id
    ).image.data == b"FIRST"

    second = repository.append_user_message(
        conversation.id, "第二张", request_id="second", kind="image"
    )
    store.save(conversation.id, second.id, b"SECOND", "image/png", 10, 200)
    latest_text = repository.append_user_message(
        conversation.id, "继续第二张", request_id="latest-text"
    )

    assert builder.build(
        conversation.id, request_message_id=latest_text.id
    ).image.data == b"SECOND"


def test_builder_does_not_select_another_conversations_or_dropped_image(tmp_path) -> None:
    cipher = DataCipher(b"j" * 32)
    repository = ConversationRepository(tmp_path / "chat.sqlite3", cipher)
    store = ScreenshotStore(tmp_path / "chat-images", repository, cipher)
    first = repository.create_conversation("first")
    second = repository.create_conversation("second")
    old_image = repository.append_user_message(
        first.id, "旧截图" + "甲" * 100, request_id="old", kind="image"
    )
    store.save(first.id, old_image.id, b"OLD", "image/png", 10, 10)
    latest_text = repository.append_user_message(
        first.id, "最新文字", request_id="latest"
    )
    foreign_image = repository.append_user_message(
        second.id, "外部截图", request_id="foreign", kind="image"
    )
    store.save(second.id, foreign_image.id, b"FOREIGN", "image/png", 10, 10)
    builder = ContextBuilder(repository, store, character_budget=20)

    package = builder.build(first.id, request_message_id=latest_text.id)

    assert package.image is None
    assert "外部截图" not in package.render_for_model()
