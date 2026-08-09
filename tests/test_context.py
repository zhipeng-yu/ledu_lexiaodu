from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Event, Thread

import pytest

from lexiaodu.context import ContextBuilder, SummaryCoordinator
from lexiaodu.conversations import ConversationRepository, Message
from lexiaodu.local_crypto import DataCipher


class AdvancingClock:
    def __init__(self) -> None:
        self._current = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        value = self._current
        self._current += timedelta(seconds=1)
        return value


@pytest.fixture
def repository(tmp_path) -> ConversationRepository:
    return ConversationRepository(
        tmp_path / "context.sqlite3",
        DataCipher(b"x" * 32),
        clock=AdvancingClock(),
    )


def _seed_messages(
    repository: ConversationRepository,
    conversation_id: str,
    prefix: str,
    count: int,
) -> tuple[Message, ...]:
    return tuple(
        repository.append_user_message(
            conversation_id,
            (
                f"{prefix} message {index} 英语 开口 confidence"
                if index in (14, 20)
                else f"{prefix} message {index} unrelated"
            ),
            request_id=f"{prefix}-request-{index}",
        )
        for index in range(count)
    )


def test_builder_assembles_budgeted_same_thread_context_in_priority_order(
    repository, tmp_path
) -> None:
    first = repository.create_conversation("first")
    second = repository.create_conversation("second")
    first_messages = _seed_messages(repository, first.id, "FIRST", 30)
    second_messages = _seed_messages(repository, second.id, "OTHER-FAMILY-SENTINEL", 30)
    first_fact = repository.save_confirmed_fact(first.id, "FIRST CONFIRMED FACT")
    repository.save_confirmed_fact(second.id, "OTHER-FAMILY-SENTINEL FACT")
    summary = repository.save_context_summary(
        first.id,
        "FIRST VALID SUMMARY",
        start_message_id=first_messages[0].id,
        end_message_id=first_messages[9].id,
        context_version=first.context_version,
    )
    repository.save_context_summary(
        second.id,
        "OTHER-FAMILY-SENTINEL SUMMARY",
        start_message_id=second_messages[0].id,
        end_message_id=second_messages[9].id,
        context_version=second.context_version,
    )
    attachment = repository.save_attachment(
        first.id, "a" * 32, tmp_path / "first.bin", b"first-key"
    )
    repository.save_corrected_text(first.id, attachment.id, "FIRST ATTACHMENT TEXT")
    other_attachment = repository.save_attachment(
        second.id, "b" * 32, tmp_path / "second.bin", b"second-key"
    )
    repository.save_corrected_text(
        second.id, other_attachment.id, "OTHER-FAMILY-SENTINEL ATTACHMENT"
    )

    package = ContextBuilder(
        repository,
        recent_limit=4,
        related_limit=2,
        character_budget=260,
    ).build(first.id, "现在主要担心英语开口 confidence")

    rendered = package.render_for_model()
    assert package.context_version == repository.get_conversation(first.id).context_version
    assert package.confirmed_facts == (first_fact,)
    assert package.summary == summary
    assert package.recent_messages == first_messages[-4:]
    assert tuple(message.body for message in package.related_messages) == (
        "FIRST message 14 英语 开口 confidence",
        "FIRST message 20 英语 开口 confidence",
    )
    assert tuple(item.corrected_text for item in package.attachment_texts) == (
        "FIRST ATTACHMENT TEXT",
    )
    assert all(item.conversation_id == first.id for item in package.all_items())
    assert len(rendered) <= 260
    assert "OTHER-FAMILY-SENTINEL" not in rendered
    assert rendered.index(first_fact.body) < rendered.index(summary.body)
    assert rendered.index(summary.body) < rendered.index(first_messages[-4].body)
    assert rendered.index(first_messages[-1].body) < rendered.index(
        package.related_messages[0].body
    )
    assert rendered.index(package.related_messages[-1].body) < rendered.index(
        "FIRST ATTACHMENT TEXT"
    )


def test_budget_discards_oldest_related_messages_before_recent_messages(
    repository,
) -> None:
    conversation = repository.create_conversation("budget")
    messages = tuple(
        repository.append_user_message(
            conversation.id,
            f"英语 relevant {index} " + ("x" * 28),
            request_id=f"budget-{index}",
        )
        for index in range(6)
    )

    package = ContextBuilder(
        repository,
        recent_limit=2,
        related_limit=4,
        character_budget=145,
    ).build(conversation.id, "英语 relevant")

    assert package.recent_messages == messages[-2:]
    assert len(package.render_for_model()) <= 145
    assert len(package.related_messages) < 4
    if package.related_messages:
        assert package.related_messages == messages[4 - len(package.related_messages) : 4]


def test_current_draft_reserves_space_inside_the_character_budget(repository) -> None:
    conversation = repository.create_conversation("draft budget")
    repository.append_user_message(
        conversation.id, "m" * 50, request_id="draft-budget-message"
    )
    current_text = "d" * 80

    package = ContextBuilder(
        repository,
        recent_limit=1,
        related_limit=0,
        character_budget=100,
    ).build(conversation.id, current_text)

    assert len(package.render_for_model()) + len(current_text) <= 100


def test_editing_or_deleting_covered_messages_invalidates_summary_immediately(
    repository,
) -> None:
    conversation = repository.create_conversation("invalidation")
    first = repository.append_user_message(
        conversation.id, "first", request_id="invalidate-first"
    )
    second = repository.append_user_message(
        conversation.id, "second", request_id="invalidate-second"
    )
    third = repository.append_user_message(
        conversation.id, "third", request_id="invalidate-third"
    )
    summary = repository.save_context_summary(
        conversation.id,
        "summary one",
        start_message_id=first.id,
        end_message_id=second.id,
        context_version=conversation.context_version,
    )
    builder = ContextBuilder(
        repository, recent_limit=3, related_limit=0, character_budget=500
    )

    assert builder.build(conversation.id, "draft").summary == summary

    repository.edit_message(conversation.id, first.id, "first edited")

    edited_version = repository.get_conversation(conversation.id).context_version
    assert edited_version == conversation.context_version + 1
    assert builder.build(conversation.id, "draft").summary is None

    replacement = repository.save_context_summary(
        conversation.id,
        "summary two",
        start_message_id=first.id,
        end_message_id=third.id,
        context_version=edited_version,
    )
    assert builder.build(conversation.id, "draft").summary == replacement

    repository.delete_message(conversation.id, second.id)

    assert repository.get_conversation(conversation.id).context_version == edited_version + 1
    package = builder.build(conversation.id, "draft")
    assert package.summary is None
    assert tuple(message.body for message in package.recent_messages) == (
        "first edited",
        "third",
    )


class SuccessfulSummarizer:
    def summarize(
        self,
        messages: tuple[Message, ...],
        covered_range: tuple[str, str],
        context_version: int,
    ) -> str:
        range_matches = covered_range == (messages[0].id, messages[-1].id)
        return (
            f"summary range={range_matches} version={context_version}: "
            + ", ".join(message.body for message in messages)
        )


class FailingSummarizer:
    def summarize(
        self,
        messages: tuple[Message, ...],
        covered_range: tuple[str, str],
        context_version: int,
    ) -> str:
        raise RuntimeError("summarizer unavailable")


def test_summary_coordinator_persists_successful_same_thread_summary(repository) -> None:
    conversation = repository.create_conversation("summary success")
    first = repository.append_user_message(
        conversation.id, "one", request_id="summary-success-one"
    )
    second = repository.append_user_message(
        conversation.id, "two", request_id="summary-success-two"
    )

    summary = SummaryCoordinator(repository, SuccessfulSummarizer()).summarize(
        conversation.id, first.id, second.id
    )

    assert summary.body == "summary range=True version=1: one, two"
    assert summary.start_message_id == first.id
    assert summary.end_message_id == second.id
    assert summary.context_version == conversation.context_version
    assert repository.list_context_summaries(conversation.id) == (summary,)


def test_summary_failure_keeps_original_messages_available_for_fallback(
    repository,
) -> None:
    conversation = repository.create_conversation("summary failure")
    first = repository.append_user_message(
        conversation.id, "one", request_id="summary-failure-one"
    )
    second = repository.append_user_message(
        conversation.id, "two", request_id="summary-failure-two"
    )

    with pytest.raises(RuntimeError, match="summarizer unavailable"):
        SummaryCoordinator(repository, FailingSummarizer()).summarize(
            conversation.id, first.id, second.id
        )

    assert repository.list_context_summaries(conversation.id) == ()
    assert repository.list_messages(conversation.id) == (first, second)
    package = ContextBuilder(
        repository, recent_limit=2, related_limit=0, character_budget=100
    ).build(conversation.id, "draft")
    assert package.summary is None
    assert package.recent_messages == (first, second)


@pytest.mark.parametrize("mutation", ("edit", "delete"))
def test_summary_coordinator_rejects_covered_mutation_during_summarization(
    repository, mutation
) -> None:
    conversation = repository.create_conversation("summary race")
    first = repository.append_user_message(
        conversation.id, "before edit", request_id="summary-race-first"
    )
    second = repository.append_user_message(
        conversation.id, "second", request_id="summary-race-second"
    )
    summarizer_started = Event()
    release_summarizer = Event()
    errors: list[BaseException] = []

    class BlockingSummarizer:
        def summarize(
            self,
            messages: tuple[Message, ...],
            covered_range: tuple[str, str],
            context_version: int,
        ) -> str:
            summarizer_started.set()
            assert release_summarizer.wait(5)
            return "stale generated summary"

    def generate_summary() -> None:
        try:
            SummaryCoordinator(repository, BlockingSummarizer()).summarize(
                conversation.id, first.id, second.id
            )
        except BaseException as error:
            errors.append(error)

    worker = Thread(target=generate_summary)
    worker.start()
    assert summarizer_started.wait(5)

    if mutation == "edit":
        repository.edit_message(conversation.id, first.id, "after edit")
    else:
        repository.delete_message(conversation.id, first.id)
    release_summarizer.set()
    worker.join(5)

    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
    assert str(errors[0]) == "Messages changed during summarization"
    assert repository.list_context_summaries(conversation.id) == ()
    expected_bodies = ("after edit", "second") if mutation == "edit" else ("second",)
    assert tuple(
        message.body for message in repository.list_messages(conversation.id)
    ) == expected_bodies


def test_builder_never_combines_records_from_different_read_snapshots(
    repository, monkeypatch
) -> None:
    conversation = repository.create_conversation("builder snapshot")
    first = repository.append_user_message(
        conversation.id, "covered", request_id="snapshot-first"
    )
    repository.append_user_message(
        conversation.id, "recent", request_id="snapshot-second"
    )
    summary = repository.save_context_summary(
        conversation.id,
        "old summary",
        start_message_id=first.id,
        end_message_id=first.id,
        context_version=conversation.context_version,
    )
    message_read_started = Event()
    release_reader = Event()
    original_message_from_row = repository._message_from_row
    paused = False

    def pause_during_message_read(row):
        nonlocal paused
        if not paused:
            paused = True
            message_read_started.set()
            assert release_reader.wait(5)
        return original_message_from_row(row)

    monkeypatch.setattr(repository, "_message_from_row", pause_during_message_read)
    packages = []
    errors: list[BaseException] = []

    def build_context() -> None:
        try:
            packages.append(
                ContextBuilder(
                    repository,
                    recent_limit=2,
                    related_limit=0,
                    character_budget=500,
                ).build(conversation.id, "draft")
            )
        except BaseException as error:
            errors.append(error)

    worker = Thread(target=build_context)
    worker.start()
    assert message_read_started.wait(5)

    repository.edit_message(conversation.id, first.id, "edited covered")
    new_fact = repository.save_confirmed_fact(conversation.id, "new concurrent fact")
    release_reader.set()
    worker.join(5)

    assert not worker.is_alive()
    assert errors == []
    assert len(packages) == 1
    package = packages[0]
    assert not (package.summary == summary and new_fact in package.confirmed_facts)
    assert repository.get_conversation(conversation.id).context_version == 2
    assert repository.list_confirmed_facts(conversation.id) == (new_fact,)
