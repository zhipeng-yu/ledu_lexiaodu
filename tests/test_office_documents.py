from __future__ import annotations

from types import SimpleNamespace

import pytest
from lexiaodu.office_documents import ArkOfficeDocumentReader, OfficeDocumentError


class FakeCollection:
    collection_name = "office-originals"
    project = "default"
    resource_id = "resource-1"

    def __init__(self, documents) -> None:
        self.documents = documents
        self.list_calls = []

    def list_docs(self, **options):
        self.list_calls.append(options)
        return self.documents


class FakeKnowledgeService:
    def __init__(self) -> None:
        self.search_options = []

    def search_knowledge(self, **options):
        self.search_options.append(options)
        doc_id = options["query_param"]["doc_filter"]["conds"][0]
        return {
            "result_list": [
                {
                    "content": f"Ark content {doc_id}",
                    "chunk_title": "Key section",
                    "doc_info": {"doc_id": doc_id},
                }
            ]
        }


def test_reader_retrieves_manually_imported_office_files(tmp_path) -> None:
    local_documents = tuple(
        tmp_path / name
        for name in ("course.docx", "parents.pptx", "prices.xlsx")
    )
    for path in local_documents:
        path.touch()
    cloud_documents = [
        SimpleNamespace(doc_id=f"doc-{index}", doc_name=path.name, status=0)
        for index, path in enumerate(local_documents, start=1)
    ]
    collection = FakeCollection(cloud_documents)
    service = FakeKnowledgeService()
    reader = ArkOfficeDocumentReader(service, collection)

    evidence = reader.retrieve("course and prices", local_documents)

    assert collection.list_calls == [{"project": "default"}]
    assert [
        options["query_param"]["doc_filter"]["conds"]
        for options in service.search_options
    ] == [["doc-1"], ["doc-2"], ["doc-3"]]
    assert "course.docx" in evidence
    assert "parents.pptx" in evidence
    assert "prices.xlsx" in evidence
    assert "Ark content doc-3" in evidence


def test_reader_reports_file_missing_from_cloud_knowledge_base(tmp_path) -> None:
    document = tmp_path / "not-uploaded.docx"
    document.touch()
    reader = ArkOfficeDocumentReader(
        FakeKnowledgeService(),
        FakeCollection([]),
    )

    with pytest.raises(OfficeDocumentError, match="not-uploaded.docx"):
        reader.retrieve("read it", (document,))


def test_reader_reports_cloud_document_not_ready(tmp_path) -> None:
    document = tmp_path / "processing.xlsx"
    document.touch()
    cloud_document = SimpleNamespace(
        doc_id="doc-processing",
        doc_name=document.name,
        status={"process_status": 2, "failed_code": 0, "failed_msg": ""},
    )
    reader = ArkOfficeDocumentReader(
        FakeKnowledgeService(),
        FakeCollection([cloud_document]),
    )

    with pytest.raises(OfficeDocumentError, match="processing.xlsx"):
        reader.retrieve("read it", (document,))
