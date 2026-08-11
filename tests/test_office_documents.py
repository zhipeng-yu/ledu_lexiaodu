from __future__ import annotations

from types import SimpleNamespace

import pytest

from lexiaodu.office_documents import (
    ArkKnowledgeDocumentReader,
    KnowledgeDocument,
    KnowledgeDocumentError,
)


class FakeCollection:
    collection_name = "company-originals"
    project = "default"
    resource_id = "resource-1"

    def __init__(self, documents) -> None:
        self.documents = documents
        self.list_calls = []

    def list_docs(self, **options):
        self.list_calls.append(options)
        return self.documents


class FakeKnowledgeService:
    def __init__(self, *, empty_doc_ids=()) -> None:
        self.empty_doc_ids = set(empty_doc_ids)
        self.search_options = []

    def search_knowledge(self, **options):
        self.search_options.append(options)
        doc_ids = options["query_param"]["doc_filter"]["conds"]
        return {
            "result_list": [
                {
                    "content": f"Ark content {doc_id}",
                    "chunk_title": "Key section",
                    "doc_info": {"doc_id": doc_id},
                }
                for doc_id in doc_ids
                if doc_id not in self.empty_doc_ids
            ]
        }


def test_reader_lists_ready_supported_cloud_documents_without_local_files() -> None:
    collection = FakeCollection(
        [
            SimpleNamespace(doc_id="doc-pdf", doc_name="course.pdf", status=0),
            SimpleNamespace(
                doc_id="doc-docx",
                doc_name="guide.docx",
                status={"process_status": 0},
            ),
            SimpleNamespace(doc_id="doc-pptx", doc_name="slides.PPTX", status=0),
            SimpleNamespace(doc_id="doc-xlsx", doc_name="prices.xlsx", status=0),
            SimpleNamespace(doc_id="doc-txt", doc_name="notes.txt", status=0),
            SimpleNamespace(
                doc_id="doc-pending",
                doc_name="pending.pdf",
                status={"process_status": 2},
            ),
        ]
    )
    reader = ArkKnowledgeDocumentReader(FakeKnowledgeService(), collection)

    documents = reader.list_documents()

    assert documents == (
        KnowledgeDocument("doc-pdf", "course.pdf"),
        KnowledgeDocument("doc-docx", "guide.docx"),
        KnowledgeDocument("doc-xlsx", "prices.xlsx"),
        KnowledgeDocument("doc-pptx", "slides.PPTX"),
    )
    assert collection.list_calls == [{"project": "default"}]


def test_reader_retrieves_pdf_and_office_documents_by_cloud_id() -> None:
    collection = FakeCollection([])
    service = FakeKnowledgeService()
    reader = ArkKnowledgeDocumentReader(service, collection)
    documents = (
        KnowledgeDocument("doc-pdf", "course.pdf"),
        KnowledgeDocument("doc-docx", "guide.docx"),
        KnowledgeDocument("doc-pptx", "slides.pptx"),
        KnowledgeDocument("doc-xlsx", "prices.xlsx"),
    )

    evidence = reader.retrieve("course and prices", documents)

    assert collection.list_calls == []
    assert len(service.search_options) == 1
    assert service.search_options[0]["query_param"]["doc_filter"]["conds"] == [
        "doc-pdf",
        "doc-docx",
        "doc-pptx",
        "doc-xlsx",
    ]
    assert service.search_options[0]["limit"] == 40
    assert all(
        options["collection_name"] == "company-originals"
        and options["project"] == "default"
        and options["resource_id"] == "resource-1"
        for options in service.search_options
    )
    assert "course.pdf" in evidence
    assert "guide.docx" in evidence
    assert "slides.pptx" in evidence
    assert "prices.xlsx" in evidence
    assert "Ark content doc-xlsx" in evidence


def test_reader_rejects_unsupported_selected_cloud_document() -> None:
    reader = ArkKnowledgeDocumentReader(FakeKnowledgeService(), FakeCollection([]))

    with pytest.raises(KnowledgeDocumentError, match="notes.txt"):
        reader.retrieve("read it", (KnowledgeDocument("doc-txt", "notes.txt"),))


def test_reader_reports_selected_cloud_document_without_search_results() -> None:
    reader = ArkKnowledgeDocumentReader(
        FakeKnowledgeService(empty_doc_ids={"doc-empty"}),
        FakeCollection([]),
    )

    with pytest.raises(KnowledgeDocumentError, match="empty.pdf"):
        reader.retrieve("read it", (KnowledgeDocument("doc-empty", "empty.pdf"),))
