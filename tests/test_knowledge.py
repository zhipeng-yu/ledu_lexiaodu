from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

import pytest

from lexiaodu.knowledge import (
    DEFAULT_CHUNK_SIZE,
    KnowledgeBase,
    KnowledgeError,
    KnowledgeType,
    format_search_results,
)


def _knowledge_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "knowledge"
    policy = root / KnowledgeType.POLICY
    style_case = root / KnowledgeType.STYLE_CASE
    policy.mkdir(parents=True)
    style_case.mkdir()
    return root, policy, style_case


def _write_docx(path: Path, heading: str, body: str) -> None:
    document_xml = f"""\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:r><w:t>{heading}</w:t></w:r>
    </w:p>
    <w:p><w:r><w:t>{body}</w:t></w:r></w:p>
  </w:body>
</w:document>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document_xml)


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


def test_rebuild_parses_txt_docx_and_text_pdf_with_source_metadata(
    tmp_path: Path,
) -> None:
    root, policy, style_case = _knowledge_dirs(tmp_path)
    (policy / "月莓守则.txt").write_text(
        "# 月莓请假章\n月莓学院请假须由监护人提交星印申请。",
        encoding="utf-8",
    )
    _write_docx(
        policy / "星舟规范.docx",
        "星舟安全章",
        "星舟出发前必须检查蓝色罗盘。",
    )
    _write_text_pdf(
        style_case / "云鲸回信.pdf",
        "Cloudwhale letters use a warm moonberry greeting.",
    )
    database = tmp_path / "knowledge.sqlite3"

    report = KnowledgeBase(root, database).rebuild()

    assert report.document_count == 3
    assert report.chunk_count == 3
    with sqlite3.connect(database) as connection:
        documents = connection.execute(
            "SELECT name, knowledge_type, file_format FROM documents "
            "ORDER BY name"
        ).fetchall()
        chunks = connection.execute(
            "SELECT locator, text FROM chunks ORDER BY locator"
        ).fetchall()
    assert documents == [
        ("云鲸回信.pdf", "style_case", "pdf"),
        ("星舟规范.docx", "policy", "docx"),
        ("月莓守则.txt", "policy", "txt"),
    ]
    assert ("星舟安全章", "星舟出发前必须检查蓝色罗盘。") in chunks
    assert ("月莓请假章", "月莓学院请假须由监护人提交星印申请。") in chunks
    assert any(locator == "第 1 页" and "Cloudwhale" in text for locator, text in chunks)


def test_bm25_returns_top_three_and_never_mixes_knowledge_types(
    tmp_path: Path,
) -> None:
    root, policy, style_case = _knowledge_dirs(tmp_path)
    for index in range(4):
        (policy / f"月莓政策{index}.txt").write_text(
            f"# 第 {index + 1} 章\n月莓通行证办理规则 {index}。" + " 月莓" * (4 - index),
            encoding="utf-8",
        )
    (style_case / "月莓语气案例.txt").write_text(
        "# 温暖案例\n月莓通行证可以用“星光已为你点亮”来温柔表达。",
        encoding="utf-8",
    )
    knowledge = KnowledgeBase(root, tmp_path / "knowledge.sqlite3")
    knowledge.rebuild()

    policy_results = knowledge.search("月莓通行证", KnowledgeType.POLICY)
    style_results = knowledge.search("月莓通行证", KnowledgeType.STYLE_CASE)

    assert len(policy_results) == 3
    assert all(
        result.knowledge_type is KnowledgeType.POLICY
        for result in policy_results
    )
    assert len(style_results) == 1
    assert style_results[0].knowledge_type is KnowledgeType.STYLE_CASE
    assert "温柔表达" in style_results[0].evidence
    rendered = format_search_results(style_results)
    assert "月莓语气案例.txt" in rendered
    assert "温暖案例" in rendered
    assert "证据：" in rendered


def test_search_uses_document_name_to_route_subject_query(
    tmp_path: Path,
) -> None:
    root, policy, _ = _knowledge_dirs(tmp_path)
    (policy / "蓝鲸化学.txt").write_text(
        "# 课次与时长\n夏季12讲。",
        encoding="utf-8",
    )
    knowledge = KnowledgeBase(root, tmp_path / "knowledge.sqlite3")
    knowledge.rebuild()

    results = knowledge.search("蓝鲸化学", KnowledgeType.POLICY)

    assert len(results) == 1
    assert results[0].document_name == "蓝鲸化学.txt"
    assert results[0].evidence == "夏季12讲。"


def test_rebuild_replaces_stale_index_content(tmp_path: Path) -> None:
    root, policy, _ = _knowledge_dirs(tmp_path)
    document = policy / "旧月规.txt"
    document.write_text("旧月规要求出示银狐密钥。", encoding="utf-8")
    knowledge = KnowledgeBase(root, tmp_path / "knowledge.sqlite3")
    knowledge.rebuild()
    assert knowledge.search("银狐密钥", KnowledgeType.POLICY)

    document.unlink()
    (policy / "新月规.txt").write_text(
        "新月规要求出示金雀令牌。", encoding="utf-8"
    )
    report = knowledge.rebuild()

    assert report.document_count == 1
    assert knowledge.search("银狐密钥", KnowledgeType.POLICY) == []
    assert (
        knowledge.search("金雀令牌", KnowledgeType.POLICY)[0].document_name
        == "新月规.txt"
    )


def test_rebuild_rejects_supported_documents_without_classification(
    tmp_path: Path,
) -> None:
    root, _, _ = _knowledge_dirs(tmp_path)
    (root / "未分类规则.txt").write_text("这是一条未分类规则。", encoding="utf-8")

    with pytest.raises(KnowledgeError, match="policy.*style_case"):
        KnowledgeBase(root, tmp_path / "knowledge.sqlite3").rebuild()


def test_long_section_is_split_into_bounded_chunks(tmp_path: Path) -> None:
    root, policy, _ = _knowledge_dirs(tmp_path)
    (policy / "星砂长卷.txt").write_text(
        "# 星砂章\n" + "星砂航线每次转向都要记录。" * 100,
        encoding="utf-8",
    )
    database = tmp_path / "knowledge.sqlite3"

    report = KnowledgeBase(root, database).rebuild()

    assert report.chunk_count > 1
    with sqlite3.connect(database) as connection:
        chunks = connection.execute(
            "SELECT locator, length(text) FROM chunks ORDER BY chunk_index"
        ).fetchall()
    assert all(locator == "星砂章" for locator, _ in chunks)
    assert all(length <= DEFAULT_CHUNK_SIZE for _, length in chunks)
