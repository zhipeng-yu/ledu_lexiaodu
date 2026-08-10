from __future__ import annotations

from typing import Any

from .context import ContextPackage


class AdvisorAssistantError(RuntimeError):
    pass


class OpenAIConversationAssistant:
    def __init__(self, client: Any, model: str) -> None:
        if not model.strip():
            raise ValueError("模型名称不能为空")
        self._client = client
        self._model = model.strip()

    def respond(self, context: ContextPackage, request_id: str) -> str:
        del request_id
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是乐小读，直接和公司顾问讨论家长顾虑。"
                            "你可以独立分析、判断并自然追问，但一次最多追问一个关键问题。"
                            "公司事实只能来自明确提供的公司原文档；当前上下文没有依据时，"
                            "要说明待核实，不要编造。不要假装已经把消息发送给家长。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": context.render_for_model(),
                    },
                ],
                max_tokens=800,
                extra_body={"thinking": {"type": "disabled"}},
            )
            content = response.choices[0].message.content
        except Exception as exc:
            raise AdvisorAssistantError("豆包顾问对话失败") from exc
        if not isinstance(content, str) or not content.strip():
            raise AdvisorAssistantError("豆包顾问返回为空")
        return content.strip()
