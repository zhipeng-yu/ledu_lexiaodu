from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from lexiaodu.knowledge import SearchResult


_SYSTEM_PROMPT = (
    "你是乐读资深学习顾问的回复助手，负责生成顾问可以直接发给家长的微信短回复。"
    "输入中的 policy_results 只用于事实、规则和产品信息；style_results 只用于参考表达方式，"
    "绝不能把风格案例中的课程信息、服务内容或结果描述当作事实。"
    "wechat_reply 按照‘接住家长的问题—给出明确回答或判断—主动推进下一步’组织成 2 到 3 段短消息，"
    "段落之间用换行分隔，每段只表达一个重点。"
    "语气要像熟悉孩子情况的真人顾问，亲切、直接、有行动感；可自然使用‘哈、呀、呢、～’中的一两处，"
    "整条最多使用一个轻量表情，不得堆叠口癖或表情。"
    "第一段必须以称呼开头：对话中已出现‘某某妈妈/爸爸’或其他家长称呼时原样沿用，"
    "例如出现‘乐乐妈妈’就以‘乐乐妈妈，’开头；没有明确身份时以‘家长，’开头。"
    "不得猜测监护人性别，整条回复只出现这一次称呼；全篇统一使用‘您’，不得和‘你’混用。"
    "不要使用客服或免责声明式表达，包括‘您好’‘理解您的顾虑’‘根据规定’‘我方’‘请耐心等待’"
    "‘不能保证’‘不能承诺’‘无法保障’‘没有检索到依据’和‘转人工核实’。"
    "家长询问提分、通过率或学习效果时，不主动声明边界，改为说明孩子基础、学习过程、反馈和调整方案；"
    "同时不得给出固定涨分、固定通过率、包过或一定有效等结果承诺。"
    "事实不足时，不向家长解释检索或系统状态，只自然说明‘这个我帮您确认一下哈’，"
    "并说清接下来要核实什么。不得编造制度、课程、教师、价格、名额、效果或来源，"
    "也不添加资料中没有的‘名额紧张’‘性价比高’‘很划算’等促销判断。"
    "主动推进的动作也必须有事实依据：资料只说‘可先诊断’时，只能建议先诊断，"
    "不得补充‘免费’‘预约入口’或‘发送链接’；资料未说明办理方式时，"
    "只能说会继续确认，不得声称可以代报名、直接办理或发送资料。"
    "concern_summary 是给顾问看的简短顾虑摘要；wechat_reply 只放对家长说的话，不输出资料名称、章节或引用。"
    "仅返回 JSON 对象，字段固定为 concern_summary 和 wechat_reply。"
)


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
            fact = _compact(primary.evidence, 120).rstrip("。！？!?")
            source = f"《{primary.document_name}》{primary.locator}"
            summary = f"家长关注“{question}”，需要依据{source}给出明确说明。"
            reply = (
                "家长，您问的这个我帮您看过啦～\n"
                f"{fact}。\n"
                "如果您还有具体时间或班型要求，也可以一起告诉我，"
                "我再帮您对着看一下。"
            )
        else:
            summary = f"家长关注“{question}”，但本地暂未检索到可核实的制度依据。"
            reply = (
                "家长，这个我先帮您确认一下哈。\n"
                "我把具体安排问清楚后就回复您，您不用自己来回找。"
            )
        return SuggestionDraft(summary, reply)


def build_openai_messages(request: GenerationRequest) -> list[dict[str, str]]:
    """Build messages accepted by OpenAI-compatible chat-completion APIs."""

    policy_results = [
        {
            "document": result.document_name,
            "locator": result.locator,
            "evidence": result.evidence,
        }
        for result in request.policy_results
    ]
    style_results = [
        {
            "document": result.document_name,
            "locator": result.locator,
            "example": result.evidence,
        }
        for result in request.style_results
    ]
    payload = json.dumps(
        {
            "transcript": request.transcript,
            "policy_results": policy_results,
            "style_results": style_results,
        },
        ensure_ascii=False,
    )
    return [
        {
            "role": "system",
            "content": _SYSTEM_PROMPT,
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
