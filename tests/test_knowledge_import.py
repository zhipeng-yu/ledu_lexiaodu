from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from PySide6.QtGui import QImage

from lexiaodu.advice import AdviceService
from lexiaodu.generator import SimulatedGenerator
from lexiaodu.knowledge import KnowledgeBase, KnowledgeType
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


def _write_pptx(path: Path, image: bytes) -> None:
    slide = """\
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
 <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>课程讲次安排</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>
</p:sld>"""
    notes = """\
<p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
 <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>顾问备注内容</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>
</p:notes>"""
    rels = """\
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.com/docs/slides" TargetMode="External"/>
</Relationships>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", slide)
        archive.writestr("ppt/slides/_rels/slide1.xml.rels", rels)
        archive.writestr("ppt/notesSlides/notesSlide1.xml", notes)
        archive.writestr("ppt/media/image1.png", image)


def _knowledge_dirs(root: Path) -> None:
    (root / "policy").mkdir(parents=True)
    (root / "style_case").mkdir()


def _approve_raw(
    decision: dict[str, object], *, audience: str = "advisor"
) -> None:
    raw = decision["raw"]
    assert isinstance(raw, dict)
    raw.update(
        {
            "status": "approved",
            "audience": audience,
            "authority": "primary",
            "usage_status": audience,
        }
    )
    semantic = decision.get("semantic")
    if isinstance(semantic, dict):
        records = semantic.get("records", [])
        assert isinstance(records, list)
        for record in records:
            assert isinstance(record, dict)
            record["decision"] = "approved"


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


def test_pptx_and_standalone_image_extract_text_links_and_ocr(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "课程图.png"
    image = QImage(120, 80, QImage.Format.Format_RGB32)
    image.fill(0xFFFFFF)
    assert image.save(str(image_path), "PNG")
    presentation = tmp_path / "课程.pptx"
    _write_pptx(presentation, image_path.read_bytes())

    class FakeOcrEngine:
        def recognize_document(self, _image: object) -> list[TranscriptLine]:
            return [
                TranscriptLine(
                    Speaker.PARENT,
                    "图片中的课程信息",
                    confidence=0.98,
                )
            ]

    coordinator = _OcrCoordinator(FakeOcrEngine(), {})  # type: ignore[arg-type]
    extracted_pptx = extract_source(presentation, coordinator)
    extracted_image = extract_source(image_path, coordinator)

    pptx_text = "\n".join(block.text for block in extracted_pptx.blocks)
    assert "课程讲次安排" in pptx_text
    assert "顾问备注内容" in pptx_text
    assert "图片中的课程信息" in pptx_text
    assert extracted_pptx.links[0].target_type == "document"
    assert extracted_image.blocks[0].kind == "image_ocr"
    assert extracted_image.blocks[0].confidence == pytest.approx(0.98)


def test_docx_extracts_header_and_accounts_for_every_media_object(
    tmp_path: Path,
) -> None:
    document = tmp_path / "完整课程.docx"
    _write_docx(document, ["正文课程内容"])
    image_path = tmp_path / "embedded.png"
    image = QImage(120, 80, QImage.Format.Format_RGB32)
    image.fill(0xFFFFFF)
    assert image.save(str(image_path), "PNG")
    header = (
        '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:p><w:r><w:t>页眉课程版本</w:t></w:r></w:p></w:hdr>"
    )
    with zipfile.ZipFile(document, "a") as archive:
        archive.writestr("word/header1.xml", header)
        archive.writestr("word/media/image1.png", image_path.read_bytes())
        archive.writestr("word/media/image2.png", image_path.read_bytes())

    class FakeOcrEngine:
        def recognize_document(self, _image: object) -> list[TranscriptLine]:
            return [TranscriptLine(Speaker.PARENT, "图片课程表", confidence=0.99)]

    extracted = extract_source(
        document,
        _OcrCoordinator(FakeOcrEngine(), {}),  # type: ignore[arg-type]
    )

    assert any(block.kind == "header" and "页眉课程版本" in block.text for block in extracted.blocks)
    image_blocks = [
        block
        for block in extracted.blocks
        if block.kind in {"image_ocr", "image_no_text"}
    ]
    assert len(image_blocks) == 2
    assert all("图片课程表" in block.text for block in image_blocks)


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
    with pytest.raises(KnowledgeImportError, match="尚未完成原文审核"):
        service.apply(prepared.batch_id)
    assert not (knowledge_dir / "policy" / "产品知识" / "课程.txt").exists()

    review = json.loads(prepared.review_path.read_text(encoding="utf-8"))
    directory_decision = review["decisions"]["资料目录.docx"]
    assert directory_decision["raw"]["block_candidates"]
    assert all(
        candidate["block_key"]
        for candidate in directory_decision["raw"]["block_candidates"]
    )
    directory_decision["excluded_reason"] = "仅作为资料目录和引用来源"
    _approve_raw(directory_decision, audience="internal")
    course_decision = review["decisions"]["课程说明.docx"]
    _approve_raw(course_decision)
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
    with sqlite3.connect(tmp_path / "knowledge.sqlite3") as connection:
        indexed_text = "\n".join(
            row[0] for row in connection.execute("SELECT text FROM source_chunks")
        )
    assert "https://example.com/docs/course" not in indexed_text

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


def test_approved_raw_source_is_searchable_and_internal_operations_are_discarded(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    _write_docx(source_dir / "课程资料.docx", ["星河班每周六上午上课。"])
    _write_docx(source_dir / "内部资料.docx", ["内部续报率目标为百分之八十。"])
    knowledge_dir = tmp_path / "knowledge"
    _knowledge_dirs(knowledge_dir)
    database = tmp_path / "knowledge.sqlite3"
    service = KnowledgeImportService(
        knowledge_dir, database, tmp_path / "staging"
    )
    prepared = service.prepare(source_dir)
    review = json.loads(prepared.review_path.read_text(encoding="utf-8"))
    _approve_raw(review["decisions"]["课程资料.docx"])
    _approve_raw(
        review["decisions"]["内部资料.docx"], audience="internal"
    )
    prepared.review_path.write_text(
        json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    service.apply(prepared.batch_id)
    knowledge = KnowledgeBase(knowledge_dir, database)

    public = knowledge.search("星河班周六", KnowledgeType.SOURCE)
    assert public and public[0].source_tier == "approved_source"
    assert "每周六上午" in public[0].evidence
    assert knowledge.search("续报率目标", KnowledgeType.SOURCE) == []
    internal = knowledge.search(
        "续报率目标",
        KnowledgeType.SOURCE,
        include_internal=True,
    )
    assert internal == []
    assert service.coverage_report().discarded_block_count == 1
    suggestion = AdviceService(
        knowledge, SimulatedGenerator()
    ).create("星河班周六什么时候上课？")
    assert any(
        fact.source_tier == "approved_source"
        for fact in suggestion.facts
    )
    assert "每周六上午" in suggestion.wechat_reply
    coverage = service.coverage_report()
    assert coverage.searchable_char_count >= len("星河班每周六上午上课。")
    assert coverage.advisor_block_count == 1
    assert coverage.internal_block_count == 0
    assert not (prepared.review_path.parent / "extracted").exists()
    assert not (prepared.review_path.parent / "draft").exists()


def test_source_search_prefers_matching_subject_document_name(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    _write_docx(source_dir / "初中数学课程.docx", ["课程讲次为十二讲。"])
    _write_docx(source_dir / "小学数学课程.docx", ["课程讲次为十四讲。"])
    knowledge_dir = tmp_path / "knowledge"
    _knowledge_dirs(knowledge_dir)
    database = tmp_path / "knowledge.sqlite3"
    service = KnowledgeImportService(
        knowledge_dir, database, tmp_path / "staging"
    )
    prepared = service.prepare(source_dir)
    review = json.loads(prepared.review_path.read_text(encoding="utf-8"))
    for decision in review["decisions"].values():
        _approve_raw(decision)
    prepared.review_path.write_text(
        json.dumps(review, ensure_ascii=False), encoding="utf-8"
    )
    service.apply(prepared.batch_id)

    results = KnowledgeBase(knowledge_dir, database).search(
        "初中数学 课程讲次", KnowledgeType.SOURCE
    )

    assert results[0].document_name == "初中数学课程.docx"


def test_prepare_excludes_advisor_chat_folder_and_reports_legacy_formats(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    _write_docx(source_dir / "课程资料.docx", ["课程信息"])
    chat_dir = source_dir / "顾问聊天记录"
    chat_dir.mkdir()
    (chat_dir / "聊天.png").write_bytes(b"not-an-import-source")
    (source_dir / "旧资料.xls").write_bytes(b"legacy")
    knowledge_dir = tmp_path / "knowledge"
    _knowledge_dirs(knowledge_dir)
    service = KnowledgeImportService(
        knowledge_dir,
        tmp_path / "knowledge.sqlite3",
        tmp_path / "staging",
    )

    prepared = service.prepare(source_dir)
    review = json.loads(prepared.review_path.read_text(encoding="utf-8"))
    report = prepared.report_path.read_text(encoding="utf-8")

    assert prepared.new_count == 1
    assert set(review["decisions"]) == {"课程资料.docx"}
    assert prepared.excluded_count == 1
    assert "顾问聊天记录/聊天.png" in report
    assert "配置排除：顾问聊天记录不得作为产品事实导入" in report
    assert "旧资料.xls" in report


def test_low_confidence_image_text_is_persisted_but_blocked_from_advice(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    image_path = source_dir / "低可信课程图.png"
    image = QImage(120, 80, QImage.Format.Format_RGB32)
    image.fill(0xFFFFFF)
    assert image.save(str(image_path), "PNG")

    class LowConfidenceOcr:
        def recognize_document(self, _image: object) -> list[TranscriptLine]:
            return [
                TranscriptLine(
                    Speaker.PARENT,
                    "可能识别错误的课程价格",
                    confidence=0.55,
                )
            ]

    knowledge_dir = tmp_path / "knowledge"
    _knowledge_dirs(knowledge_dir)
    database = tmp_path / "knowledge.sqlite3"
    service = KnowledgeImportService(
        knowledge_dir,
        database,
        tmp_path / "staging",
        LowConfidenceOcr(),  # type: ignore[arg-type]
    )
    prepared = service.prepare(source_dir)
    review = json.loads(prepared.review_path.read_text(encoding="utf-8"))
    _approve_raw(review["decisions"]["低可信课程图.png"])
    prepared.review_path.write_text(
        json.dumps(review, ensure_ascii=False), encoding="utf-8"
    )

    service.apply(prepared.batch_id)

    assert KnowledgeBase(knowledge_dir, database).search(
        "课程价格", KnowledgeType.SOURCE
    ) == []
    coverage = service.coverage_report()
    assert coverage.text_char_count >= len("可能识别错误的课程价格")
    assert coverage.blocked_block_count == 1


def test_review_marked_conflict_is_blocked_from_source_search(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    _write_docx(source_dir / "待核对课程.docx", ["课程共十二讲，数字待核对。"])
    knowledge_dir = tmp_path / "knowledge"
    _knowledge_dirs(knowledge_dir)
    database = tmp_path / "knowledge.sqlite3"
    service = KnowledgeImportService(
        knowledge_dir, database, tmp_path / "staging"
    )
    prepared = service.prepare(source_dir)
    review = json.loads(prepared.review_path.read_text(encoding="utf-8"))
    decision = review["decisions"]["待核对课程.docx"]
    _approve_raw(decision)
    block_key = decision["raw"]["block_candidates"][0]["block_key"]
    decision["raw"]["block_overrides"][block_key] = {
        "quality_status": "blocked"
    }
    prepared.review_path.write_text(
        json.dumps(review, ensure_ascii=False), encoding="utf-8"
    )

    service.apply(prepared.batch_id)

    assert KnowledgeBase(knowledge_dir, database).search(
        "十二讲", KnowledgeType.SOURCE
    ) == []
    assert service.coverage_report().blocked_block_count == 1
    report = prepared.report_path.read_text(encoding="utf-8")
    assert "[blocked] 待核对课程.docx" in report
    assert "课程共十二讲" in report


def test_source_version_switch_is_atomic_and_missing_file_keeps_last_approval(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    source = source_dir / "课程版本.docx"
    _write_docx(source, ["旧版课程每周一讲。"])
    knowledge_dir = tmp_path / "knowledge"
    _knowledge_dirs(knowledge_dir)
    database = tmp_path / "knowledge.sqlite3"
    service = KnowledgeImportService(
        knowledge_dir, database, tmp_path / "staging"
    )

    first = service.prepare(source_dir)
    first_review = json.loads(first.review_path.read_text(encoding="utf-8"))
    _approve_raw(first_review["decisions"]["课程版本.docx"])
    first.review_path.write_text(
        json.dumps(first_review, ensure_ascii=False), encoding="utf-8"
    )
    service.apply(first.batch_id)
    assert KnowledgeBase(knowledge_dir, database).search(
        "旧版课程", KnowledgeType.SOURCE
    )

    _write_docx(source, ["新版课程每周两讲。"])
    second = service.prepare(source_dir)
    knowledge = KnowledgeBase(knowledge_dir, database)
    assert knowledge.search("旧版课程", KnowledgeType.SOURCE)
    assert not any(
        "新版课程" in result.evidence
        for result in knowledge.search("新版课程", KnowledgeType.SOURCE)
    )
    second_review = json.loads(second.review_path.read_text(encoding="utf-8"))
    _approve_raw(second_review["decisions"]["课程版本.docx"])
    second.review_path.write_text(
        json.dumps(second_review, ensure_ascii=False), encoding="utf-8"
    )
    service.apply(second.batch_id)
    assert knowledge.search("新版课程", KnowledgeType.SOURCE)
    assert not any(
        "旧版课程" in result.evidence
        for result in knowledge.search("旧版课程", KnowledgeType.SOURCE)
    )

    source.unlink()
    missing = service.prepare(source_dir)
    assert missing.missing_source_count == 1
    assert knowledge.search("新版课程", KnowledgeType.SOURCE)


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
    _approve_raw(review["decisions"]["新资料.docx"])
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


def test_semantic_candidates_require_explicit_review_and_source_binding(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    _write_docx(source_dir / "一年级数学课程.docx", ["一年级数学课程共十二讲。"])
    knowledge_dir = tmp_path / "knowledge"
    _knowledge_dirs(knowledge_dir)
    service = KnowledgeImportService(
        knowledge_dir, tmp_path / "knowledge.sqlite3", tmp_path / "staging"
    )
    prepared = service.prepare(source_dir)
    review = json.loads(prepared.review_path.read_text(encoding="utf-8"))
    decision = review["decisions"]["一年级数学课程.docx"]
    raw = decision["raw"]
    raw.update(
        {
            "status": "approved",
            "audience": "advisor",
            "authority": "primary",
            "usage_status": "advisor",
        }
    )
    prepared.review_path.write_text(
        json.dumps(review, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(KnowledgeImportError, match="语义候选尚未完成审核"):
        service.apply(prepared.batch_id)

    _approve_raw(decision)
    semantic_records = decision["semantic"]["records"]
    assert semantic_records
    semantic_records[0]["source_block_id"] += 999
    prepared.review_path.write_text(
        json.dumps(review, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(KnowledgeImportError, match="来源块绑定无效"):
        service.apply(prepared.batch_id)


def test_schema_upgrade_adds_block_disposition_and_semantic_tables(
    tmp_path: Path,
) -> None:
    database = tmp_path / "knowledge.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE source_blocks (
                id INTEGER PRIMARY KEY,
                revision_id INTEGER NOT NULL,
                block_index INTEGER NOT NULL,
                block_key TEXT NOT NULL,
                locator TEXT NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                audience TEXT NOT NULL DEFAULT 'pending',
                quality_status TEXT NOT NULL DEFAULT 'pending',
                authority TEXT NOT NULL DEFAULT 'reference',
                confidence REAL,
                warning TEXT NOT NULL DEFAULT ''
            )
            """
        )
    service = KnowledgeImportService(
        tmp_path / "knowledge", database, tmp_path / "staging"
    )

    report = service.semantic_report()

    assert report.binding_rate == 1.0
    with sqlite3.connect(database) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(source_blocks)")
        }
        assert {"usage_status", "discard_reason"} <= columns
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'semantic_records'"
        ).fetchone()

def test_semantic_filters_keep_grades_separate(tmp_path: Path) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    _write_docx(source_dir / "一年级数学课程.docx", ["一年级数学课程共十二讲。"])
    _write_docx(source_dir / "二年级数学课程.docx", ["二年级数学课程共十四讲。"])
    knowledge_dir = tmp_path / "knowledge"
    _knowledge_dirs(knowledge_dir)
    database = tmp_path / "knowledge.sqlite3"
    service = KnowledgeImportService(
        knowledge_dir, database, tmp_path / "staging"
    )
    prepared = service.prepare(source_dir)
    review = json.loads(prepared.review_path.read_text(encoding="utf-8"))
    for decision in review["decisions"].values():
        _approve_raw(decision)
    prepared.review_path.write_text(
        json.dumps(review, ensure_ascii=False), encoding="utf-8"
    )
    service.apply(prepared.batch_id)

    results = KnowledgeBase(knowledge_dir, database).search_advice_policy(
        "一年级数学一共多少讲"
    )
    assert any("十二讲" in result.evidence for result in results)
    assert all("十四讲" not in result.evidence for result in results)
    semantic = service.semantic_report()
    assert semantic.record_count > 0
    assert semantic.binding_rate == 1.0


def test_national_course_query_requires_tianjin_compatible_evidence(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    _write_docx(
        source_dir / "天津普通课程.docx",
        ["天津一年级数学课程可以报名。"],
    )
    knowledge_dir = tmp_path / "knowledge"
    _knowledge_dirs(knowledge_dir)
    database = tmp_path / "knowledge.sqlite3"
    service = KnowledgeImportService(
        knowledge_dir, database, tmp_path / "staging"
    )
    prepared = service.prepare(source_dir)
    review = json.loads(prepared.review_path.read_text(encoding="utf-8"))
    for decision in review["decisions"].values():
        _approve_raw(decision)
    prepared.review_path.write_text(
        json.dumps(review, ensure_ascii=False), encoding="utf-8"
    )
    service.apply(prepared.batch_id)

    knowledge = KnowledgeBase(knowledge_dir, database)
    assert knowledge.search_advice_policy(
        "全国班的课程天津孩子能不能报名和使用"
    ) == []
    assert knowledge.search_advice_policy(
        "这个项目的内部续报目标、负责人和排期是什么"
    ) == []
    assert knowledge.search_advice_policy(
        "报名后 App 为什么没有课程，订单付款成功了吗"
    ) == []


def test_unchanged_approved_source_backfills_semantics_without_reextracting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    _write_docx(source_dir / "一年级数学课程.docx", ["一年级数学课程共十二讲。"])
    knowledge_dir = tmp_path / "knowledge"
    _knowledge_dirs(knowledge_dir)
    database = tmp_path / "knowledge.sqlite3"
    service = KnowledgeImportService(
        knowledge_dir, database, tmp_path / "staging"
    )
    first = service.prepare(source_dir)
    review = json.loads(first.review_path.read_text(encoding="utf-8"))
    _approve_raw(review["decisions"]["一年级数学课程.docx"])
    first.review_path.write_text(
        json.dumps(review, ensure_ascii=False), encoding="utf-8"
    )
    service.apply(first.batch_id)
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM policy_semantic_links")
        connection.execute("DELETE FROM semantic_records")
        connection.execute("DELETE FROM semantic_candidates")
        connection.execute("DELETE FROM semantic_revision_scans")

    import lexiaodu.knowledge_import as import_module

    def unexpected_extract(*args, **kwargs):
        raise AssertionError("unchanged source must not be extracted or OCRed")

    monkeypatch.setattr(import_module, "extract_source", unexpected_extract)
    second = service.prepare(source_dir)

    assert second.unchanged_count == 1
    second_review = json.loads(second.review_path.read_text(encoding="utf-8"))
    decision = second_review["decisions"]["一年级数学课程.docx"]
    assert decision["raw"]["preserve_existing"] is True
    assert decision["semantic"]["records"]


def test_review_all_sources_reuses_approved_revision_without_reextracting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    _write_docx(source_dir / "一年级数学课程.docx", ["一年级数学课程共十二讲。"])
    knowledge_dir = tmp_path / "knowledge"
    _knowledge_dirs(knowledge_dir)
    service = KnowledgeImportService(
        knowledge_dir, tmp_path / "knowledge.sqlite3", tmp_path / "staging"
    )
    first = service.prepare(source_dir)
    first_review = json.loads(first.review_path.read_text(encoding="utf-8"))
    _approve_raw(first_review["decisions"]["一年级数学课程.docx"])
    first.review_path.write_text(
        json.dumps(first_review, ensure_ascii=False), encoding="utf-8"
    )
    service.apply(first.batch_id)

    import lexiaodu.knowledge_import as import_module

    def unexpected_extract(*args, **kwargs):
        raise AssertionError("review-only batch must not extract or OCR")

    monkeypatch.setattr(import_module, "extract_source", unexpected_extract)
    second = service.prepare(source_dir, review_all_sources=True)
    second_review = json.loads(second.review_path.read_text(encoding="utf-8"))
    decision = second_review["decisions"]["一年级数学课程.docx"]

    assert second.unchanged_count == 1
    assert decision["raw"]["status"] == "pending"
    assert decision["raw"]["preserve_existing"] is False
    assert decision["semantic"]["records"]
    first_record_count = service.semantic_report().record_count
    _approve_raw(decision)
    second.review_path.write_text(
        json.dumps(second_review, ensure_ascii=False), encoding="utf-8"
    )
    service.apply(second.batch_id)
    assert service.semantic_report().record_count == first_record_count

    third = service.prepare(source_dir, review_all_sources=True)
    third_review = json.loads(third.review_path.read_text(encoding="utf-8"))
    third_decision = next(iter(third_review["decisions"].values()))
    _approve_raw(third_decision)
    third.review_path.write_text(
        json.dumps(third_review, ensure_ascii=False), encoding="utf-8"
    )
    service.apply(third.batch_id)
    assert service.semantic_report().record_count == first_record_count


def test_expired_campaign_is_recorded_but_not_searchable(tmp_path: Path) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    _write_docx(
        source_dir / "暑期优惠活动.docx",
        ["暑期优惠活动：2026-01-01至2026-02-01，报名赠送练习册。"],
    )
    knowledge_dir = tmp_path / "knowledge"
    _knowledge_dirs(knowledge_dir)
    database = tmp_path / "knowledge.sqlite3"
    service = KnowledgeImportService(
        knowledge_dir, database, tmp_path / "staging"
    )
    prepared = service.prepare(source_dir)
    review = json.loads(prepared.review_path.read_text(encoding="utf-8"))
    decision = review["decisions"]["暑期优惠活动.docx"]
    _approve_raw(decision)
    for item in decision["semantic"]["records"]:
        record = item["record"]
        if record["record_kind"] == "campaign":
            record["campaign_student_scope"] = "新生"
            record["campaign_fulfillment"] = "由顾问按审核流程办理"
    prepared.review_path.write_text(
        json.dumps(review, ensure_ascii=False), encoding="utf-8"
    )
    service.apply(prepared.batch_id)

    semantic = service.semantic_report()
    assert semantic.campaign_expired_count >= 1
    assert KnowledgeBase(knowledge_dir, database).search(
        "赠送练习册", KnowledgeType.SOURCE
    ) == []
    assert KnowledgeBase(knowledge_dir, database).search_advice_policy(
        "这个优惠赠品活动现在还能参加吗"
    ) == []


def test_conflicting_active_campaigns_block_apply(tmp_path: Path) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    _write_docx(
        source_dir / "数学优惠活动产品说明.docx",
        ["数学优惠活动：2026-08-01至2026-08-31，报名赠送练习册。"],
    )
    _write_docx(
        source_dir / "数学优惠活动招生物料.docx",
        ["数学优惠活动：2026-08-01至2026-08-31，报名赠送书包。"],
    )
    knowledge_dir = tmp_path / "knowledge"
    _knowledge_dirs(knowledge_dir)
    service = KnowledgeImportService(
        knowledge_dir, tmp_path / "knowledge.sqlite3", tmp_path / "staging"
    )
    prepared = service.prepare(source_dir)
    review = json.loads(prepared.review_path.read_text(encoding="utf-8"))
    for decision in review["decisions"].values():
        _approve_raw(decision)
        for item in decision["semantic"]["records"]:
            record = item["record"]
            if record["record_kind"] == "campaign":
                record["campaign_student_scope"] = "新生"
                record["campaign_fulfillment"] = "由顾问按审核流程办理"
    prepared.review_path.write_text(
        json.dumps(review, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(KnowledgeImportError, match="未解决.*冲突"):
        service.apply(prepared.batch_id)


def test_national_class_defaults_to_pending_until_tianjin_is_confirmed(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    _write_docx(source_dir / "全国班数学课程.docx", ["全国班数学课程共十二讲。"])
    knowledge_dir = tmp_path / "knowledge"
    _knowledge_dirs(knowledge_dir)
    database = tmp_path / "knowledge.sqlite3"
    service = KnowledgeImportService(
        knowledge_dir, database, tmp_path / "staging"
    )
    prepared = service.prepare(source_dir)
    review = json.loads(prepared.review_path.read_text(encoding="utf-8"))
    decision = review["decisions"]["全国班数学课程.docx"]
    _approve_raw(decision)
    prepared.review_path.write_text(
        json.dumps(review, ensure_ascii=False), encoding="utf-8"
    )
    service.apply(prepared.batch_id)

    assert KnowledgeBase(knowledge_dir, database).search(
        "全国班十二讲", KnowledgeType.SOURCE
    ) == []
    assert service.coverage_report().pending_block_count == 1


def test_apply_failure_restores_policy_database_and_source_fts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    _write_docx(source_dir / "小学数学产品说明.docx", ["新课程共十二讲。"])
    knowledge_dir = tmp_path / "knowledge"
    _knowledge_dirs(knowledge_dir)
    target = knowledge_dir / "policy" / "产品知识" / "小学数学-时期待确认.txt"
    target.parent.mkdir(parents=True)
    target.write_text("# 旧知识\n旧课程仍在服务。\n", encoding="utf-8")
    database = tmp_path / "knowledge.sqlite3"
    KnowledgeBase(knowledge_dir, database).rebuild()
    service = KnowledgeImportService(
        knowledge_dir, database, tmp_path / "staging"
    )
    prepared = service.prepare(source_dir)
    review = json.loads(prepared.review_path.read_text(encoding="utf-8"))
    decision = review["decisions"]["小学数学产品说明.docx"]
    _approve_raw(decision)
    decision["outputs"] = ["policy/产品知识/小学数学-时期待确认.txt"]
    prepared.review_path.write_text(
        json.dumps(review, ensure_ascii=False), encoding="utf-8"
    )
    draft = prepared.review_path.parent / "draft" / "knowledge" / decision["outputs"][0]
    draft.write_text("# 新知识\n新课程共十二讲。\n", encoding="utf-8")

    import lexiaodu.knowledge_import as import_module

    def fail_after_database_changes(connection: sqlite3.Connection) -> None:
        raise RuntimeError("injected source FTS failure")

    monkeypatch.setattr(import_module, "_rebuild_source_fts", fail_after_database_changes)
    with pytest.raises(RuntimeError, match="injected"):
        service.apply(prepared.batch_id)

    assert target.read_text(encoding="utf-8") == "# 旧知识\n旧课程仍在服务。\n"
    assert KnowledgeBase(knowledge_dir, database).search(
        "旧课程", KnowledgeType.POLICY
    )
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM semantic_records").fetchone()[0] == 0
        assert connection.execute(
            "SELECT status FROM source_revisions"
        ).fetchone()[0] == "pending"


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
