from __future__ import annotations

from pathlib import Path
from typing import Any


class OfficeDocumentError(RuntimeError):
    pass


class ArkOfficeDocumentReader:
    def __init__(
        self,
        knowledge_service: Any,
        collection: Any,
    ) -> None:
        self._knowledge_service = knowledge_service
        self._collection = collection
        self._project = collection.project or "default"
        self._resource_id = collection.resource_id

    def retrieve(
        self,
        query: str,
        documents: tuple[Path, ...],
    ) -> str:
        if not documents:
            raise ValueError("必须提供 Office 原文档")
        doc_ids: list[str] = []
        names_by_id: dict[str, str] = {}
        try:
            cloud_documents = {
                item.doc_name: item
                for item in self._collection.list_docs(project=self._project)
            }
            for document in documents:
                path = Path(document)
                suffix = path.suffix.casefold()
                if suffix not in _OFFICE_FORMATS or not path.is_file():
                    raise OfficeDocumentError(f"无法读取 Office 原文档《{path.name}》")
                cloud_document = cloud_documents.get(path.name)
                if cloud_document is None:
                    raise OfficeDocumentError(
                        f"方舟知识库中未找到同名 Office 原文档《{path.name}》"
                    )
                status = cloud_document.status
                if isinstance(status, dict):
                    status = status.get("process_status")
                if status != 0:
                    state = "解析失败" if status in {1, 5} else "尚未解析完成"
                    raise OfficeDocumentError(
                        f"方舟知识库中的 Office 原文档{state}：《{path.name}》"
                    )
                doc_id = cloud_document.doc_id
                doc_ids.append(doc_id)
                names_by_id[doc_id] = path.name
            points = self._search(query, doc_ids, names_by_id)
            return self._render_evidence(points, names_by_id)
        except OfficeDocumentError:
            raise
        except Exception as exc:
            names = "、".join(path.name for path in documents)
            raise OfficeDocumentError(f"方舟读取 Office 原文档失败：《{names}》") from exc

    def _search(
        self,
        query: str,
        doc_ids: list[str],
        names_by_id: dict[str, str],
    ) -> list[Any]:
        search_query = query.strip()[-8000:] or "请提取与当前顾问问题最相关的公司原文内容"
        all_points: list[Any] = []
        for doc_id in doc_ids:
            result = self._knowledge_service.search_knowledge(
                collection_name=self._collection.collection_name,
                query=search_query,
                query_param={
                    "doc_filter": {
                        "op": "must",
                        "field": "doc_id",
                        "conds": [doc_id],
                    }
                },
                limit=10,
                project=self._project,
                resource_id=self._resource_id,
            )
            points = result.get("result_list") or []
            if not points:
                raise OfficeDocumentError(
                    "方舟未能从 Office 原文档检索到内容："
                    f"《{names_by_id[doc_id]}》"
                )
            all_points.extend(points)
        return all_points

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
            raise OfficeDocumentError("方舟返回的 Office 原文内容为空")
        return "\n\n".join(evidence)


_OFFICE_FORMATS = frozenset({".docx", ".pptx", ".xlsx"})
