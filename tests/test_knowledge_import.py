from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from lexiaodu.knowledge import KnowledgeType
from lexiaodu.knowledge_import import (
    KnowledgeImportError,
    KnowledgeImportService,
    _OcrCoordinator,
    canonicalize_url,
    classify_link,
    extract_source,
    suggested_outputs,
)
from lexiaodu.ocr import Speaker, TranscriptLine


def _write_docx(
    path: Path,
    paragraphs: list[str],
    hyperlinks: list[tuple[str, str, str]] | None = None,
) -> None:
    hyperlinks = hyperlinks or []
    relations = []
    hyperlink_xml: dict[str, str] = {}
    for index, (placeholder, display, target) in enumerate(hyperlinks, start=1):
        relation_id = f"rId{index}"
        relations.append(
            f'<Relationship Id="{relation_id}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
            f'Target="{target}" TargetMode="External"/>'
        )
        hyperlink_xml[placeholder] = (
            f'<w:hyperlink r:id="{relation_id}"><w:r><w:t>{display}</w:t>'
            "</w:r></w:hyperlink>"
        )
    body = []
    for paragraph in paragraphs:
        rendered = hyperlink_xml.get(
            paragraph, f"<w:r><w:t>{paragraph}</w:t></w:r>"
        )
        body.append(f"<w:p>{rendered}</w:p>")
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<w:body>{''.join(body)}</w:body></w:document>"
    )
    relationships_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{''.join(relations)}</Relationships>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
        archive.writestr(
            "word/_rels/document.xml.rels", relationships_xml
        )


def _write_xlsx(path: Path) -> None:
    workbook = """\
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheets><sheet name="课程表" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""
    workbook_rels = """\
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
    sheet = """\
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheetData>
  <row r="1"><c r="A1" t="inlineStr"><is><t>课程说明</t></is></c></row>
  <row r="2"><c r="A2"><f>HYPERLINK("https://example.com/sheets/plan","全年大纲")</f><v>全年大纲</v></c></row>
  <row r="3"><c r="A3" t="inlineStr"><is><t>查看批注</t></is></c></row>
 </sheetData>
 <hyperlinks><hyperlink ref="A1" r:id="rId1"/></hyperlinks>
</worksheet>"""
    sheet_rels = """\
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.com/docs/course/" TargetMode="External"/>
 <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="../comments1.xml"/>
</Relationships>"""
    comments = """\
<comments xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
 <authors><author>User</author></authors>
 <commentList><comment ref="A3" authorId="0"><text><t>附件 https://example.com/uploader/guide.pdf</t></text></comment></commentList>
</comments>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
        archive.writestr(
            "xl/worksheets/_rels/sheet1.xml.rels", sheet_rels
        )
        archive.writestr("xl/comments1.xml", comments)


def _write_text_pdf(path: Path, text: str) -> None:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(stream)).encode("ascii")
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, value in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{number} 0 obj\n".encode("ascii"))
        payload.extend(value)
        payload.extend(b"\nendobj\n")
    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    payload.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(payload)


def _knowledge_dirs(root: Path) -> None:
    (root / "policy").mkdir(parents=True)
    (root / "style_case").mkdir()


def test_url_normalization_and_link_classification() -> None:
    assert (
        canonicalize_url("https://EXAMPLE.com/docs/abc/?token=secret")
        == "https://example.com/docs/abc"
    )


def test_output_suggestions_derive_period_instead_of_hardcoding_year() -> None:
    assert suggested_outputs("2027秋初中数学产品说明.docx") == [
        "policy/产品知识/初中数学-2027秋.txt"
    ]
    assert suggested_outputs("27夏秋启蒙数学产品说明.docx") == [
        "policy/产品知识/启蒙数学-2027夏秋.txt"
    ]
    assert suggested_outputs("小学语文产品说明.docx") == [
        "policy/产品知识/小学语文-时期待确认.txt"
    ]
    assert classify_link("https://example.com/docs/abc") == "document"
    assert classify_link("https://example.com/sheets/abc") == "sheet"
    assert (
        classify_link("https://example.com/uploader/f/guide.pdf") == "pdf"
    )


def test_docx_extracts_paragraph_and_relationship_link(tmp_path: Path) -> None:
    document = tmp_path / "课程.docx"
    _write_docx(
        document,
        ["课程大纲"],
        [("课程大纲", "查看课程", "https://example.com/docs/course")],
    )

    extracted = extract_source(document, _OcrCoordinator(None, {}))

    assert any(block.text == "查看课程" for block in extracted.blocks)
    assert len(extracted.links) == 1
    assert extracted.links[0].target_type == "document"


def test_xlsx_extracts_cells_formulas_comments_and_links(tmp_path: Path) -> None:
    workbook = tmp_path / "课程.xlsx"
    _write_xlsx(workbook)

    extracted = extract_source(workbook, _OcrCoordinator(None, {}))

    text = "\n".join(block.text for block in extracted.blocks)
    assert "A1=课程说明" in text
    assert "HYPERLINK" in text
    assert "A3批注=附件" in text
    assert {link.target_type for link in extracted.links} == {
        "document",
        "sheet",
        "pdf",
    }


def test_text_pdf_extracts_page_text_and_plain_url(tmp_path: Path) -> None:
    document = tmp_path / "课程.pdf"
    _write_text_pdf(document, "Course https://example.com/docs/course")

    extracted = extract_source(document, _OcrCoordinator(None, {}))

    assert any(
        block.kind == "pdf_text" and "Course" in block.text
        for block in extracted.blocks
    )
    assert len(extracted.links) == 1
    assert extracted.links[0].target_type == "document"


def test_scanned_pdf_uses_document_ocr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pypdf import PdfWriter

    document = tmp_path / "扫描课程.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with document.open("wb") as stream:
        writer.write(stream)

    class FakeOcrEngine:
        def recognize_document(self, _image: object) -> list[TranscriptLine]:
            return [TranscriptLine(Speaker.PARENT, "扫描页课程内容")]

    monkeypatch.setattr(
        "lexiaodu.knowledge_import._render_pdf_page",
        lambda _path, _number: object(),
    )

    extracted = extract_source(
        document,
        _OcrCoordinator(FakeOcrEngine(), {}),  # type: ignore[arg-type]
    )

    assert any(
        block.kind == "pdf_ocr" and block.text == "扫描页课程内容"
        for block in extracted.blocks
    )


def test_prepare_requires_review_and_apply_resolves_link_target(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    _write_docx(
        source_dir / "资料目录.docx",
        ["linked"],
        [
            (
                "linked",
                "课程说明",
                "https://example.com/docs/course",
            )
        ],
    )
    # Put the exact title next to the hyperlink so the importer can suggest a
    # stable source alias without using fuzzy title matching.
    _write_docx(
        source_dir / "资料目录.docx",
        ["https://example.com/docs/course 《课程说明》"],
        [
            (
                "https://example.com/docs/course 《课程说明》",
                "https://example.com/docs/course 《课程说明》",
                "https://example.com/docs/course",
            )
        ],
    )
    _write_docx(source_dir / "课程说明.docx", ["课程每周一讲。"])
    knowledge_dir = tmp_path / "knowledge"
    _knowledge_dirs(knowledge_dir)
    service = KnowledgeImportService(
        knowledge_dir,
        tmp_path / "knowledge.sqlite3",
        tmp_path / "staging",
    )

    prepared = service.prepare(source_dir)

    assert prepared.new_count == 2
    assert prepared.link_report.occurrence_count == 1
    assert prepared.link_report.unique_target_count == 1
    assert prepared.link_report.missing_target_count == 1
    with pytest.raises(KnowledgeImportError, match="必须指定知识输出"):
        service.apply(prepared.batch_id)
    assert not (knowledge_dir / "policy" / "产品知识" / "课程.txt").exists()

    review = json.loads(prepared.review_path.read_text(encoding="utf-8"))
    directory_decision = review["decisions"]["资料目录.docx"]
    directory_decision["excluded_reason"] = "仅作为资料目录和引用来源"
    course_decision = review["decisions"]["课程说明.docx"]
    course_decision["outputs"] = ["policy/产品知识/课程.txt"]
    assert len(course_decision["alias_candidates"]) == 1
    course_decision["aliases"] = course_decision["alias_candidates"]
    prepared.review_path.write_text(
        json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    draft = (
        prepared.review_path.parent
        / "draft"
        / "knowledge"
        / "policy"
        / "产品知识"
        / "课程.txt"
    )
    draft.parent.mkdir(parents=True)
    draft.write_text("# 课程安排\n课程每周一讲。\n", encoding="utf-8")

    applied = service.apply(prepared.batch_id)

    assert applied.output_count == 1
    assert applied.link_report.ingested_target_count == 1
    assert applied.link_report.missing_target_count == 0
    assert (
        service.link_report().ingested_target_count == 1
    )
    applied_report = prepared.report_path.read_text(encoding="utf-8")
    assert "已入库资料：1" in applied_report
    assert "未入库资料：0" in applied_report
    assert "https://example.com/docs/course" not in applied_report

    prepared_again = service.prepare(source_dir)
    assert prepared_again.unchanged_count == 2
    assert prepared_again.new_count == 0


def test_prepare_reuses_existing_knowledge_as_incremental_draft(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    _write_docx(
        source_dir / "2027秋初中数学产品说明.docx",
        ["新增课程内容"],
    )
    knowledge_dir = tmp_path / "knowledge"
    _knowledge_dirs(knowledge_dir)
    existing = knowledge_dir / "policy/产品知识/初中数学-2027秋.txt"
    existing.parent.mkdir(parents=True)
    existing.write_text("# 初中数学\n已审核知识。\n", encoding="utf-8")
    service = KnowledgeImportService(
        knowledge_dir,
        tmp_path / "knowledge.sqlite3",
        tmp_path / "staging",
    )

    prepared = service.prepare(source_dir)

    draft = (
        prepared.review_path.parent
        / "draft/knowledge/policy/产品知识/初中数学-2027秋.txt"
    )
    assert draft.read_text(encoding="utf-8") == "# 初中数学\n已审核知识。\n"
    assert existing.read_text(encoding="utf-8") == "# 初中数学\n已审核知识。\n"


def test_apply_rejects_unreviewed_output_overwrite(tmp_path: Path) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    _write_docx(source_dir / "新资料.docx", ["新知识"])
    knowledge_dir = tmp_path / "knowledge"
    _knowledge_dirs(knowledge_dir)
    service = KnowledgeImportService(
        knowledge_dir,
        tmp_path / "knowledge.sqlite3",
        tmp_path / "staging",
    )
    prepared = service.prepare(source_dir)
    review = json.loads(prepared.review_path.read_text(encoding="utf-8"))
    review["decisions"]["新资料.docx"]["outputs"] = [
        "policy/产品知识/新资料.txt"
    ]
    prepared.review_path.write_text(
        json.dumps(review, ensure_ascii=False), encoding="utf-8"
    )
    draft = (
        prepared.review_path.parent
        / "draft/knowledge/policy/产品知识/新资料.txt"
    )
    draft.parent.mkdir(parents=True)
    draft.write_text("# 新资料\n新知识\n", encoding="utf-8")
    target = knowledge_dir / "policy/产品知识/新资料.txt"
    target.parent.mkdir(parents=True)
    target.write_text("用户刚刚写入的内容", encoding="utf-8")

    with pytest.raises(KnowledgeImportError, match="拒绝覆盖"):
        service.apply(prepared.batch_id)

    assert target.read_text(encoding="utf-8") == "用户刚刚写入的内容"


def test_resume_reuses_atomic_extracted_file_and_checkpoints_each_source(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    _write_docx(source_dir / "已完成.docx", ["第一份知识"])
    _write_docx(source_dir / "待继续.docx", ["第二份知识"])
    knowledge_dir = tmp_path / "knowledge"
    _knowledge_dirs(knowledge_dir)
    staging_dir = tmp_path / "staging"
    batch_dir = staging_dir / "paused-batch"
    extracted_dir = batch_dir / "extracted"
    extracted_dir.mkdir(parents=True)
    preserved = extracted_dir / "已完成.docx.txt"
    preserved.write_text("# 已完成\n已保存的 OCR 结果\n", encoding="utf-8")
    service = KnowledgeImportService(
        knowledge_dir,
        tmp_path / "knowledge.sqlite3",
        staging_dir,
    )

    report = service.resume("paused-batch", source_dir)

    assert report.new_count == 2
    assert preserved.read_text(encoding="utf-8") == "# 已完成\n已保存的 OCR 结果\n"
    progress = json.loads(
        (batch_dir / "progress.json").read_text(encoding="utf-8")
    )
    assert progress["status"] == "prepared"
    assert all(
        value["db_checkpoint"] for value in progress["files"].values()
    )


def test_resume_keeps_unapproved_staged_source_in_review(tmp_path: Path) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    _write_docx(source_dir / "待审核.docx", ["尚未批准的知识"])
    knowledge_dir = tmp_path / "knowledge"
    _knowledge_dirs(knowledge_dir)
    staging_dir = tmp_path / "staging"
    service = KnowledgeImportService(
        knowledge_dir,
        tmp_path / "knowledge.sqlite3",
        staging_dir,
    )
    first = service.prepare(source_dir)
    progress_path = first.review_path.parent / "progress.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    progress["files"]["待审核.docx"]["change"] = "unchanged"
    progress["files"]["待审核.docx"]["db_checkpoint"] = False
    progress_path.write_text(
        json.dumps(progress, ensure_ascii=False), encoding="utf-8"
    )

    resumed = service.resume(first.batch_id, source_dir)
    review = json.loads(resumed.review_path.read_text(encoding="utf-8"))

    assert resumed.new_count == 1
    assert "待审核.docx" in review["decisions"]
