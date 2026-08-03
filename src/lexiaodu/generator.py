from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from lexiaodu.knowledge import SearchResult


class GenerationError(RuntimeError):
    """Raised when a generator cannot return a usable suggestion."""


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    transcript: str
    policy_results: tuple[SearchResult, ...]
    style_results: tuple[SearchResult, ...]

    def __post_init__(self) -> None:
        if not self.transcript.strip():
            raise ValueError("对话内容不能为空")


@dataclass(frozen=True, slots=True)
class SuggestionDraft:
    concern_summary: str
    wechat_reply: str

    def __post_init__(self) -> None:
        if not self.concern_summary.strip():
            raise ValueError("顾虑摘要不能为空")
        if not self.wechat_reply.strip():
            raise ValueError("微信短回复不能为空")


class Generator(Protocol):
    """Replaceable structured generator boundary."""

    def generate(self, request: GenerationRequest) -> SuggestionDraft:
        """Generate editable copy from the supplied retrieval results."""


def _compact(value: str, maximum: int) -> str:
    text = " ".join(value.split())
    if len(text) <= maximum:
        return text
    return f"{text[: maximum - 1].rstrip()}…"


class SimulatedGenerator:
    """Deterministic local generator grounded in actual retrieval results."""

    def generate(self, request: GenerationRequest) -> SuggestionDraft:
        question = _compact(request.transcript, 72)
        if request.policy_results:
            primary = request.policy_results[0]
            fact = _compact(primary.evidence, 120).rstrip("。")
            source = f"《{primary.document_name}》{primary.locator}"
            summary = f"家长关注“{question}”，需要依据{source}给出明确说明。"
            reply = (
                f"您好，理解您的顾虑。根据{source}的说明，{fact}。"
                "我会按这一规则继续协助您；如实际情况有差异，我先为您核实。"
            )
        else:
            summary = f"家长关注“{question}”，但本地暂未检索到可核实的制度依据。"
            reply = (
                "您好，理解您的顾虑。目前我还没有检索到可以确认的制度依据，"
                "我先为您转人工核实，确认后再给您准确回复。"
            )

        if request.style_results:
            reply = reply.replace("您好，理解您的顾虑。", "您好，能理解您的顾虑。", 1)
        return SuggestionDraft(summary, reply)


def build_openai_messages(request: GenerationRequest) -> list[dict[str, str]]:
    """Build messages accepted by OpenAI-compatible chat-completion APIs."""

    evidence = [
        {
            "type": result.knowledge_type.value,
            "document": result.document_name,
            "locator": result.locator,
            "evidence": result.evidence,
        }
        for result in (*request.policy_results, *request.style_results)
    ]
    payload = json.dumps(
        {"transcript": request.transcript, "retrieval_results": evidence},
        ensure_ascii=False,
    )
    return [
        {
            "role": "system",
            "content": (
                "你是乐小读顾问建议生成器。只依据给定检索结果生成内容，不得编造"
                "制度或来源。仅返回 JSON 对象，字段为 concern_summary 和 "
                "wechat_reply。事实依据由调用方绑定，不要输出引用字段。"
            ),
        },
        {"role": "user", "content": payload},
    ]


def _response_content(response: Any) -> str:
    try:
        choice = response.choices[0]
        message = choice.message
        content = message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise GenerationError("OpenAI 兼容响应缺少 choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise GenerationError("OpenAI 兼容响应内容为空")
    return content


class OpenAICompatibleGenerator:
    """Generator adapter for clients exposing client.chat.completions.create."""

    def __init__(
        self,
        client: Any,
        model: str,
        *,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("模型名称不能为空")
        if max_tokens is not None and max_tokens < 1:
            raise ValueError("max_tokens 必须大于 0")
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._extra_body = dict(extra_body) if extra_body else None

    def generate(self, request: GenerationRequest) -> SuggestionDraft:
        try:
            options: dict[str, Any] = {
                "model": self._model,
                "messages": build_openai_messages(request),
                "response_format": {"type": "json_object"},
            }
            if self._max_tokens is not None:
                options["max_tokens"] = self._max_tokens
            if self._extra_body is not None:
                options["extra_body"] = self._extra_body
            response = self._client.chat.completions.create(
                **options,
            )
            payload = json.loads(_response_content(response))
            return SuggestionDraft(
                concern_summary=payload["concern_summary"].strip(),
                wechat_reply=payload["wechat_reply"].strip(),
            )
        except GenerationError:
            raise
        except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise GenerationError(f"OpenAI 兼容生成结果无效: {exc}") from exc
