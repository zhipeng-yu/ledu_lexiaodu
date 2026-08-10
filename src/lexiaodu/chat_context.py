from __future__ import annotations

from dataclasses import dataclass

from lexiaodu.chat_repository import ConversationRepository, Message


_ROLE_LABELS = {"user": "顾问", "assistant": "乐小读"}


@dataclass(frozen=True, slots=True)
class ContextPackage:
    messages: tuple[Message, ...]
    context_version: int

    def render_for_model(self) -> str:
        return "\n".join(
            f"{_ROLE_LABELS.get(message.role, message.role)}：{message.body}"
            for message in self.messages
        )


class ContextBuilder:
    def __init__(
        self,
        repository: ConversationRepository,
        *,
        character_budget: int,
    ) -> None:
        if character_budget < 1:
            raise ValueError("character_budget 必须是正整数")
        self._repository = repository
        self._character_budget = character_budget

    def build(self, conversation_id: str) -> ContextPackage:
        conversation = self._repository.get_conversation(conversation_id)
        messages = self._repository.list_messages(conversation_id)
        selected: list[Message] = []
        used = 0
        for message in reversed(messages):
            label = _ROLE_LABELS.get(message.role, message.role)
            length = len(label) + 1 + len(message.body) + (1 if selected else 0)
            if selected and used + length > self._character_budget:
                break
            selected.append(message)
            used += length
        selected.reverse()
        return ContextPackage(tuple(selected), conversation.context_version)
