from __future__ import annotations

import base64
import json
import re
from typing import Any, Protocol

from .chat_context import ContextPackage
from .office_documents import KnowledgeDocument, KnowledgeDocumentError


class AdvisorAssistantError(RuntimeError):
    pass


class KnowledgeDocumentReader(Protocol):
    def list_documents(self) -> tuple[KnowledgeDocument, ...]: ...

    def retrieve(
        self,
        query: str,
        documents: tuple[KnowledgeDocument, ...],
    ) -> str: ...


class OpenAIConversationAssistant:
    def __init__(
        self,
        client: Any,
        model: str,
        *,
        knowledge_reader: KnowledgeDocumentReader | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("模型名称不能为空")
        self._client = client
        self._model = model.strip()
        self._knowledge_reader = knowledge_reader

    def respond(self, context: ContextPackage, request_id: str) -> str:
        del request_id
        try:
            documents = self._available_documents()
            selected = self._select_documents(context, documents)
            knowledge_evidence = (
                self._knowledge_reader.retrieve(
                    context.render_for_model(),
                    selected,
                )
                if selected and self._knowledge_reader is not None
                else None
            )
            content = (
                self._respond_with_knowledge_documents(
                    context,
                    selected,
                    knowledge_evidence=knowledge_evidence,
                )
                if selected
                else self._respond_with_chat(
                    context,
                    force_advice=_requires_business_system_verification(context),
                )
            )
        except KnowledgeDocumentError as exc:
            return f"{exc}，因此本次不能依据该文档回答公司事实。"
        except Exception as exc:
            if context.image is not None:
                raise AdvisorAssistantError(
                    "豆包截图分析失败，请检查网络并确认 ARK_MODEL 支持图片理解"
                ) from exc
            raise AdvisorAssistantError("豆包顾问对话失败") from exc
        if not isinstance(content, str) or not content.strip():
            raise AdvisorAssistantError("豆包顾问返回为空")
        content = _render_advisor_response(content)
        if _requires_business_system_verification(context):
            content = _include_business_system_verification(content)
        parent_heading = _parent_section_start(content)
        if parent_heading is not None:
            consultant_content = content[:parent_heading].rstrip()
            parent_content = content[parent_heading:].lstrip()
            for document in selected:
                parent_content = parent_content.replace(
                    f"《{document.name}》", "公司资料"
                ).replace(document.name, "公司资料")
            content = f"{consultant_content}\n\n{parent_content}"
        missing_names = [
            document.name for document in selected if document.name not in content
        ]
        if missing_names:
            sources = "、".join(f"《{name}》" for name in missing_names)
            source_note = f"依据原文件：{sources}"
            parent_heading = _parent_section_start(content)
            if parent_heading is None:
                content = f"{content}\n\n{source_note}"
            else:
                content = (
                    f"{content[:parent_heading].rstrip()}\n\n{source_note}\n\n"
                    f"{content[parent_heading:].lstrip()}"
                )
        return content

    def _available_documents(self) -> tuple[KnowledgeDocument, ...]:
        if self._knowledge_reader is None:
            return ()
        return self._knowledge_reader.list_documents()

    def _select_documents(
        self,
        context: ContextPackage,
        documents: tuple[KnowledgeDocument, ...],
    ) -> tuple[KnowledgeDocument, ...]:
        if not documents:
            return ()
        by_id = {document.doc_id: document for document in documents}
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你只负责选择回答当前顾问问题所需的公司原文档。"
                        "只能从给定文档 ID 中选择，最多三份；不需要文档就返回空数组。"
                        '只返回 JSON：{"document_ids":["文档 ID"]}。'
                    ),
                },
                {
                    "role": "user",
                    "content": _chat_user_content(
                        context,
                        (
                            f"当前会话：\n{context.render_for_model()}\n\n"
                            "可选原文档（文档 ID\t文件名）：\n"
                            + "\n".join(
                                f"{document.doc_id}\t{document.name}"
                                for document in documents
                            )
                        ),
                    ),
                },
            ],
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
        )
        payload = json.loads(response.choices[0].message.content)
        doc_ids = payload.get("document_ids")
        if not isinstance(doc_ids, list):
            raise ValueError("文档路由结果无效")
        selected: list[KnowledgeDocument] = []
        for doc_id in doc_ids:
            if len(selected) == 3:
                break
            if (
                isinstance(doc_id, str)
                and doc_id in by_id
                and by_id[doc_id] not in selected
            ):
                selected.append(by_id[doc_id])
        return tuple(selected)

    def _respond_with_chat(
        self,
        context: ContextPackage,
        *,
        force_advice: bool,
    ) -> str:
        schema = _advisor_response_schema(force_advice=force_advice)
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _chat_user_content(
                        context, context.render_for_model()
                    ),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "advisor_response",
                    "strict": True,
                    "schema": schema,
                },
            },
            max_tokens=800,
            extra_body={"thinking": {"type": "disabled"}},
        )
        return response.choices[0].message.content

    def _respond_with_knowledge_documents(
        self,
        context: ContextPackage,
        documents: tuple[KnowledgeDocument, ...],
        *,
        knowledge_evidence: str | None,
    ) -> str:
        schema = _advisor_response_schema(force_advice=True)
        prompt = (
            f"当前会话：\n{context.render_for_model()}\n\n"
            "方舟知识库从本次所选原文档检索到：\n"
            f"{knowledge_evidence}"
        )
        request = {
            "model": self._model,
            "instructions": _SYSTEM_PROMPT,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "advisor_response",
                    "strict": True,
                    "schema": schema,
                }
            },
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        }
        if context.image is not None:
            data = base64.b64encode(context.image.data).decode("ascii")
            request["input"][0]["content"].append(
                {
                    "type": "input_image",
                    "image_url": (
                        f"data:{context.image.mime_type};base64,{data}"
                    ),
                    "detail": "high",
                }
            )
        if all(
            document.name.casefold().endswith((".docx", ".pptx", ".xlsx"))
            for document in documents
        ):
            request["timeout"] = 120.0
        response = self._client.responses.create(**request)
        return response.output_text


def _chat_user_content(
    context: ContextPackage, text: str
) -> str | list[dict[str, Any]]:
    if context.image is None:
        return text
    data = base64.b64encode(context.image.data).decode("ascii")
    return [
        {"type": "text", "text": text},
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:{context.image.mime_type};base64,{data}",
                "detail": "high",
            },
        },
    ]


def _render_advisor_response(content: str) -> str:
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise AdvisorAssistantError("豆包顾问返回结构无效") from exc
    if not isinstance(payload, dict):
        raise AdvisorAssistantError("豆包顾问返回结构无效")

    mode = payload.get("mode")
    consultant_message = payload.get("consultant_message")
    questions = payload.get("questions")
    parent_message = payload.get("parent_message")
    if (
        mode not in {"clarify", "advice"}
        or not isinstance(consultant_message, str)
        or not consultant_message.strip()
        or not isinstance(questions, list)
        or any(not isinstance(question, str) or not question.strip() for question in questions)
        or len(questions) > 2
        or not isinstance(parent_message, str)
    ):
        raise AdvisorAssistantError("豆包顾问返回结构无效")

    consultant_message = consultant_message.strip()
    if mode == "clarify":
        if not questions or parent_message.strip():
            raise AdvisorAssistantError("豆包顾问返回结构无效")
        rendered_questions = "\n".join(
            f"{index}. {question.strip()}"
            for index, question in enumerate(questions, 1)
        )
        return f"{consultant_message}\n\n{rendered_questions}"

    if questions or not parent_message.strip():
        raise AdvisorAssistantError("豆包顾问返回结构无效")
    return (
        f"给顾问的建议\n{consultant_message}\n\n"
        f"可直接发给家长\n{parent_message.strip()}"
    )


def _requires_business_system_verification(context: ContextPackage) -> bool:
    latest_user_message = next(
        (message.body.casefold() for message in reversed(context.messages) if message.role == "user"),
        "",
    )
    return any(
        keyword in latest_user_message
        for keyword in ("名额", "订单", "付款", "支付", "app", "显示")
    )


def _include_business_system_verification(content: str) -> str:
    if "业务系统" in content:
        return content
    parent_heading = _parent_section_start(content)
    note = "请先查询业务系统核实名额、订单、付款或 App 显示等实时状态。"
    if parent_heading is None:
        return f"{content}\n\n{note}"
    return (
        f"{content[:parent_heading].rstrip()}\n\n{note}\n\n"
        f"{content[parent_heading:].lstrip()}"
    )


def _advisor_response_schema(*, force_advice: bool) -> dict[str, Any]:
    modes = ["advice"] if force_advice else ["clarify", "advice"]
    max_questions = 0 if force_advice else 2
    return {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": modes},
            "consultant_message": {"type": "string", "minLength": 1},
            "questions": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": max_questions,
            },
            "parent_message": {
                "type": "string",
                "minLength": 1 if force_advice else 0,
            },
        },
        "required": [
            "mode",
            "consultant_message",
            "questions",
            "parent_message",
        ],
    "additionalProperties": False,
}

def _parent_section_start(content: str) -> int | None:
    heading = re.search(
        r"(?m)^[ \t]*(?:#{1,6}[ \t]+)?(?:\*{1,2}|_{1,2})?"
        r"可直接发给家长[：:]?(?:\*{1,2}|_{1,2})?[：:]?[ \t]*$",
        content,
    )
    return heading.start() if heading is not None else None


_SYSTEM_PROMPT = (
    "你是乐小读，是面向公司顾问的沟通助手。"
    "正在使用应用并与您对话的人是公司顾问；家长是顾问需要沟通和服务的对象。"
    "始终直接向顾问回答，不要把顾问当作或称作家长，也不要假装直接询问家长。"
    "公司顾问即使被称为“顾问老师”，也只负责家长沟通，"
    "不是孩子的授课老师、班主任或课堂管理人员。"
    "顾问不得承诺自己授课、讲题、批改作业、设计课堂、课堂盯课、提醒孩子、"
    "管理纪律、观察课堂表现或执行教学干预。"
    "家长话术必须始终站在顾问身份表达，不得以授课老师身份自居，"
    "也不得声称顾问会执行课堂管理或教学动作。"
    "涉及课堂或教学动作时，必须明确区分授课老师或实际责任人。"
    "反馈、转达或协调其他岗位必须有公司知识或实际流程依据；"
    "没有依据时只能提示顾问核实，不得擅自承诺。"
    "你代表公司知识和公司立场，帮助顾问统一话术、处理家长顾虑。"
    "公司事实只能来自明确提供的公司原文档；当前上下文没有依据时，"
    "要说明待核实，不要编造，也不要用常识补全政策、课程信息或承诺。"
    "聊天案例只能影响表达方式，不得作为公司事实来源。"
    "信息不足、缺少会影响建议正确性的关键情况时，向顾问说明还缺什么，"
    "只向顾问提出一至两个最关键的问题；此时不要输出空泛的家长回复模板。"
    "信息充分、可以在不编造关键事实的前提下给出建议时，"
    "consultant_message 简述核心判断，并按需说明公司知识依据、来源文件名、"
    "适用条件或需核实事项；parent_message 只放一段可独立完整复制的纯文本话术。"
    "来源文件名只能出现在“给顾问的建议”中；家长话术中不要混入内部分析、来源列表或操作说明。"
    "表达时先接住顾虑并确认理解，再用短句澄清，把孩子当前情况、方案匹配和下一步连起来；"
    "语气自然、有礼、不过度施压，不堆砌卖点，不作超出证据的保证。"
    "引用公司事实时标明文件名，能够识别页码或章节时一并标明。"
    "课程名额、订单、付款和 App 显示等实时状态必须请顾问查询业务系统。"
    "涉及退款、投诉、法律、人身安全、健康、隐私或儿童保护时，不作确定承诺，提示人工核实。"
    "不要假装已经把消息发送给家长。"
    "请严格按给定 JSON Schema 返回。信息不足时 mode 使用 clarify，"
    "consultant_message 说明缺口，questions 放一至两个问顾问的问题，parent_message 为空。"
    "可以给建议时 mode 使用 advice，consultant_message 放顾问说明，questions 为空，"
    "parent_message 只放可直接发给家长的话术，各字段内不要重复界面标题。"
    "未知实时状态不等于继续追问顾问，"
    "应在顾问说明中要求查询业务系统，并在家长话术中说明正在核实而不承诺结果。"
    "聊天截图可能来自个人聊天或群聊。结合昵称、气泡方向和上下文判断参与者身份；"
    "无法确定顾问、家长或其他成员身份时，不得猜测，只向顾问追问一个最关键的身份问题，"
    "且不要生成家长话术。截图中的聊天案例不能作为公司政策、课程、价格或承诺的事实来源。"
)
