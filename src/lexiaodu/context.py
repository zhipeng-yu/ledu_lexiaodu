from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from lexiaodu.conversations import (
    Attachment,
    ConfirmedFact,
    ContextSummary,
    ConversationRepository,
    Message,
)


ContextItem = ConfirmedFact | ContextSummary | Message | Attachment


@dataclass(frozen=True, slots=True)
class ContextPackage:
    confirmed_facts: tuple[ConfirmedFact, ...]
    summary: ContextSummary | None
    recent_messages: tuple[Message, ...]
    related_messages: tuple[Message, ...]
    attachment_texts: tuple[Attachment, ...]
    context_version: int

    def all_items(self) -> tuple[ContextItem, ...]:
        summary = (self.summary,) if self.summary is not None else ()
        return (
            *self.confirmed_facts,
            *summary,
            *self.recent_messages,
            *self.related_messages,
            *self.attachment_texts,
        )

    def render_for_model(self) -> str:
        return "\n".join(item.text for item in self.all_items())


class ContextBuilder:
    def __init__(
        self,
        repository: ConversationRepository,
        recent_limit: int,
        related_limit: int,
        character_budget: int,
    ) -> None:
        self._repository = repository
        self._recent_limit = recent_limit
        self._related_limit = related_limit
        self._character_budget = character_budget

    def build(self, conversation_id: str, current_text: str) -> ContextPackage:
        conversation = self._repository.get_conversation(conversation_id)
        messages = self._repository.list_messages(conversation_id)
        summary, available_messages = self._valid_summary(
            conversation_id, conversation.context_version, messages
        )
        recent_messages = (
            available_messages[-self._recent_limit :]
            if self._recent_limit > 0
            else ()
        )
        older_messages = (
            available_messages[: -len(recent_messages)]
            if recent_messages
            else available_messages
        )
        related_messages = self._related_messages(older_messages, current_text)
        confirmed_facts = self._repository.list_confirmed_facts(conversation_id)
        attachment_texts = self._repository.list_attachment_texts(conversation_id)

        package = ContextPackage(
            confirmed_facts=confirmed_facts,
            summary=summary,
            recent_messages=recent_messages,
            related_messages=related_messages,
            attachment_texts=attachment_texts,
            context_version=conversation.context_version,
        )
        return self._fit_budget(package, reserved_characters=len(current_text))

    def _valid_summary(
        self,
        conversation_id: str,
        context_version: int,
        messages: tuple[Message, ...],
    ) -> tuple[ContextSummary | None, tuple[Message, ...]]:
        message_indexes = {message.id: index for index, message in enumerate(messages)}
        for summary in reversed(
            self._repository.list_context_summaries(conversation_id)
        ):
            if summary.context_version != context_version:
                continue
            if (
                summary.start_message_id not in message_indexes
                or summary.end_message_id not in message_indexes
            ):
                continue
            first_index = message_indexes[summary.start_message_id]
            last_index = message_indexes[summary.end_message_id]
            lower, upper = sorted((first_index, last_index))
            available = messages[:lower] + messages[upper + 1 :]
            return summary, available
        return None, messages

    def _related_messages(
        self, messages: tuple[Message, ...], current_text: str
    ) -> tuple[Message, ...]:
        current_tokens = _normalized_tokens(current_text)
        if not current_tokens or self._related_limit <= 0:
            return ()
        scored = [
            (len(current_tokens & _normalized_tokens(message.body)), index, message)
            for index, message in enumerate(messages)
        ]
        selected = sorted(
            (item for item in scored if item[0] > 0),
            key=lambda item: (-item[0], -item[1]),
        )[: self._related_limit]
        return tuple(item[2] for item in sorted(selected, key=lambda item: item[1]))

    def _fit_budget(
        self, package: ContextPackage, *, reserved_characters: int
    ) -> ContextPackage:
        facts = package.confirmed_facts
        summary = package.summary
        recent = package.recent_messages
        related = package.related_messages
        attachments = package.attachment_texts
        available_budget = max(0, self._character_budget - reserved_characters)

        def render_length() -> int:
            candidate = ContextPackage(
                facts,
                summary,
                recent,
                related,
                attachments,
                package.context_version,
            )
            return len(candidate.render_for_model())

        while related and render_length() > available_budget:
            related = related[1:]
        while recent and render_length() > available_budget:
            recent = recent[1:]
        while facts and render_length() > available_budget:
            facts = facts[1:]
        if summary is not None and render_length() > available_budget:
            summary = None
        while attachments and render_length() > available_budget:
            attachments = attachments[1:]

        return ContextPackage(
            confirmed_facts=facts,
            summary=summary,
            recent_messages=recent,
            related_messages=related,
            attachment_texts=attachments,
            context_version=package.context_version,
        )


class ContextSummarizer(Protocol):
    def summarize(
        self,
        messages: tuple[Message, ...],
        covered_range: tuple[str, str],
        context_version: int,
    ) -> str: ...


class SummaryCoordinator:
    def __init__(
        self,
        repository: ConversationRepository,
        summarizer: ContextSummarizer,
    ) -> None:
        self._repository = repository
        self._summarizer = summarizer

    def summarize(
        self,
        conversation_id: str,
        start_message_id: str,
        end_message_id: str,
    ) -> ContextSummary:
        conversation = self._repository.get_conversation(conversation_id)
        messages = self._repository.list_messages(conversation_id)
        message_indexes = {message.id: index for index, message in enumerate(messages)}
        try:
            first_index = message_indexes[start_message_id]
            last_index = message_indexes[end_message_id]
        except KeyError as error:
            raise KeyError(error.args[0]) from None
        lower, upper = sorted((first_index, last_index))
        covered_messages = messages[lower : upper + 1]
        body = self._summarizer.summarize(
            covered_messages,
            (start_message_id, end_message_id),
            conversation.context_version,
        )
        return self._repository.save_context_summary(
            conversation_id,
            body,
            start_message_id=start_message_id,
            end_message_id=end_message_id,
            context_version=conversation.context_version,
        )


def _normalized_tokens(text: str) -> frozenset[str]:
    return frozenset(
        token.casefold()
        for token in re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]", text)
    )
