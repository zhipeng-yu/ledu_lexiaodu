from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .context import ContextPackage


class AdvisorAssistantError(RuntimeError):
    pass


class OpenAIConversationAssistant:
    def __init__(
        self,
        client: Any,
        model: str,
        *,
        document_dir: Path = Path("company_documents"),
    ) -> None:
        if not model.strip():
            raise ValueError("模型名称不能为空")
        self._client = client
        self._model = model.strip()
        self._document_dir = Path(document_dir)
        self._document_dir.mkdir(parents=True, exist_ok=True)

    def respond(self, context: ContextPackage, request_id: str) -> str:
        del request_id
        try:
            documents = self._available_documents()
            selected = self._select_documents(context, documents)
            unsupported = tuple(
                path for path in selected if path.suffix.casefold() != ".pdf"
            )
            if unsupported:
                names = "、".join(path.name for path in unsupported)
                return (
                    f"我判断本次需要参考《{names}》，但该格式必须通过方舟文档知识库读取，"
                    "当前尚未完成知识库接口配置，因此不能据此编造公司事实。"
                )
            content = (
                self._respond_with_original_documents(context, selected)
                if selected
                else self._respond_with_chat(context)
            )
        except Exception as exc:
            raise AdvisorAssistantError("豆包顾问对话失败") from exc
        if not isinstance(content, str) or not content.strip():
            raise AdvisorAssistantError("豆包顾问返回为空")
        return content.strip()

    def _available_documents(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                (
                    path
                    for path in self._document_dir.rglob("*")
                    if path.is_file()
                    and path.suffix.casefold() in _SUPPORTED_FORMATS
                ),
                key=lambda path: path.relative_to(self._document_dir).as_posix(),
            )
        )

    def _select_documents(
        self,
        context: ContextPackage,
        documents: tuple[Path, ...],
    ) -> tuple[Path, ...]:
        if not documents:
            return ()
        by_name = {
            path.relative_to(self._document_dir).as_posix(): path
            for path in documents
        }
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你只负责选择回答当前顾问问题所需的公司原文档。"
                        "只能从给定相对路径中选择，最多三份；不需要文档就返回空数组。"
                        '只返回 JSON：{"files":["相对路径"]}。'
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"当前会话：\n{context.render_for_model()}\n\n"
                        "可选原文档：\n" + "\n".join(by_name)
                    ),
                },
            ],
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
        )
        payload = json.loads(response.choices[0].message.content)
        names = payload.get("files")
        if not isinstance(names, list):
            raise ValueError("文档路由结果无效")
        selected: list[Path] = []
        for name in names[:3]:
            if isinstance(name, str) and name in by_name and by_name[name] not in selected:
                selected.append(by_name[name])
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

    def _respond_with_original_documents(
        self,
        context: ContextPackage,
        documents: tuple[Path, ...],
    ) -> str:
        file_ids: list[str] = []
        try:
            for path in documents:
                if path.suffix.casefold() != ".pdf" or not path.is_file():
                    raise ValueError("当前只支持上传 PDF 原文档")
                with path.open("rb") as source:
                    uploaded = self._client.files.create(
                        file=source,
                        purpose="user_data",
                    )
                file_ids.append(uploaded.id)
                self._wait_until_active(uploaded.id)
            response = self._client.responses.create(
                model=self._model,
                input=[
                    {
                        "role": "user",
                        "content": [
                            *(
                                {"type": "input_file", "file_id": file_id}
                                for file_id in file_ids
                            ),
                            {
                                "type": "input_text",
                                "text": f"{_SYSTEM_PROMPT}\n\n{context.render_for_model()}",
                            },
                        ],
                    }
                ],
            )
            return response.output_text
        finally:
            for file_id in file_ids:
                try:
                    self._client.files.delete(file_id)
                except Exception:
                    pass

    def _wait_until_active(self, file_id: str) -> None:
        deadline = time.monotonic() + 60
        while True:
            status = self._client.files.retrieve(file_id).status
            if status == "active":
                return
            if status in {"failed", "error", "cancelled", "expired"}:
                raise RuntimeError("方舟未能读取 PDF")
            if time.monotonic() >= deadline:
                raise TimeoutError("等待方舟读取 PDF 超时")
            time.sleep(1)


_SYSTEM_PROMPT = (
    "你是乐小读，直接和公司顾问讨论家长顾虑。"
    "你可以独立分析、判断并自然追问，但一次最多追问一个关键问题。"
    "公司事实只能来自明确提供的公司原文档；当前上下文没有依据时，"
    "要说明待核实，不要编造。不要假装已经把消息发送给家长。"
)

_SUPPORTED_FORMATS = frozenset({".pdf", ".docx", ".pptx", ".xlsx"})
