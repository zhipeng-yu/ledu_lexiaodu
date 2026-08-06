from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from lexiaodu.knowledge import KnowledgeBase, KnowledgeType
from lexiaodu.knowledge_import import KnowledgeImportError, KnowledgeImportService
from lexiaodu.policy_upgrade import read_policy_sections


def _write_docx(path: Path, paragraphs: list[str]) -> None:
    body = "".join(
        f"<w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>"
        for paragraph in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_formal_knowledge(
    tmp_path: Path,
) -> tuple[KnowledgeImportService, Path, Path, dict[str, int]]:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    _write_docx(
        source_dir / "天津小学数学课程资料.docx",
        [
            "天津小学一年级数学课程内容包括数感启蒙和图形认知。",
            "天津小学二年级数学课程内容包括运算方法和问题解决。",
            "天津小学数学课程共十二讲。",
        ],
    )
    knowledge_dir = tmp_path / "knowledge"
    (knowledge_dir / "policy" / "旧结构").mkdir(parents=True)
    (knowledge_dir / "style_case").mkdir()
    old_policy = knowledge_dir / "policy" / "旧结构" / "小学数学.txt"
    old_policy.write_text("# 旧课程\n旧版课程结论。\n", encoding="utf-8")
    style_case = knowledge_dir / "style_case" / "表达风格.txt"
    style_case.write_text("# 温和表达\n请顾问温和说明。\n", encoding="utf-8")
    database = tmp_path / "knowledge.sqlite3"
    KnowledgeBase(knowledge_dir, database).rebuild()
    service = KnowledgeImportService(
        knowledge_dir, database, tmp_path / "staging"
    )
    prepared = service.prepare(source_dir)
    review = json.loads(prepared.review_path.read_text(encoding="utf-8"))
    decision = review["decisions"]["天津小学数学课程资料.docx"]
    raw = decision["raw"]
    raw.update(
        {
            "status": "approved",
            "audience": "advisor",
            "authority": "primary",
            "usage_status": "advisor",
        }
    )
    for record in decision["semantic"]["records"]:
        record["decision"] = "approved"
    decision["outputs"] = []
    prepared.review_path.write_text(
        json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    service.apply(prepared.batch_id)
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT id, grade FROM semantic_records "
            "WHERE record_status = 'approved' AND grade <> '' ORDER BY id"
        ).fetchall()
    ids = {str(grade): int(record_id) for record_id, grade in rows}
    assert {"一年级", "二年级"} <= ids.keys()
    return service, knowledge_dir, database, ids


def _approve_policy_drafts(
    prepared_path: Path,
    documents: dict[str, list[tuple[str, str, int]]],
) -> None:
    review = json.loads(prepared_path.read_text(encoding="utf-8"))
    batch_dir = prepared_path.parent
    reviewed_documents: list[dict[str, object]] = []
    draft_policy_dir = batch_dir / "draft" / "knowledge" / "policy"
    for existing in draft_policy_dir.rglob("*.txt"):
        existing.unlink()
    for relative_path, sections in documents.items():
        draft = batch_dir / "draft" / "knowledge" / relative_path
        draft.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"# {Path(relative_path).stem}", ""]
        for locator, text, _ in sections:
            lines.extend((f"### {locator}", text, ""))
        draft.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        parsed = {item["locator"]: item for item in read_policy_sections(draft)}
        reviewed_documents.append(
            {
                "path": relative_path,
                "file_sha256": _sha256(draft),
                "sections": [
                    {
                        "locator": locator,
                        "text_hash": parsed[locator]["text_hash"],
                        "decision": "approved",
                        "semantic_record_ids": [semantic_id],
                    }
                    for locator, _, semantic_id in sections
                ],
            }
        )
    review["policy_upgrade"]["status"] = "approved"
    review["policy_upgrade"]["documents"] = reviewed_documents
    prepared_path.write_text(
        json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def test_policy_upgrade_prepare_is_read_only_and_apply_switches_atomically(
    tmp_path: Path,
) -> None:
    service, knowledge_dir, database, ids = _seed_formal_knowledge(tmp_path)
    old_policy = knowledge_dir / "policy" / "旧结构" / "小学数学.txt"
    style_case = knowledge_dir / "style_case" / "表达风格.txt"
    old_text = old_policy.read_text(encoding="utf-8")
    style_text = style_case.read_text(encoding="utf-8")
    with sqlite3.connect(database) as connection:
        semantic_before = connection.execute(
            "SELECT COUNT(*) FROM semantic_records"
        ).fetchone()[0]
        source_before = connection.execute(
            "SELECT COUNT(*) FROM source_revisions WHERE status = 'approved'"
        ).fetchone()[0]

    prepared = service.prepare_policy_upgrade()

    assert old_policy.read_text(encoding="utf-8") == old_text
    assert style_case.read_text(encoding="utf-8") == style_text
    assert prepared.new_count == prepared.changed_count == 0
    batch = json.loads(
        (prepared.review_path.parent / "batch.json").read_text(encoding="utf-8")
    )
    assert batch["formal_semantic_count"] == semantic_before
    assert (prepared.review_path.parent / "evidence.json").is_file()
    incremental_draft = (
        prepared.review_path.parent
        / "draft"
        / "knowledge"
        / "policy"
        / "旧结构"
        / "小学数学.txt"
    )
    assert incremental_draft.read_text(encoding="utf-8") == old_text
    incremental_review = json.loads(prepared.review_path.read_text(encoding="utf-8"))
    assert incremental_review["policy_upgrade"]["documents"][0]["path"] == (
        "policy/旧结构/小学数学.txt"
    )
    _approve_policy_drafts(
        prepared.review_path,
        {
            "policy/学科年级课程/小学数学.txt": [
                (
                    "一年级数学｜数感与图形",
                    "适用天津。小学一年级数学课程包含数感启蒙和图形认知。",
                    ids["一年级"],
                ),
                (
                    "二年级数学｜运算与问题解决",
                    "天津小学二年级数学课程包含运算方法和问题解决。",
                    ids["二年级"],
                ),
            ]
        },
    )

    applied = service.apply(prepared.batch_id)

    assert applied.output_count == 1
    assert not old_policy.exists()
    assert (
        knowledge_dir / "policy" / "学科年级课程" / "小学数学.txt"
    ).is_file()
    assert style_case.read_text(encoding="utf-8") == style_text
    report = service.policy_report()
    assert report.document_count == 1
    assert report.section_count == report.linked_section_count == 2
    assert report.binding_rate == 1.0
    assert report.source_bound_section_count == 2
    assert report.source_binding_rate == 1.0
    assert report.retired_document_count == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM semantic_records"
        ).fetchone()[0] == semantic_before
        assert connection.execute(
            "SELECT COUNT(*) FROM source_revisions WHERE status = 'approved'"
        ).fetchone()[0] == source_before
        locators = {
            row[0]
            for row in connection.execute(
                "SELECT policy_locator FROM policy_semantic_links"
            )
        }
    assert locators == {
        "一年级数学｜数感与图形",
        "二年级数学｜运算与问题解决",
    }

    follow_up = service.prepare_policy_upgrade()
    _approve_policy_drafts(
        follow_up.review_path,
        {
            "policy/学科年级课程/小学数学.txt": [
                (
                    "一年级数学｜数感与图形",
                    "适用天津。小学一年级数学课程包含数感启蒙和图形认知。",
                    ids["一年级"],
                ),
                (
                    "二年级数学｜运算与问题解决",
                    "天津小学二年级数学课程包含运算方法和问题解决。",
                    ids["二年级"],
                ),
            ]
        },
    )
    service.apply(follow_up.batch_id)
    assert service.policy_report().retired_document_count == 1


def test_policy_upgrade_rejects_orphan_semantic_evidence(tmp_path: Path) -> None:
    service, _, _, ids = _seed_formal_knowledge(tmp_path)
    prepared = service.prepare_policy_upgrade()
    _approve_policy_drafts(
        prepared.review_path,
        {
            "policy/学科年级课程/小学数学.txt": [
                (
                    "一年级数学｜课程内容",
                    "天津小学一年级数学课程包含数感启蒙。",
                    ids["一年级"] + 999_999,
                )
            ]
        },
    )

    with pytest.raises(KnowledgeImportError, match="不存在的semantic"):
        service.apply(prepared.batch_id)


def test_policy_upgrade_failure_restores_files_database_and_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, knowledge_dir, database, ids = _seed_formal_knowledge(tmp_path)
    old_policy = knowledge_dir / "policy" / "旧结构" / "小学数学.txt"
    old_text = old_policy.read_text(encoding="utf-8")
    prepared = service.prepare_policy_upgrade()
    _approve_policy_drafts(
        prepared.review_path,
        {
            "policy/学科年级课程/小学数学.txt": [
                (
                    "一年级数学｜课程内容",
                    "天津小学一年级数学课程包含数感启蒙。",
                    ids["一年级"],
                )
            ]
        },
    )

    def fail_rebuild(
        self: KnowledgeBase, connection: sqlite3.Connection | None = None
    ) -> None:
        raise RuntimeError("injected policy index failure")

    monkeypatch.setattr(KnowledgeBase, "rebuild", fail_rebuild)
    with pytest.raises(RuntimeError, match="injected policy index failure"):
        service.apply(prepared.batch_id)

    assert old_policy.read_text(encoding="utf-8") == old_text
    assert not (
        knowledge_dir / "policy" / "学科年级课程" / "小学数学.txt"
    ).exists()
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT status FROM import_batches WHERE batch_id = ?",
            (prepared.batch_id,),
        ).fetchone()[0] == "prepared"
    assert KnowledgeBase(knowledge_dir, database).search(
        "旧版课程", KnowledgeType.POLICY
    )


def test_policy_semantic_filter_is_scoped_to_each_section(tmp_path: Path) -> None:
    service, knowledge_dir, database, ids = _seed_formal_knowledge(tmp_path)
    prepared = service.prepare_policy_upgrade()
    _approve_policy_drafts(
        prepared.review_path,
        {
            "policy/学科年级课程/小学数学.txt": [
                (
                    "一年级数学｜数感",
                    "天津小学一年级数学学习数感启蒙。",
                    ids["一年级"],
                ),
                (
                    "二年级数学｜运算",
                    "天津小学二年级数学学习运算方法。",
                    ids["二年级"],
                ),
            ]
        },
    )
    service.apply(prepared.batch_id)

    results = KnowledgeBase(knowledge_dir, database).search_advice_policy(
        "一年级数学学习什么"
    )
    curated = [result for result in results if result.source_tier == "curated"]

    assert curated
    assert {result.locator for result in curated} == {"一年级数学｜数感"}
    assert all("二年级" not in result.evidence for result in curated)
    assert KnowledgeBase(knowledge_dir, database).search_advice_policy(
        "上海课程能给天津孩子使用吗"
    ) == []
