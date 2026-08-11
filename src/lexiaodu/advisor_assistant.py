from __future__ import annotations

import json
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
                    knowledge_evidence=knowledge_evidence,
                )
                if selected
                else self._respond_with_chat(context)
            )
        except KnowledgeDocumentError as exc:
            return f"{exc}，因此本次不能依据该文档回答公司事实。"
        except Exception as exc:
            raise AdvisorAssistantError("豆包顾问对话失败") from exc
        if not isinstance(content, str) or not content.strip():
            raise AdvisorAssistantError("豆包顾问返回为空")
        content = content.strip()
        missing_names = [
            document.name for document in selected if document.name not in content
        ]
        if missing_names:
            sources = "、".join(f"《{name}》" for name in missing_names)
            content = f"{content}\n\n依据原文件：{sources}"
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
                    "content": (
                        f"当前会话：\n{context.render_for_model()}\n\n"
                        "可选原文档（文档 ID\t文件名）：\n"
                        + "\n".join(
                            f"{document.doc_id}\t{document.name}"
                            for document in documents
                        )
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

    def _respond_with_chat(self, context: ContextPackage) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": context.render_for_model()},
            ],
            max_tokens=800,
            extra_body={"thinking": {"type": "disabled"}},
        )
        return response.choices[0].message.content

    def _respond_with_knowledge_documents(
        self,
        context: ContextPackage,
        *,
        knowledge_evidence: str | None,
    ) -> str:
        prompt = (
            f"{_SYSTEM_PROMPT}\n\n"
            f"当前会话：\n{context.render_for_model()}\n\n"
            "方舟知识库从本次所选原文档检索到：\n"
            f"{knowledge_evidence}"
        )
        response = self._client.responses.create(
            model=self._model,
            input=[
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
        )
        return response.output_text


_SYSTEM_PROMPT = (
    "你是乐小读，直接和公司顾问讨论家长顾虑。"
    "你可以独立分析、判断并自然追问，但一次最多追问一个关键问题。"
    "公司事实只能来自明确提供的公司原文档；当前上下文没有依据时，"
    "要说明待核实，不要编造。引用公司事实时标明文件名，能够识别页码或章节时一并标明。"
    "课程名额、订单、付款和 App 显示等实时状态必须请顾问查询业务系统。"
    "涉及退款、投诉、法律、人身安全、健康、隐私或儿童保护时，不作确定承诺，提示人工核实。"
    "不要假装已经把消息发送给家长。"
)
