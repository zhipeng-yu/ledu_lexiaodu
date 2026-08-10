from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any


class OfficeDocumentError(RuntimeError):
    pass


class ArkOfficeDocumentReader:
    def __init__(
        self,
        tos_client: Any,
        knowledge_service: Any,
        collection: Any,
        bucket: str,
    ) -> None:
        if not bucket.strip():
            raise ValueError("TOS 存储桶名称不能为空")
        self._tos_client = tos_client
        self._knowledge_service = knowledge_service
        self._collection = collection
        self._bucket = bucket.strip()
        self._project = collection.project or "default"
        self._resource_id = collection.resource_id

    def retrieve(
        self,
        query: str,
        documents: tuple[Path, ...],
    ) -> str:
        if not documents:
            raise ValueError("必须提供 Office 原文档")
        uploaded_keys: list[str] = []
        doc_ids: list[str] = []
        names_by_id: dict[str, str] = {}
        import_prefix = f"lexiaodu-office/{uuid.uuid4().hex}"
        try:
            for document in documents:
                path = Path(document)
                suffix = path.suffix.casefold()
                if suffix not in _OFFICE_FORMATS or not path.is_file():
                    raise OfficeDocumentError(f"无法读取 Office 原文档《{path.name}》")
                doc_id = f"office_{uuid.uuid4().hex}"
                object_key = f"{import_prefix}/{path.name}"
                with path.open("rb") as source:
                    self._tos_client.put_object(
                        self._bucket,
                        object_key,
                        content=source,
                        meta={"doc_id": doc_id},
                    )
                uploaded_keys.append(object_key)
                doc_ids.append(doc_id)
                names_by_id[doc_id] = path.name
                self._collection.add_doc(
                    add_type="tos",
                    tos_path=f"{self._bucket}/{object_key}",
                    project=self._project,
                    resource_id=self._resource_id,
                )

            deadline = time.monotonic() + _WAIT_SECONDS
            for doc_id in doc_ids:
                self._wait_until_parsed(doc_id, names_by_id[doc_id], deadline)
            points = self._search_until_available(query, doc_ids, deadline)
            return self._render_evidence(points, names_by_id)
        except OfficeDocumentError:
            raise
        except Exception as exc:
            names = "、".join(path.name for path in documents)
            raise OfficeDocumentError(f"方舟读取 Office 原文档失败：《{names}》") from exc
        finally:
            for doc_id in doc_ids:
                try:
                    self._collection.delete_doc(
                        doc_id,
                        project=self._project,
                        resource_id=self._resource_id,
                    )
                except Exception:
                    pass
            for object_key in uploaded_keys:
                try:
                    self._tos_client.delete_object(self._bucket, object_key)
                except Exception:
                    pass

    def _wait_until_parsed(
        self,
        doc_id: str,
        document_name: str,
        deadline: float,
    ) -> None:
        while True:
            status = self._collection.get_doc(
                doc_id,
                project=self._project,
                resource_id=self._resource_id,
            ).status
            if isinstance(status, dict):
                status = status.get("process_status")
            if status == 0:
                return
            if status in {1, 5}:
                raise OfficeDocumentError(
                    f"方舟未能解析 Office 原文档《{document_name}》"
                )
            if time.monotonic() >= deadline:
                raise OfficeDocumentError(
                    f"等待方舟解析 Office 原文档超时：《{document_name}》"
                )
            time.sleep(1)

    def _search_until_available(
        self,
        query: str,
        doc_ids: list[str],
        deadline: float,
    ) -> list[Any]:
        search_query = query.strip()[-8000:] or "请提取与当前顾问问题最相关的公司原文内容"
        all_points: list[Any] = []
        for doc_id in doc_ids:
            while True:
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
                if points:
                    all_points.extend(points)
                    break
                if time.monotonic() >= deadline:
                    raise OfficeDocumentError(
                        "方舟未能从所选 Office 原文档检索到内容"
                    )
                time.sleep(1)
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
_WAIT_SECONDS = 300
