from __future__ import annotations

from types import SimpleNamespace

import pytest

from lexiaodu.office_documents import ArkOfficeDocumentReader, OfficeDocumentError


class FakeTosClient:
    def __init__(self) -> None:
        self.uploads = []
        self.deleted = []

    def put_object(self, bucket, key, *, content, meta):
        self.uploads.append((bucket, key, content.read(), meta))

    def delete_object(self, bucket, key):
        self.deleted.append((bucket, key))


class FakeCollection:
    collection_name = "office-originals"
    project = "default"
    resource_id = "resource-1"

    def __init__(self, *, status=0) -> None:
        self.status = status
        self.added = []
        self.deleted = []

    def add_doc(self, **options):
        self.added.append(options)

    def get_doc(self, doc_id, **options):
        return SimpleNamespace(doc_id=doc_id, status=self.status)

    def delete_doc(self, doc_id, **options):
        self.deleted.append(doc_id)


class FakeKnowledgeService:
    def __init__(self, collection: FakeCollection, tos_client: FakeTosClient) -> None:
        self.collection = collection
        self.tos_client = tos_client
        self.search_options = []

    def search_knowledge(self, **options):
        self.search_options.append(options)
        selected = options["query_param"]["doc_filter"]["conds"][0]
        return {
            "result_list": [
                {
                    "content": f"方舟解析内容 {index}",
                    "chunk_title": f"章节 {index}",
                    "doc_info": {
                        "doc_id": upload[3]["doc_id"],
                        "doc_name": upload[1].split("/")[-1],
                    },
                }
                for index, upload in enumerate(self.tos_client.uploads, start=1)
                if upload[3]["doc_id"] == selected
            ]
        }


def test_reader_imports_searches_and_cleans_selected_office_files(tmp_path) -> None:
    documents = tuple(
        tmp_path / name
        for name in ("课程介绍.docx", "家长沟通.pptx", "价格表.xlsx")
    )
    for index, path in enumerate(documents, start=1):
        path.write_bytes(f"original-{index}".encode())
    tos_client = FakeTosClient()
    collection = FakeCollection()
    service = FakeKnowledgeService(collection, tos_client)
    reader = ArkOfficeDocumentReader(
        tos_client,
        service,
        collection,
        "private-bucket",
    )

    evidence = reader.retrieve("家长想了解课程和价格", documents)

    assert [item[2] for item in tos_client.uploads] == [
        b"original-1",
        b"original-2",
        b"original-3",
    ]
    doc_ids = [item[3]["doc_id"] for item in tos_client.uploads]
    assert [item["add_type"] for item in collection.added] == ["tos"] * 3
    assert [item["tos_path"] for item in collection.added] == [
        f"private-bucket/{item[1]}" for item in tos_client.uploads
    ]
    assert len(service.search_options) == 3
    assert [
        options["query_param"]["doc_filter"]["conds"]
        for options in service.search_options
    ] == [[doc_id] for doc_id in doc_ids]
    assert "《课程介绍.docx》" in evidence
    assert "《家长沟通.pptx》" in evidence
    assert "《价格表.xlsx》" in evidence
    assert "方舟解析内容 3" in evidence
    assert collection.deleted == doc_ids
    assert tos_client.deleted == [item[:2] for item in tos_client.uploads]


def test_reader_reports_ark_parse_failure_and_still_cleans(tmp_path) -> None:
    document = tmp_path / "损坏文档.docx"
    document.write_bytes(b"broken")
    tos_client = FakeTosClient()
    collection = FakeCollection(status=1)
    reader = ArkOfficeDocumentReader(
        tos_client,
        FakeKnowledgeService(collection, tos_client),
        collection,
        "private-bucket",
    )

    with pytest.raises(OfficeDocumentError, match="损坏文档.docx"):
        reader.retrieve("请读取", (document,))

    assert len(collection.deleted) == 1
    assert tos_client.deleted == [item[:2] for item in tos_client.uploads]


def test_reader_accepts_structured_ark_processing_status(tmp_path) -> None:
    document = tmp_path / "课程介绍.docx"
    document.write_bytes(b"original")
    tos_client = FakeTosClient()
    collection = FakeCollection(
        status={"process_status": 0, "failed_code": 0, "failed_msg": ""}
    )
    reader = ArkOfficeDocumentReader(
        tos_client,
        FakeKnowledgeService(collection, tos_client),
        collection,
        "private-bucket",
    )

    evidence = reader.retrieve("请概括课程", (document,))

    assert "《课程介绍.docx》" in evidence
    assert len(collection.deleted) == 1
    assert tos_client.deleted == [item[:2] for item in tos_client.uploads]
