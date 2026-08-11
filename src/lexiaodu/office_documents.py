from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class KnowledgeDocumentError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    doc_id: str
    name: str


class ArkKnowledgeDocumentReader:
    def __init__(
        self,
        knowledge_service: Any,
        collection: Any,
    ) -> None:
        self._knowledge_service = knowledge_service
        self._collection = collection
        self._project = collection.project or "default"
        self._resource_id = collection.resource_id

    def list_documents(self) -> tuple[KnowledgeDocument, ...]:
        try:
            documents: list[KnowledgeDocument] = []
            for item in self._collection.list_docs(project=self._project):
                status = item.status
                if isinstance(status, dict):
                    status = status.get("process_status")
                name = item.doc_name
                doc_id = item.doc_id
                if (
                    status == 0
                    and isinstance(name, str)
                    and Path(name).suffix.casefold() in _SUPPORTED_FORMATS
                    and isinstance(doc_id, str)
                    and doc_id.strip()
                ):
                    documents.append(KnowledgeDocument(doc_id.strip(), name))
            return tuple(
                sorted(
                    documents,
                    key=lambda document: (document.name.casefold(), document.doc_id),
                )
            )
        except Exception as exc:
            raise KnowledgeDocumentError("方舟读取知识库文档列表失败") from exc

    def retrieve(
        self,
        query: str,
        documents: tuple[KnowledgeDocument, ...],
    ) -> str:
        if not documents:
            raise ValueError("必须提供知识库原文档")
        names_by_id: dict[str, str] = {}
        try:
            for document in documents:
                if (
                    Path(document.name).suffix.casefold() not in _SUPPORTED_FORMATS
                    or not document.doc_id.strip()
                ):
                    raise KnowledgeDocumentError(
                        f"不支持的知识库原文档《{document.name}》"
                    )
                names_by_id[document.doc_id] = document.name
            points = self._search(query, list(names_by_id), names_by_id)
            return self._render_evidence(points, names_by_id)
        except KnowledgeDocumentError:
            raise
        except Exception as exc:
            names = "、".join(document.name for document in documents)
            raise KnowledgeDocumentError(
                f"方舟读取知识库原文档失败：《{names}》"
            ) from exc

    def _search(
        self,
        query: str,
        doc_ids: list[str],
        names_by_id: dict[str, str],
    ) -> list[Any]:
        search_query = query.strip()[-8000:] or "请提取与当前顾问问题最相关的公司原文内容"
        result = self._knowledge_service.search_knowledge(
            collection_name=self._collection.collection_name,
            query=search_query,
            query_param={
                "doc_filter": {
                    "op": "must",
                    "field": "doc_id",
                    "conds": doc_ids,
                }
            },
            limit=min(200, 10 * len(doc_ids)),
            project=self._project,
            resource_id=self._resource_id,
        )
        points = result.get("result_list") or []
        if not points:
            names = "、".join(names_by_id[doc_id] for doc_id in doc_ids)
            raise KnowledgeDocumentError(
                f"方舟未能从知识库原文档检索到内容：《{names}》"
            )
        return points

    @staticmethod
    def _render_evidence(
        points: list[Any],
        names_by_id: dict[str, str],
    ) -> str:
        evidence: list[str] = []
        for point in points:
            content = (point.get("content") or "").strip()
            if not content:
                continue
            doc_info = point.get("doc_info") or {}
            document_name = doc_info.get("doc_name") or names_by_id.get(
                doc_info.get("doc_id"),
                "未知文档",
            )
            title = (point.get("chunk_title") or "").strip()
            source = f"《{document_name}》"
            if title:
                source += f"（{title}）"
            item = f"{source}\n{content}"
            if item not in evidence:
                evidence.append(item)
        if not evidence:
            raise KnowledgeDocumentError("方舟返回的知识库原文内容为空")
        return "\n\n".join(evidence)


_SUPPORTED_FORMATS = frozenset({".pdf", ".docx", ".pptx", ".xlsx"})
