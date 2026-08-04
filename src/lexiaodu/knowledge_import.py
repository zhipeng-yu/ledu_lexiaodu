from __future__ import annotations

import hashlib
import json
import posixpath
import re
import shutil
import sqlite3
import uuid
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Protocol
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage

from lexiaodu.knowledge import (
    KnowledgeBase,
    KnowledgeError,
    SourceBlock,
    chunk_block,
    tokenize,
)
from lexiaodu.ocr import MIN_TEXT_CONFIDENCE, OcrError, PaddleOcrEngine


SUPPORTED_SOURCE_SUFFIXES = {
    ".docx",
    ".xlsx",
    ".pptx",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}
LEGACY_SOURCE_SUFFIXES = {".doc", ".xls", ".ppt"}
IMAGE_SOURCE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_EXCLUDED_SOURCE_PARTS = {"顾问聊天记录"}
_URL_PATTERN = re.compile(r"https?://[^\s《》<>]+", re.IGNORECASE)
_HEADING_PATTERN = re.compile(
    r"^(?:#{1,6}\s+|[一二三四五六七八九十百]+[、.．]|\d+[、.．)）])"
)
_WORD_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_SHEET_NS = {
    "x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


class KnowledgeImportError(RuntimeError):
    """Raised when a staged knowledge import cannot be prepared or applied."""


class DocumentOcr(Protocol):
    def recognize_document(self, image: QImage) -> list[Any]: ...


@dataclass(frozen=True, slots=True)
class ExtractedBlock:
    locator: str
    kind: str
    text: str
    confidence: float | None = None
    warning: str = ""


@dataclass(frozen=True, slots=True)
class LinkOccurrence:
    target_url: str
    canonical_key: str
    target_type: str
    display_text: str
    locator: str
    context: str


@dataclass(frozen=True, slots=True)
class ExtractedSource:
    title: str
    blocks: tuple[ExtractedBlock, ...]
    links: tuple[LinkOccurrence, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LinkReport:
    occurrence_count: int
    unique_target_count: int
    ingested_target_count: int
    missing_target_count: int
    internal_anchor_count: int
    by_type: dict[str, int]
    archived_target_count: int = 0
    advisor_target_count: int = 0
    internal_only_target_count: int = 0


@dataclass(frozen=True, slots=True)
class CoverageReport:
    source_count: int
    revision_count: int
    block_count: int
    text_char_count: int
    searchable_char_count: int
    advisor_block_count: int
    internal_block_count: int
    pending_block_count: int
    no_text_block_count: int
    failed_block_count: int
    blocked_block_count: int
    image_count: int
    image_ocr_count: int
    by_kind: dict[str, int]


@dataclass(frozen=True, slots=True)
class PrepareReport:
    batch_id: str
    new_count: int
    changed_count: int
    unchanged_count: int
    missing_source_count: int
    failed_count: int
    link_report: LinkReport
    review_path: Path
    report_path: Path


@dataclass(frozen=True, slots=True)
class ApplyReport:
    batch_id: str
    output_count: int
    indexed_document_count: int
    indexed_chunk_count: int
    link_report: LinkReport


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bytes_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _clean_text(value: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", value).strip()


def _safe_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" .")
    return cleaned or "untitled"


def _normalized_title(value: str) -> str:
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", value.casefold())


def _extract_url(value: str) -> str:
    match = _URL_PATTERN.search(value or "")
    if match is None:
        return ""
    return match.group().rstrip("/.,;，。；）)")


def canonicalize_url(value: str) -> str:
    """Return a stable, non-secret link identity used for deduplication."""

    url = _extract_url(value)
    if not url:
        return ""
    split = urlsplit(url)
    path = split.path.rstrip("/")
    return urlunsplit(
        (split.scheme.casefold(), split.netloc.casefold(), path, "", "")
    )


def classify_link(value: str) -> str:
    split = urlsplit(value)
    host = split.netloc.casefold()
    path = split.path.casefold()
    if "/docs/" in path:
        return "document"
    if "/sheets/" in path:
        return "sheet"
    if "/uploader/" in path or "/files/" in path or "/file/" in path:
        suffix = Path(path).suffix
        return {
            ".pdf": "pdf",
            ".ppt": "presentation",
            ".pptx": "presentation",
            ".mp4": "video",
        }.get(suffix, "attachment")
    if (
        "paperrest" in host
        or "game-shell" in path
        or "mccplayer" in path
    ):
        return "interactive"
    if host == "s.tal.com":
        return "short_link"
    return "other"


def _relationships(xml: bytes) -> dict[str, tuple[str, str, str]]:
    root = ElementTree.fromstring(xml)
    result: dict[str, tuple[str, str, str]] = {}
    for relationship in root:
        result[relationship.get("Id", "")] = (
            relationship.get("Target", ""),
            relationship.get("TargetMode", ""),
            relationship.get("Type", "").rsplit("/", 1)[-1],
        )
    return result


def _is_heading(text: str, style: str = "") -> bool:
    folded = style.casefold()
    return (
        folded.startswith("heading")
        or folded.startswith("title")
        or bool(_HEADING_PATTERN.match(text))
    )


def _deduplicate_links(
    links: Iterable[LinkOccurrence],
) -> tuple[LinkOccurrence, ...]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[LinkOccurrence] = []
    for link in links:
        key = (
            link.canonical_key,
            link.locator,
            link.display_text,
            link.context,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(link)
    return tuple(result)


class _OcrCoordinator:
    def __init__(
        self,
        engine: DocumentOcr | None,
        cached: dict[str, tuple[str, str] | tuple[str, str, float | None]],
        *,
        skip_images: bool = False,
    ) -> None:
        self.engine = engine
        self.cached = {
            digest: (
                value[0],
                value[1],
                value[2] if len(value) > 2 else None,
            )
            for digest, value in cached.items()
        }
        self.pending: dict[
            str, tuple[str, str, float | None, int, int]
        ] = {}
        self.skip_images = skip_images

    def recognize(
        self, data: bytes, label: str
    ) -> tuple[str, str, float | None]:
        if self.skip_images:
            return "", "", None
        digest = _bytes_hash(data)
        if digest in self.cached:
            return self.cached[digest]
        image = QImage.fromData(data)
        if image.isNull():
            result = ("", f"{label}: 无法解码嵌入图片", None)
        elif image.width() < 80 or image.height() < 30:
            result = ("", "", None)
        elif self.engine is None:
            result = (
                "",
                f"{label}: 未启用 OCR，图片文字尚未提取",
                None,
            )
        else:
            try:
                lines = self.engine.recognize_document(image)
                confidences = [
                    float(line.confidence)
                    for line in lines
                    if getattr(line, "confidence", None) is not None
                ]
                result = (
                    "\n".join(line.text for line in lines),
                    "",
                    (
                        sum(confidences) / len(confidences)
                        if confidences
                        else None
                    ),
                )
            except OcrError as exc:
                result = ("", f"{label}: OCR 失败：{exc}", None)
        self.cached[digest] = result
        self.pending[digest] = (
            result[0],
            result[1],
            result[2],
            image.width(),
            image.height(),
        )
        return result


def _paragraph_text(element: ElementTree.Element) -> str:
    return _clean_text(
        "".join(
            value.text or ""
            for value in element.findall(".//w:t", _WORD_NS)
        )
    )


def _docx_links_in_element(
    element: ElementTree.Element,
    relationships: dict[str, tuple[str, str, str]],
    locator: str,
    context: str,
) -> list[LinkOccurrence]:
    links: list[LinkOccurrence] = []
    relationship_urls: set[str] = set()
    relationship_id = f"{{{_WORD_NS['r']}}}id"
    anchor_name = f"{{{_WORD_NS['w']}}}anchor"
    for hyperlink in element.findall(".//w:hyperlink", _WORD_NS):
        display = _paragraph_text(hyperlink)
        relation_id = hyperlink.get(relationship_id)
        anchor = hyperlink.get(anchor_name)
        if relation_id and relation_id in relationships:
            target, _, relation_type = relationships[relation_id]
            if relation_type != "hyperlink":
                continue
            target_url = _extract_url(target)
            canonical = canonicalize_url(target)
            if not canonical:
                continue
            relationship_urls.add(canonical)
            links.append(
                LinkOccurrence(
                    target_url=target_url,
                    canonical_key=canonical,
                    target_type=classify_link(canonical),
                    display_text=display or target_url,
                    locator=locator,
                    context=context,
                )
            )
        elif anchor:
            links.append(
                LinkOccurrence(
                    target_url=f"#{anchor}",
                    canonical_key=f"internal:{anchor}",
                    target_type="internal_anchor",
                    display_text=display or anchor,
                    locator=locator,
                    context=context,
                )
            )
    for match in _URL_PATTERN.finditer(context):
        target_url = _extract_url(match.group())
        canonical = canonicalize_url(target_url)
        if not canonical or canonical in relationship_urls:
            continue
        links.append(
            LinkOccurrence(
                target_url=target_url,
                canonical_key=canonical,
                target_type=classify_link(canonical),
                display_text=target_url,
                locator=locator,
                context=context,
            )
        )
    return links


def extract_docx(path: Path, ocr: _OcrCoordinator) -> ExtractedSource:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            document = ElementTree.fromstring(archive.read("word/document.xml"))
            relationship_path = "word/_rels/document.xml.rels"
            relationships = (
                _relationships(archive.read(relationship_path))
                if relationship_path in names
                else {}
            )
            media = {
                name: archive.read(name)
                for name in names
                if name.startswith("word/media/")
            }
            extra_xml = {
                name: archive.read(name)
                for name in names
                if re.fullmatch(
                    r"word/(?:header|footer|footnotes|endnotes|comments)[^/]*\.xml",
                    name,
                )
            }
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise KnowledgeImportError(f"DOCX 无法读取：{path}: {exc}") from exc

    blocks: list[ExtractedBlock] = []
    links: list[LinkOccurrence] = []
    warnings: list[str] = []
    locator = path.stem
    body = document.find(".//w:body", _WORD_NS)
    if body is None:
        raise KnowledgeImportError(f"DOCX 缺少正文：{path}")

    def process_paragraph(paragraph: ElementTree.Element) -> None:
        nonlocal locator
        text = _paragraph_text(paragraph)
        style_element = paragraph.find("./w:pPr/w:pStyle", _WORD_NS)
        style = ""
        if style_element is not None:
            style = style_element.get(f"{{{_WORD_NS['w']}}}val", "")
        if text and _is_heading(text, style):
            locator = text.lstrip("# ")
            kind = "heading"
        else:
            kind = "paragraph"
        if text:
            blocks.append(ExtractedBlock(locator, kind, text))
            links.extend(
                _docx_links_in_element(
                    paragraph, relationships, locator, text
                )
            )

    for child in body:
        local_name = child.tag.rsplit("}", 1)[-1]
        if local_name == "p":
            process_paragraph(child)
        elif local_name == "tbl":
            rows: list[str] = []
            for row in child.findall("./w:tr", _WORD_NS):
                cells: list[str] = []
                for cell in row.findall("./w:tc", _WORD_NS):
                    cell_parts: list[str] = []
                    for paragraph in cell.findall("./w:p", _WORD_NS):
                        value = _paragraph_text(paragraph)
                        if value:
                            cell_parts.append(value)
                        links.extend(
                            _docx_links_in_element(
                                paragraph,
                                relationships,
                                locator,
                                value,
                            )
                        )
                    cells.append(" / ".join(cell_parts))
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                blocks.append(
                    ExtractedBlock(locator, "table", "\n".join(rows))
                )

    part_labels = {
        "header": "页眉",
        "footer": "页脚",
        "footnotes": "脚注",
        "endnotes": "尾注",
        "comments": "批注",
    }
    parsed_parts: list[tuple[str, ElementTree.Element]] = [
        ("正文", document)
    ]
    for part_name, xml in sorted(extra_xml.items()):
        stem = Path(part_name).stem
        part_kind = next(
            (key for key in part_labels if stem.startswith(key)), stem
        )
        label = f"{part_labels.get(part_kind, part_kind)} {stem}"
        try:
            root = ElementTree.fromstring(xml)
        except ElementTree.ParseError as exc:
            warnings.append(f"{label}: XML 无法解析：{exc}")
            continue
        parsed_parts.append((label, root))
        text = _clean_text(
            "".join(node.text or "" for node in root.findall(".//w:t", _WORD_NS))
        )
        if text:
            blocks.append(ExtractedBlock(label, part_kind, text))
            for match in _URL_PATTERN.finditer(text):
                target_url = _extract_url(match.group())
                canonical = canonicalize_url(target_url)
                if canonical:
                    links.append(
                        LinkOccurrence(
                            target_url,
                            canonical,
                            classify_link(canonical),
                            target_url,
                            label,
                            text,
                        )
                    )

    for part_label, root in parsed_parts:
        alt_values: list[str] = []
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] not in {"docPr", "cNvPr"}:
                continue
            for attribute in ("title", "descr"):
                value = _clean_text(element.get(attribute, ""))
                if value and value not in alt_values:
                    alt_values.append(value)
        if alt_values:
            blocks.append(
                ExtractedBlock(part_label, "alt_text", "\n".join(alt_values))
            )
        deleted = _clean_text(
            "".join(
                node.text or ""
                for node in root.findall(".//w:delText", _WORD_NS)
            )
        )
        if deleted:
            blocks.append(
                ExtractedBlock(part_label, "revision_deleted", deleted)
            )

    for media_name, data in sorted(media.items()):
        image_text, warning, confidence = ocr.recognize(
            data, f"{path.name}/{media_name}"
        )
        image_locator = f"嵌入图片 {Path(media_name).name}"
        blocks.append(
            ExtractedBlock(
                image_locator,
                "image_ocr" if image_text else "image_no_text",
                f"[图片文字] {image_text}" if image_text else "",
                confidence,
                warning,
            )
        )
        if warning:
            warnings.append(warning)

    return ExtractedSource(
        title=path.stem,
        blocks=tuple(blocks),
        # Keep repeated Word hyperlinks as separate occurrences.  Plain-text
        # URLs duplicating a relationship hyperlink were already filtered at
        # paragraph level above.
        links=tuple(links),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _xlsx_cell_value(
    cell: ElementTree.Element, shared_strings: list[str]
) -> tuple[str, str]:
    cell_type = cell.get("t", "")
    formula_element = cell.find("./x:f", _SHEET_NS)
    formula = formula_element.text or "" if formula_element is not None else ""
    if cell_type == "inlineStr":
        value = "".join(
            node.text or "" for node in cell.findall(".//x:t", _SHEET_NS)
        )
    else:
        value_element = cell.find("./x:v", _SHEET_NS)
        value = value_element.text or "" if value_element is not None else ""
        if cell_type == "s" and value:
            try:
                value = shared_strings[int(value)]
            except (ValueError, IndexError):
                pass
        elif cell_type == "b":
            value = "TRUE" if value == "1" else "FALSE"
    return _clean_text(value), _clean_text(formula)


def extract_xlsx(path: Path, ocr: _OcrCoordinator) -> ExtractedSource:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            media = {
                name: archive.read(name)
                for name in names
                if name.startswith("xl/media/")
            }
            workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
            workbook_relationships = _relationships(
                archive.read("xl/_rels/workbook.xml.rels")
            )
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in names:
                shared_root = ElementTree.fromstring(
                    archive.read("xl/sharedStrings.xml")
                )
                shared_strings = [
                    "".join(
                        value.text or ""
                        for value in item.findall(".//x:t", _SHEET_NS)
                    )
                    for item in shared_root.findall("./x:si", _SHEET_NS)
                ]
            sheets: list[tuple[str, str]] = []
            for sheet in workbook.findall(".//x:sheets/x:sheet", _SHEET_NS):
                relation_id = sheet.get(f"{{{_SHEET_NS['r']}}}id", "")
                target = workbook_relationships.get(relation_id, ("", "", ""))[0]
                if target:
                    sheet_path = posixpath.normpath(f"xl/{target}")
                    sheets.append((sheet.get("name", "Sheet"), sheet_path))

            blocks: list[ExtractedBlock] = []
            links: list[LinkOccurrence] = []
            warnings: list[str] = []
            defined_names = [
                f"{item.get('name', '')}={_clean_text(item.text or '')}"
                for item in workbook.findall(".//x:definedNames/x:definedName", _SHEET_NS)
                if _clean_text(item.text or "")
            ]
            if defined_names:
                blocks.append(
                    ExtractedBlock(
                        "工作簿定义名称",
                        "workbook_metadata",
                        "\n".join(defined_names),
                    )
                )
            for sheet_name, sheet_path in sheets:
                if sheet_path not in names:
                    warnings.append(f"工作表缺少 XML：{sheet_name}")
                    continue
                sheet_root = ElementTree.fromstring(archive.read(sheet_path))
                relation_path = str(
                    Path(sheet_path).parent
                    / "_rels"
                    / f"{Path(sheet_path).name}.rels"
                ).replace("\\", "/")
                sheet_relationships = (
                    _relationships(archive.read(relation_path))
                    if relation_path in names
                    else {}
                )
                comments: dict[str, str] = {}
                for target, _, relation_type in sheet_relationships.values():
                    if relation_type != "comments":
                        continue
                    comment_path = posixpath.normpath(
                        f"{posixpath.dirname(sheet_path)}/{target}"
                    )
                    if comment_path not in names:
                        warnings.append(
                            f"工作表批注文件缺失：{sheet_name}/{target}"
                        )
                        continue
                    comment_root = ElementTree.fromstring(
                        archive.read(comment_path)
                    )
                    for comment in comment_root.findall(
                        ".//x:commentList/x:comment", _SHEET_NS
                    ):
                        reference = comment.get("ref", "")
                        comment_text = _clean_text(
                            "".join(
                                node.text or ""
                                for node in comment.findall(
                                    ".//x:text//x:t", _SHEET_NS
                                )
                            )
                        )
                        if reference and comment_text:
                            comments[reference] = comment_text
                cell_values: dict[str, tuple[str, str]] = {}
                for cell in sheet_root.findall(".//x:c", _SHEET_NS):
                    reference = cell.get("r", "")
                    cell_values[reference] = _xlsx_cell_value(
                        cell, shared_strings
                    )
                for row in sheet_root.findall(".//x:sheetData/x:row", _SHEET_NS):
                    parts: list[str] = []
                    row_number = row.get("r", "?")
                    for cell in row.findall("./x:c", _SHEET_NS):
                        reference = cell.get("r", "")
                        value, formula = cell_values.get(reference, ("", ""))
                        rendered = value
                        if formula:
                            rendered = f"{value} [公式: ={formula}]" if value else f"={formula}"
                            for match in re.finditer(
                                r'HYPERLINK\(\s*"([^"]+)"(?:\s*,\s*"([^"]*)")?',
                                formula,
                                re.IGNORECASE,
                            ):
                                target_url = _extract_url(match.group(1))
                                canonical = canonicalize_url(target_url)
                                if canonical:
                                    links.append(
                                        LinkOccurrence(
                                            target_url,
                                            canonical,
                                            classify_link(canonical),
                                            match.group(2) or value or target_url,
                                            f"{sheet_name}!{reference}",
                                            rendered,
                                        )
                                    )
                        if rendered:
                            parts.append(f"{reference}={rendered}")
                        if reference in comments:
                            parts.append(f"{reference}批注={comments[reference]}")
                        for match in _URL_PATTERN.finditer(rendered):
                            target_url = _extract_url(match.group())
                            canonical = canonicalize_url(target_url)
                            if canonical:
                                links.append(
                                    LinkOccurrence(
                                        target_url,
                                        canonical,
                                        classify_link(canonical),
                                        target_url,
                                        f"{sheet_name}!{reference}",
                                        rendered,
                                    )
                                )
                        for match in _URL_PATTERN.finditer(
                            comments.get(reference, "")
                        ):
                            target_url = _extract_url(match.group())
                            canonical = canonicalize_url(target_url)
                            if canonical:
                                links.append(
                                    LinkOccurrence(
                                        target_url,
                                        canonical,
                                        classify_link(canonical),
                                        target_url,
                                        f"{sheet_name}!{reference} 批注",
                                        comments[reference],
                                    )
                                )
                    if parts:
                        blocks.append(
                            ExtractedBlock(
                                f"{sheet_name}!第 {row_number} 行",
                                "spreadsheet_row",
                                " | ".join(parts),
                            )
                        )
                for hyperlink in sheet_root.findall(".//x:hyperlinks/x:hyperlink", _SHEET_NS):
                    reference = hyperlink.get("ref", "")
                    relation_id = hyperlink.get(f"{{{_SHEET_NS['r']}}}id", "")
                    location = hyperlink.get("location", "")
                    value = cell_values.get(reference, ("", ""))[0]
                    if relation_id in sheet_relationships:
                        target = sheet_relationships[relation_id][0]
                        target_url = _extract_url(target)
                        canonical = canonicalize_url(target)
                        if canonical:
                            links.append(
                                LinkOccurrence(
                                    target_url,
                                    canonical,
                                    classify_link(canonical),
                                    hyperlink.get("display", "") or value or target_url,
                                    f"{sheet_name}!{reference}",
                                    value,
                                )
                            )
                    elif location:
                        links.append(
                            LinkOccurrence(
                                f"#{location}",
                                f"internal:{sheet_name}:{location}",
                                "internal_anchor",
                                hyperlink.get("display", "") or value or location,
                                f"{sheet_name}!{reference}",
                                value,
                            )
                        )
            for media_name, data in sorted(media.items()):
                image_text, warning, confidence = ocr.recognize(
                    data, f"{path.name}/{media_name}"
                )
                blocks.append(
                    ExtractedBlock(
                        f"嵌入图片 {Path(media_name).name}",
                        "image_ocr" if image_text else "image_no_text",
                        image_text,
                        confidence,
                        warning,
                    )
                )
                if warning:
                    warnings.append(warning)
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise KnowledgeImportError(f"XLSX 无法读取：{path}: {exc}") from exc

    return ExtractedSource(
        title=path.stem,
        blocks=tuple(blocks),
        links=_deduplicate_links(links),
        warnings=tuple(warnings),
    )


def _numbered_part_key(name: str) -> tuple[str, int, str]:
    match = re.search(r"(\d+)(?=\.xml$)", name)
    return (str(Path(name).parent), int(match.group(1)) if match else 0, name)


def extract_pptx(path: Path, ocr: _OcrCoordinator) -> ExtractedSource:
    drawing_ns = {
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main"
    }
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            part_names = sorted(
                (
                    name
                    for name in names
                    if re.fullmatch(
                        r"ppt/(?:slides/slide|notesSlides/notesSlide|comments/comment)\d+\.xml",
                        name,
                    )
                ),
                key=_numbered_part_key,
            )
            parts = {name: archive.read(name) for name in part_names}
            relationships = {
                name: archive.read(name)
                for name in names
                if name.startswith("ppt/") and name.endswith(".rels")
            }
            media = {
                name: archive.read(name)
                for name in names
                if name.startswith("ppt/media/")
            }
    except (OSError, zipfile.BadZipFile) as exc:
        raise KnowledgeImportError(f"PPTX 无法读取：{path}: {exc}") from exc

    blocks: list[ExtractedBlock] = []
    links: list[LinkOccurrence] = []
    warnings: list[str] = []
    part_context: dict[str, str] = {}
    for part_name, xml in parts.items():
        if "/slides/" in part_name:
            label = f"第 {_numbered_part_key(part_name)[1]} 页"
            kind = "slide_text"
        elif "/notesSlides/" in part_name:
            label = f"第 {_numbered_part_key(part_name)[1]} 页备注"
            kind = "slide_notes"
        else:
            label = f"第 {_numbered_part_key(part_name)[1]} 页批注"
            kind = "slide_comment"
        try:
            root = ElementTree.fromstring(xml)
        except ElementTree.ParseError as exc:
            warnings.append(f"{label}: XML 无法解析：{exc}")
            continue
        text = _clean_text(
            "\n".join(
                node.text or "" for node in root.findall(".//a:t", drawing_ns)
            )
        )
        part_context[part_name] = text
        if text:
            blocks.append(ExtractedBlock(label, kind, text))
        alt_values: list[str] = []
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] not in {"cNvPr", "docPr"}:
                continue
            for attribute in ("title", "descr"):
                value = _clean_text(element.get(attribute, ""))
                if value and value not in alt_values:
                    alt_values.append(value)
        if alt_values:
            blocks.append(
                ExtractedBlock(label, "alt_text", "\n".join(alt_values))
            )
        for match in _URL_PATTERN.finditer(text):
            target_url = _extract_url(match.group())
            canonical = canonicalize_url(target_url)
            if canonical:
                links.append(
                    LinkOccurrence(
                        target_url,
                        canonical,
                        classify_link(canonical),
                        target_url,
                        label,
                        text,
                    )
                )

    for relation_name, xml in relationships.items():
        try:
            relation_values = _relationships(xml).values()
        except ElementTree.ParseError as exc:
            warnings.append(f"{relation_name}: 关系文件无法解析：{exc}")
            continue
        related_part = relation_name.replace("/_rels/", "/").removesuffix(
            ".rels"
        )
        context = part_context.get(related_part, "")
        locator = (
            f"第 {_numbered_part_key(related_part)[1]} 页"
            if "/slide" in related_part
            else Path(related_part).stem
        )
        for target, mode, relation_type in relation_values:
            if relation_type != "hyperlink" and mode.casefold() != "external":
                continue
            target_url = _extract_url(target)
            canonical = canonicalize_url(target)
            if canonical:
                links.append(
                    LinkOccurrence(
                        target_url,
                        canonical,
                        classify_link(canonical),
                        target_url,
                        locator,
                        context,
                    )
                )

    for media_name, data in sorted(media.items()):
        image_text, warning, confidence = ocr.recognize(
            data, f"{path.name}/{media_name}"
        )
        blocks.append(
            ExtractedBlock(
                f"嵌入图片 {Path(media_name).name}",
                "image_ocr" if image_text else "image_no_text",
                image_text,
                confidence,
                warning,
            )
        )
        if warning:
            warnings.append(warning)
    return ExtractedSource(
        title=path.stem,
        blocks=tuple(blocks),
        links=_deduplicate_links(links),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def extract_image(path: Path, ocr: _OcrCoordinator) -> ExtractedSource:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise KnowledgeImportError(f"图片无法读取：{path}: {exc}") from exc
    text, warning, confidence = ocr.recognize(data, path.name)
    block = ExtractedBlock(
        "整张图片",
        "image_ocr" if text else "image_no_text",
        text,
        confidence,
        warning,
    )
    return ExtractedSource(
        title=path.stem,
        blocks=(block,),
        links=tuple(
            LinkOccurrence(
                target_url,
                canonical,
                classify_link(canonical),
                target_url,
                "整张图片",
                text,
            )
            for match in _URL_PATTERN.finditer(text)
            if (target_url := _extract_url(match.group()))
            if (canonical := canonicalize_url(target_url))
        ),
        warnings=(warning,) if warning else (),
    )


def _render_pdf_page(path: Path, page_number: int) -> QImage:
    try:
        from PySide6.QtPdf import QPdfDocument
    except ImportError as exc:
        raise KnowledgeImportError("当前 PySide6 不包含 QtPdf，无法 OCR 扫描 PDF") from exc
    document = QPdfDocument()
    error = document.load(str(path))
    if error is not None and getattr(error, "name", "None_") != "None_":
        raise KnowledgeImportError(f"PDF 无法渲染：{path}: {error}")
    size = document.pagePointSize(page_number)
    width = max(1200, int(size.width() * 2))
    height = max(1600, int(size.height() * 2))
    return document.render(page_number, QSize(width, height))


def extract_pdf(path: Path, ocr: _OcrCoordinator) -> ExtractedSource:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
    except Exception as exc:
        raise KnowledgeImportError(f"PDF 无法读取：{path}: {exc}") from exc
    blocks: list[ExtractedBlock] = []
    links: list[LinkOccurrence] = []
    warnings: list[str] = []
    metadata = getattr(reader, "metadata", None)
    if metadata:
        metadata_text = "\n".join(
            f"{str(key).lstrip('/')}: {_clean_text(str(value))}"
            for key, value in metadata.items()
            if value is not None and _clean_text(str(value))
        )
        if metadata_text:
            blocks.append(
                ExtractedBlock("文档属性", "pdf_metadata", metadata_text)
            )
    for index, page in enumerate(reader.pages, start=1):
        locator = f"第 {index} 页"
        try:
            text = _clean_text(page.extract_text() or "")
        except Exception as exc:
            text = ""
            warnings.append(f"{locator}: 文本提取失败：{exc}")
        if text:
            blocks.append(ExtractedBlock(locator, "pdf_text", text))
        elif ocr.engine is not None:
            try:
                image = _render_pdf_page(path, index - 1)
                lines = ocr.engine.recognize_document(image)
                ocr_text = "\n".join(line.text for line in lines)
                confidences = [
                    float(line.confidence)
                    for line in lines
                    if getattr(line, "confidence", None) is not None
                ]
                confidence = (
                    sum(confidences) / len(confidences)
                    if confidences
                    else None
                )
                if ocr_text:
                    blocks.append(
                        ExtractedBlock(
                            locator, "pdf_ocr", ocr_text, confidence
                        )
                    )
                else:
                    warning = f"{locator}: 扫描页 OCR 未识别出文字"
                    warnings.append(warning)
                    blocks.append(
                        ExtractedBlock(
                            locator, "pdf_no_text", "", None, warning
                        )
                    )
            except (KnowledgeImportError, OcrError) as exc:
                warning = f"{locator}: {exc}"
                warnings.append(warning)
                blocks.append(
                    ExtractedBlock(
                        locator, "pdf_no_text", "", None, warning
                    )
                )
        else:
            warning = f"{locator}: 页面无可提取文本且未启用 OCR"
            warnings.append(warning)
            blocks.append(
                ExtractedBlock(locator, "pdf_no_text", "", None, warning)
            )
        try:
            page_images = list(getattr(page, "images", ()))
        except Exception as exc:
            page_images = []
            warnings.append(f"{locator}: 页面图片枚举失败：{exc}")
        for image_index, page_image in enumerate(page_images, start=1):
            image_text, warning, confidence = ocr.recognize(
                page_image.data,
                f"{path.name}/{locator}/图片{image_index}",
            )
            blocks.append(
                ExtractedBlock(
                    f"{locator} 图片 {image_index}",
                    "image_ocr" if image_text else "image_no_text",
                    image_text,
                    confidence,
                    warning,
                )
            )
            if warning:
                warnings.append(warning)
        for match in _URL_PATTERN.finditer(text):
            target_url = _extract_url(match.group())
            canonical = canonicalize_url(target_url)
            if canonical:
                links.append(
                    LinkOccurrence(
                        target_url,
                        canonical,
                        classify_link(canonical),
                        target_url,
                        locator,
                        text,
                    )
                )
        try:
            annotations = page.get("/Annots", ())
            for annotation_reference in annotations:
                annotation = annotation_reference.get_object()
                action = annotation.get("/A")
                uri = action.get("/URI") if action else None
                if uri:
                    target_url = _extract_url(str(uri))
                    canonical = canonicalize_url(target_url)
                    if canonical:
                        links.append(
                            LinkOccurrence(
                                target_url,
                                canonical,
                                classify_link(canonical),
                                target_url,
                                locator,
                                text,
                            )
                        )
                elif annotation.get("/Dest"):
                    destination = str(annotation.get("/Dest"))
                    links.append(
                        LinkOccurrence(
                            f"#{destination}",
                            f"internal:{destination}",
                            "internal_anchor",
                            destination,
                            locator,
                            text,
                        )
                    )
        except Exception as exc:
            warnings.append(f"{locator}: 链接注释读取失败：{exc}")
    return ExtractedSource(
        title=path.stem,
        blocks=tuple(blocks),
        links=_deduplicate_links(links),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def extract_source(path: Path, ocr: _OcrCoordinator) -> ExtractedSource:
    suffix = path.suffix.casefold()
    if suffix == ".docx":
        return extract_docx(path, ocr)
    if suffix == ".xlsx":
        return extract_xlsx(path, ocr)
    if suffix == ".pptx":
        return extract_pptx(path, ocr)
    if suffix == ".pdf":
        return extract_pdf(path, ocr)
    if suffix in IMAGE_SOURCE_SUFFIXES:
        return extract_image(path, ocr)
    raise KnowledgeImportError(f"不支持的来源格式：{path.suffix}")


def _period_label(source_name: str) -> str:
    stem = Path(source_name).stem
    year_match = re.search(r"(?<!\d)(20\d{2})(?!\d)", stem)
    if year_match:
        year = year_match.group(1)
    else:
        short_year = re.match(r"^[【\[\s]*(\d{2})(?=\D)", stem)
        year = f"20{short_year.group(1)}" if short_year else ""
    seasons = "".join(dict.fromkeys(re.findall(r"[春夏秋冬]", stem)))
    if year and seasons:
        return f"{year}{seasons}"
    if year:
        return f"{year}周期待确认"
    if seasons:
        return f"年份待确认{seasons}"
    return "时期待确认"


def suggested_outputs(source_name: str) -> list[str]:
    period = _period_label(source_name)

    def policy(name: str) -> str:
        return f"policy/产品知识/{name}-{period}.txt"

    rules: list[tuple[tuple[str, ...], list[str]]] = [
        (("启蒙", "数学"), [policy("启蒙数学")]),
        (("启蒙", "语文"), [policy("启蒙语文")]),
        (("启蒙", "英语"), [policy("启蒙高阶英语")]),
        (("小学", "数学"), [policy("小学数学")]),
        (("小学", "语文"), [policy("小学语文")]),
        (("小学", "英语"), [policy("小学英语")]),
        (("初中", "数学"), [policy("初中数学")]),
        (("初中", "语文"), [policy("初中语文")]),
        (("初中", "英语"), [policy("初中英语")]),
        (("物理",), [policy("初中物理")]),
        (("化学",), [policy("初中化学")]),
        (
            ("文综",),
            [
                policy("初中历史"),
                policy("初中道法"),
                policy("初中生物"),
                policy("初中地理"),
            ],
        ),
        (
            ("常见", "Q&A"),
            [
                policy("课程共性问答"),
                "style_case/顾问沟通/课程重复与续报.txt",
                "style_case/顾问沟通/线上体验与课堂时长.txt",
                "style_case/顾问沟通/难度衔接与班型选择.txt",
                "style_case/顾问沟通/师资服务与学习效果.txt",
            ],
        ),
        (
            ("大升一",),
            [
                policy("大班升一年级课程衔接"),
                "style_case/顾问沟通/课程重复与续报.txt",
                "style_case/顾问沟通/难度衔接与班型选择.txt",
            ],
        ),
    ]
    for keywords, outputs in rules:
        if all(keyword.casefold() in source_name.casefold() for keyword in keywords):
            return outputs
    return []


def _schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS import_batches (
            batch_id TEXT PRIMARY KEY,
            source_dir TEXT NOT NULL,
            staging_dir TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            applied_at TEXT,
            report_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS source_files (
            id INTEGER PRIMARY KEY,
            source_root TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            name TEXT NOT NULL,
            file_format TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            approved_sha256 TEXT,
            size_bytes INTEGER NOT NULL,
            modified_ns INTEGER NOT NULL,
            title TEXT NOT NULL,
            review_status TEXT NOT NULL,
            excluded_reason TEXT NOT NULL DEFAULT '',
            last_seen_batch TEXT NOT NULL,
            approved_at TEXT,
            UNIQUE(source_root, relative_path)
        );
        CREATE INDEX IF NOT EXISTS source_files_sha256
            ON source_files(source_root, sha256);
        CREATE TABLE IF NOT EXISTS source_outputs (
            source_id INTEGER NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
            knowledge_path TEXT NOT NULL,
            PRIMARY KEY (source_id, knowledge_path)
        );
        CREATE TABLE IF NOT EXISTS source_aliases (
            source_id INTEGER NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
            canonical_key TEXT NOT NULL UNIQUE,
            source_url TEXT NOT NULL,
            PRIMARY KEY (source_id, canonical_key)
        );
        CREATE TABLE IF NOT EXISTS link_targets (
            id INTEGER PRIMARY KEY,
            canonical_key TEXT NOT NULL UNIQUE,
            target_url TEXT NOT NULL,
            target_type TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS source_link_edges (
            source_id INTEGER NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
            target_id INTEGER NOT NULL REFERENCES link_targets(id) ON DELETE CASCADE,
            locator TEXT NOT NULL,
            display_text TEXT NOT NULL,
            context TEXT NOT NULL,
            occurrence_count INTEGER NOT NULL,
            PRIMARY KEY (source_id, target_id, locator, display_text, context)
        );
        CREATE TABLE IF NOT EXISTS image_ocr_cache (
            sha256 TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            warning TEXT NOT NULL,
            width INTEGER NOT NULL,
            height INTEGER NOT NULL,
            recognized_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS source_revisions (
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL
                REFERENCES source_files(id) ON DELETE CASCADE,
            sha256 TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            status TEXT NOT NULL,
            extracted_at TEXT NOT NULL,
            approved_at TEXT,
            warning_json TEXT NOT NULL DEFAULT '[]',
            block_count INTEGER NOT NULL DEFAULT 0,
            text_char_count INTEGER NOT NULL DEFAULT 0,
            UNIQUE(source_id, sha256)
        );
        CREATE INDEX IF NOT EXISTS source_revisions_source_status
            ON source_revisions(source_id, status);
        CREATE TABLE IF NOT EXISTS source_blocks (
            id INTEGER PRIMARY KEY,
            revision_id INTEGER NOT NULL
                REFERENCES source_revisions(id) ON DELETE CASCADE,
            block_index INTEGER NOT NULL,
            block_key TEXT NOT NULL,
            locator TEXT NOT NULL,
            kind TEXT NOT NULL,
            text TEXT NOT NULL,
            audience TEXT NOT NULL DEFAULT 'pending',
            quality_status TEXT NOT NULL DEFAULT 'pending',
            authority TEXT NOT NULL DEFAULT 'reference',
            confidence REAL,
            warning TEXT NOT NULL DEFAULT '',
            UNIQUE(revision_id, block_index),
            UNIQUE(revision_id, block_key)
        );
        CREATE INDEX IF NOT EXISTS source_blocks_revision
            ON source_blocks(revision_id);
        CREATE INDEX IF NOT EXISTS source_blocks_review
            ON source_blocks(audience, quality_status);
        CREATE TABLE IF NOT EXISTS source_chunks (
            id INTEGER PRIMARY KEY,
            block_id INTEGER NOT NULL
                REFERENCES source_blocks(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            UNIQUE(block_id, chunk_index)
        );
        CREATE INDEX IF NOT EXISTS source_chunks_block
            ON source_chunks(block_id);
        CREATE VIRTUAL TABLE IF NOT EXISTS source_chunks_fts USING fts5(
            source_chunk_id UNINDEXED,
            source_id UNINDEXED,
            audience UNINDEXED,
            document_name,
            locator,
            terms
        );
        """
    )
    cache_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(image_ocr_cache)")
    }
    if "confidence" not in cache_columns:
        connection.execute(
            "ALTER TABLE image_ocr_cache ADD COLUMN confidence REAL"
        )


def _current_link_report(connection: sqlite3.Connection) -> LinkReport:
    external_filter = "lt.target_type <> 'internal_anchor'"
    occurrence_count = connection.execute(
        f"""
        SELECT COALESCE(SUM(edge.occurrence_count), 0)
        FROM source_link_edges AS edge
        JOIN source_files AS source ON source.id = edge.source_id
        JOIN link_targets AS lt ON lt.id = edge.target_id
        WHERE source.review_status <> 'missing' AND {external_filter}
        """
    ).fetchone()[0]
    unique_target_count = connection.execute(
        f"""
        SELECT COUNT(DISTINCT edge.target_id)
        FROM source_link_edges AS edge
        JOIN source_files AS source ON source.id = edge.source_id
        JOIN link_targets AS lt ON lt.id = edge.target_id
        WHERE source.review_status <> 'missing' AND {external_filter}
        """
    ).fetchone()[0]
    archived_target_count = connection.execute(
        f"""
        SELECT COUNT(DISTINCT edge.target_id)
        FROM source_link_edges AS edge
        JOIN source_files AS source ON source.id = edge.source_id
        JOIN link_targets AS lt ON lt.id = edge.target_id
        JOIN source_aliases AS alias ON alias.canonical_key = lt.canonical_key
        JOIN source_files AS target_source ON target_source.id = alias.source_id
        WHERE source.review_status <> 'missing'
          AND {external_filter}
          AND target_source.approved_sha256 IS NOT NULL
          AND (
            EXISTS (
                SELECT 1 FROM source_outputs AS output
                WHERE output.source_id = target_source.id
            )
            OR EXISTS (
                SELECT 1 FROM source_revisions AS revision
                WHERE revision.source_id = target_source.id
                  AND revision.status = 'approved'
            )
          )
        """
    ).fetchone()[0]
    advisor_target_count = connection.execute(
        f"""
        SELECT COUNT(DISTINCT edge.target_id)
        FROM source_link_edges AS edge
        JOIN source_files AS source ON source.id = edge.source_id
        JOIN link_targets AS lt ON lt.id = edge.target_id
        JOIN source_aliases AS alias ON alias.canonical_key = lt.canonical_key
        JOIN source_files AS target_source ON target_source.id = alias.source_id
        WHERE source.review_status <> 'missing'
          AND {external_filter}
          AND target_source.approved_sha256 IS NOT NULL
          AND (
            EXISTS (
                SELECT 1 FROM source_outputs AS output
                WHERE output.source_id = target_source.id
            )
            OR EXISTS (
                SELECT 1
                FROM source_revisions AS revision
                JOIN source_blocks AS block
                  ON block.revision_id = revision.id
                WHERE revision.source_id = target_source.id
                  AND revision.status = 'approved'
                  AND block.audience = 'advisor'
                  AND block.quality_status = 'approved'
            )
          )
        """
    ).fetchone()[0]
    internal_anchor_count = connection.execute(
        """
        SELECT COUNT(DISTINCT edge.target_id)
        FROM source_link_edges AS edge
        JOIN source_files AS source ON source.id = edge.source_id
        JOIN link_targets AS lt ON lt.id = edge.target_id
        WHERE source.review_status <> 'missing'
          AND lt.target_type = 'internal_anchor'
        """
    ).fetchone()[0]
    by_type = dict(
        connection.execute(
            """
            SELECT lt.target_type, COUNT(DISTINCT edge.target_id)
            FROM source_link_edges AS edge
            JOIN source_files AS source ON source.id = edge.source_id
            JOIN link_targets AS lt ON lt.id = edge.target_id
            WHERE source.review_status <> 'missing'
              AND lt.target_type <> 'internal_anchor'
            GROUP BY lt.target_type
            ORDER BY lt.target_type
            """
        ).fetchall()
    )
    return LinkReport(
        occurrence_count=int(occurrence_count),
        unique_target_count=int(unique_target_count),
        ingested_target_count=int(archived_target_count),
        missing_target_count=int(unique_target_count - archived_target_count),
        internal_anchor_count=int(internal_anchor_count),
        by_type={str(key): int(value) for key, value in by_type.items()},
        archived_target_count=int(archived_target_count),
        advisor_target_count=int(advisor_target_count),
        internal_only_target_count=int(
            archived_target_count - advisor_target_count
        ),
    )


def _current_missing_links(
    connection: sqlite3.Connection,
) -> list[dict[str, str | int]]:
    return [
        {
            "target_url": str(row["target_url"]),
            "canonical_key": str(row["canonical_key"]),
            "target_type": str(row["target_type"]),
            "occurrences": int(row["occurrences"]),
        }
        for row in connection.execute(
            """
            SELECT lt.target_url, lt.canonical_key, lt.target_type,
                   SUM(edge.occurrence_count) AS occurrences
            FROM link_targets AS lt
            JOIN source_link_edges AS edge ON edge.target_id = lt.id
            JOIN source_files AS source ON source.id = edge.source_id
            WHERE source.review_status <> 'missing'
              AND lt.target_type <> 'internal_anchor'
              AND NOT EXISTS (
                  SELECT 1
                  FROM source_aliases AS alias
                  JOIN source_files AS target_source
                    ON target_source.id = alias.source_id
                  WHERE alias.canonical_key = lt.canonical_key
                    AND target_source.approved_sha256 IS NOT NULL
                    AND (
                      EXISTS (
                        SELECT 1 FROM source_outputs AS output
                        WHERE output.source_id = target_source.id
                      )
                      OR EXISTS (
                        SELECT 1 FROM source_revisions AS revision
                        WHERE revision.source_id = target_source.id
                          AND revision.status = 'approved'
                      )
                    )
              )
            GROUP BY lt.id
            ORDER BY lt.target_type, lt.target_url
            """
        )
    ]


def _candidate_aliases(
    source_names: Iterable[str], links: Iterable[LinkOccurrence]
) -> dict[str, list[dict[str, str]]]:
    source_names = tuple(source_names)
    result: dict[str, list[dict[str, str]]] = {
        name: [] for name in source_names
    }
    normalized = {name: _normalized_title(Path(name).stem) for name in source_names}
    for link in links:
        titles = re.findall(r"《([^》]+)》", link.context)
        if not titles:
            continue
        for source_name, source_title in normalized.items():
            if any(_normalized_title(title) == source_title for title in titles):
                result[source_name].append(
                    {
                        "canonical_key": link.canonical_key,
                        "source_url": link.target_url,
                    }
                )
    for name, values in result.items():
        unique = {value["canonical_key"]: value for value in values}
        result[name] = list(unique.values())
    return result


def _write_extracted(path: Path, extracted: ExtractedSource) -> None:
    lines = [f"# {extracted.title}", ""]
    current_locator = ""
    for block in extracted.blocks:
        if block.locator != current_locator:
            current_locator = block.locator
            lines.extend((f"## {current_locator}", ""))
        label = {
            "table": "表格",
            "image_ocr": "图片 OCR",
            "spreadsheet_row": "表格行",
            "pdf_ocr": "页面 OCR",
        }.get(block.kind)
        if label:
            lines.append(f"[{label}]")
        lines.extend((block.text, ""))
    if extracted.warnings:
        lines.extend(("# 提取警告", ""))
        lines.extend(f"- {warning}" for warning in extracted.warnings)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def _replace_source_links(
    connection: sqlite3.Connection,
    source_id: int,
    links: Iterable[LinkOccurrence],
) -> None:
    connection.execute(
        "DELETE FROM source_link_edges WHERE source_id = ?", (source_id,)
    )
    grouped = Counter(
        (
            link.canonical_key,
            link.target_url,
            link.target_type,
            link.locator,
            link.display_text,
            link.context,
        )
        for link in links
    )
    for (
        canonical,
        target_url,
        target_type,
        locator,
        display_text,
        context,
    ), count in grouped.items():
        connection.execute(
            """
            INSERT INTO link_targets (
                canonical_key, target_url, target_type
            ) VALUES (?, ?, ?)
            ON CONFLICT(canonical_key) DO UPDATE SET
                target_url = excluded.target_url,
                target_type = excluded.target_type
            """,
            (canonical, target_url, target_type),
        )
        target_id = connection.execute(
            "SELECT id FROM link_targets WHERE canonical_key = ?", (canonical,)
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO source_link_edges (
                source_id, target_id, locator, display_text,
                context, occurrence_count
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                target_id,
                locator,
                display_text,
                context,
                count,
            ),
        )


def _store_ocr_pending(
    connection: sqlite3.Connection, ocr: _OcrCoordinator
) -> None:
    for digest, (text, warning, confidence, width, height) in ocr.pending.items():
        connection.execute(
            """
            INSERT OR REPLACE INTO image_ocr_cache (
                sha256, text, warning, width, height, recognized_at,
                confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                digest,
                text,
                warning,
                width,
                height,
                _utc_now(),
                confidence,
            ),
        )
    ocr.pending.clear()


def _block_key(index: int, block: ExtractedBlock) -> str:
    identity = f"{index}\0{block.locator}\0{block.kind}".encode("utf-8")
    return _bytes_hash(identity)


def _store_source_revision(
    connection: sqlite3.Connection,
    source_id: int,
    sha256: str,
    batch_id: str,
    extracted: ExtractedSource,
) -> int:
    existing = connection.execute(
        """
        SELECT id, status FROM source_revisions
        WHERE source_id = ? AND sha256 = ?
        """,
        (source_id, sha256),
    ).fetchone()
    if existing is not None and existing["status"] == "approved":
        return int(existing["id"])
    if existing is None:
        cursor = connection.execute(
            """
            INSERT INTO source_revisions (
                source_id, sha256, batch_id, status, extracted_at,
                warning_json, block_count, text_char_count
            ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (
                source_id,
                sha256,
                batch_id,
                _utc_now(),
                json.dumps(extracted.warnings, ensure_ascii=False),
                len(extracted.blocks),
                sum(len(block.text) for block in extracted.blocks),
            ),
        )
        revision_id = int(cursor.lastrowid)
    else:
        revision_id = int(existing["id"])
        connection.execute(
            """
            UPDATE source_revisions
            SET batch_id = ?, status = 'pending', extracted_at = ?,
                approved_at = NULL, warning_json = ?, block_count = ?,
                text_char_count = ?
            WHERE id = ?
            """,
            (
                batch_id,
                _utc_now(),
                json.dumps(extracted.warnings, ensure_ascii=False),
                len(extracted.blocks),
                sum(len(block.text) for block in extracted.blocks),
                revision_id,
            ),
        )
        connection.execute(
            "DELETE FROM source_blocks WHERE revision_id = ?",
            (revision_id,),
        )
    for index, block in enumerate(extracted.blocks):
        if (
            block.text
            and block.confidence is not None
            and block.confidence < MIN_TEXT_CONFIDENCE
        ):
            quality = "blocked"
        elif block.text:
            quality = "pending"
        elif block.warning:
            quality = "failed"
        else:
            quality = "no_text"
        cursor = connection.execute(
            """
            INSERT INTO source_blocks (
                revision_id, block_index, block_key, locator, kind, text,
                audience, quality_status, authority, confidence, warning
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, 'reference', ?, ?)
            """,
            (
                revision_id,
                index,
                _block_key(index, block),
                block.locator,
                block.kind,
                block.text,
                quality,
                block.confidence,
                block.warning,
            ),
        )
        block_id = int(cursor.lastrowid)
        if not block.text:
            continue
        searchable_text = _URL_PATTERN.sub("[链接]", block.text)
        chunks = chunk_block(SourceBlock(block.locator, searchable_text))
        connection.executemany(
            """
            INSERT INTO source_chunks (block_id, chunk_index, text)
            VALUES (?, ?, ?)
            """,
            (
                (block_id, chunk_index, chunk.text)
                for chunk_index, chunk in enumerate(chunks)
            ),
        )
    return revision_id


def _apply_source_review(
    connection: sqlite3.Connection,
    revision_id: int,
    decision: dict[str, Any],
) -> None:
    raw = decision.get("raw", {})
    if not isinstance(raw, dict):
        raise KnowledgeImportError("原文审核配置必须是对象")
    status = str(raw.get("status", "")).strip()
    if status == "deferred":
        return
    if status != "approved":
        raise KnowledgeImportError("原文必须标记为 approved 或 deferred")
    audience = str(raw.get("audience", "")).strip()
    if audience not in {"advisor", "internal"}:
        raise KnowledgeImportError("原文受众必须是 advisor 或 internal")
    authority = str(raw.get("authority", "reference")).strip()
    if authority not in {"primary", "reference"}:
        raise KnowledgeImportError("原文权威等级必须是 primary 或 reference")
    internal_locators = {
        str(value) for value in raw.get("internal_locators", [])
    }
    overrides = raw.get("block_overrides", {})
    if not isinstance(overrides, dict):
        raise KnowledgeImportError("原文块覆盖配置必须是对象")
    rows = connection.execute(
        """
        SELECT id, block_key, locator, kind, text, quality_status
        FROM source_blocks WHERE revision_id = ?
        """,
        (revision_id,),
    ).fetchall()
    for row in rows:
        block_audience = (
            "internal"
            if row["locator"] in internal_locators
            or row["kind"] == "revision_deleted"
            else audience
        )
        quality = row["quality_status"]
        if row["text"] and quality == "pending":
            quality = "approved"
        override = overrides.get(row["block_key"], {})
        if override:
            if not isinstance(override, dict):
                raise KnowledgeImportError("原文块覆盖值必须是对象")
            block_audience = str(
                override.get("audience", block_audience)
            )
            quality = str(override.get("quality_status", quality))
        if block_audience not in {"advisor", "internal"}:
            raise KnowledgeImportError("原文块受众无效")
        if quality not in {"approved", "no_text", "failed", "blocked"}:
            raise KnowledgeImportError("原文块质量状态无效")
        connection.execute(
            """
            UPDATE source_blocks
            SET audience = ?, quality_status = ?, authority = ?
            WHERE id = ?
            """,
            (block_audience, quality, authority, row["id"]),
        )
    source_id = connection.execute(
        "SELECT source_id FROM source_revisions WHERE id = ?",
        (revision_id,),
    ).fetchone()[0]
    connection.execute(
        """
        UPDATE source_revisions SET status = 'superseded'
        WHERE source_id = ? AND status = 'approved' AND id <> ?
        """,
        (source_id, revision_id),
    )
    connection.execute(
        """
        UPDATE source_revisions
        SET status = 'approved', approved_at = ? WHERE id = ?
        """,
        (_utc_now(), revision_id),
    )


def _rebuild_source_fts(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM source_chunks_fts")
    rows = connection.execute(
        """
        SELECT chunk.id AS chunk_id, revision.source_id,
               block.audience, source.name, block.locator, chunk.text
        FROM source_chunks AS chunk
        JOIN source_blocks AS block ON block.id = chunk.block_id
        JOIN source_revisions AS revision ON revision.id = block.revision_id
        JOIN source_files AS source ON source.id = revision.source_id
        WHERE revision.status = 'approved'
          AND block.quality_status = 'approved'
          AND block.audience IN ('advisor', 'internal')
        ORDER BY chunk.id
        """
    ).fetchall()
    connection.executemany(
        """
        INSERT INTO source_chunks_fts (
            source_chunk_id, source_id, audience,
            document_name, locator, terms
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            (
                row["chunk_id"],
                row["source_id"],
                row["audience"],
                " ".join(tokenize(row["name"])),
                " ".join(tokenize(row["locator"])),
                " ".join(tokenize(row["text"])),
            )
            for row in rows
        ),
    )


def _coverage_report(connection: sqlite3.Connection) -> CoverageReport:
    row = connection.execute(
        """
        SELECT
          COUNT(DISTINCT source.id) AS source_count,
          COUNT(DISTINCT revision.id) AS revision_count,
          COUNT(DISTINCT block.id) AS block_count,
          COALESCE(SUM(LENGTH(block.text)), 0) AS text_chars,
          COALESCE(SUM(CASE WHEN revision.status = 'approved'
                            AND block.audience = 'advisor'
                            AND block.quality_status = 'approved'
                       THEN LENGTH(block.text) ELSE 0 END), 0) AS searchable_chars,
          COUNT(DISTINCT CASE WHEN block.audience = 'advisor' THEN block.id END) AS advisor_blocks,
          COUNT(DISTINCT CASE WHEN block.audience = 'internal' THEN block.id END) AS internal_blocks,
          COUNT(DISTINCT CASE WHEN block.audience = 'pending' THEN block.id END) AS pending_blocks,
          COUNT(DISTINCT CASE WHEN block.quality_status = 'no_text' THEN block.id END) AS no_text_blocks,
          COUNT(DISTINCT CASE WHEN block.quality_status = 'failed' THEN block.id END) AS failed_blocks,
          COUNT(DISTINCT CASE WHEN block.quality_status = 'blocked' THEN block.id END) AS blocked_blocks,
          COUNT(DISTINCT CASE WHEN block.kind IN ('image_ocr', 'image_no_text') THEN block.id END) AS image_count,
          COUNT(DISTINCT CASE WHEN block.kind = 'image_ocr' THEN block.id END) AS image_ocr_count
        FROM source_files AS source
        LEFT JOIN source_revisions AS revision
          ON revision.source_id = source.id
         AND revision.status IN ('approved', 'pending')
        LEFT JOIN source_blocks AS block ON block.revision_id = revision.id
        """
    ).fetchone()
    by_kind = dict(
        connection.execute(
            """
            SELECT block.kind, COUNT(*)
            FROM source_blocks AS block
            JOIN source_revisions AS revision ON revision.id = block.revision_id
            WHERE revision.status IN ('approved', 'pending')
            GROUP BY block.kind ORDER BY block.kind
            """
        ).fetchall()
    )
    return CoverageReport(
        source_count=int(row["source_count"]),
        revision_count=int(row["revision_count"]),
        block_count=int(row["block_count"]),
        text_char_count=int(row["text_chars"]),
        searchable_char_count=int(row["searchable_chars"]),
        advisor_block_count=int(row["advisor_blocks"]),
        internal_block_count=int(row["internal_blocks"]),
        pending_block_count=int(row["pending_blocks"]),
        no_text_block_count=int(row["no_text_blocks"]),
        failed_block_count=int(row["failed_blocks"]),
        blocked_block_count=int(row["blocked_blocks"]),
        image_count=int(row["image_count"]),
        image_ocr_count=int(row["image_ocr_count"]),
        by_kind={str(key): int(value) for key, value in by_kind.items()},
    )


def _current_quality_issues(
    connection: sqlite3.Connection,
) -> list[dict[str, Any]]:
    return [
        {
            "source": str(row["source"]),
            "locator": str(row["locator"]),
            "kind": str(row["kind"]),
            "quality_status": str(row["quality_status"]),
            "warning": str(row["warning"] or ""),
            "preview": str(row["text"])[:160],
        }
        for row in connection.execute(
            """
            SELECT source.name AS source, block.locator, block.kind,
                   block.quality_status, block.warning, block.text
            FROM source_blocks AS block
            JOIN source_revisions AS revision
              ON revision.id = block.revision_id
            JOIN source_files AS source ON source.id = revision.source_id
            WHERE revision.status IN ('approved', 'pending')
              AND block.quality_status IN ('blocked', 'failed')
            ORDER BY source.name, block.block_index
            """
        )
    ]


def _write_report(
    path: Path,
    batch: dict[str, Any],
    link_report: LinkReport,
) -> None:
    summary = batch["summary"]
    coverage = batch.get("coverage_report", {})
    lines = [
        f"# 知识导入审核报告：{batch['batch_id']}",
        "",
        "## 文件增量",
        "",
        f"- 新增：{summary['new']} 个",
        f"- 修改：{summary['changed']} 个",
        f"- 未变化：{summary['unchanged']} 个",
        f"- 来源缺失：{summary['missing']} 个",
        f"- 提取失败：{summary['failed']} 个",
        f"- 需转换旧格式：{len(batch.get('unsupported_files', []))} 个",
        "",
        "## 原文覆盖",
        "",
        f"- 来源：{coverage.get('source_count', 0)} 个",
        f"- 修订：{coverage.get('revision_count', 0)} 个",
        f"- 内容块：{coverage.get('block_count', 0)} 个",
        f"- 原文字符：{coverage.get('text_char_count', 0)}",
        f"- 顾问可检索字符：{coverage.get('searchable_char_count', 0)}",
        f"- 图片对象：{coverage.get('image_count', 0)} 个",
        f"- 图片 OCR 有文字：{coverage.get('image_ocr_count', 0)} 个",
        f"- 待审核块：{coverage.get('pending_block_count', 0)} 个",
        f"- 无文字块：{coverage.get('no_text_block_count', 0)} 个",
        f"- 失败块：{coverage.get('failed_block_count', 0)} 个",
        f"- 已阻断块：{coverage.get('blocked_block_count', 0)} 个",
        "",
        "## 提取与 OCR 警告",
        "",
    ]
    extraction_warnings = [
        (str(source["relative_path"]), str(warning))
        for source in batch["sources"]
        for warning in source.get("warnings", [])
    ]
    lines.extend(
        (
            f"- {relative_path}：{warning}"
            for relative_path, warning in extraction_warnings
        )
        if extraction_warnings
        else ["- 无"]
    )
    lines.extend(("", "## 阻断与失败对象", ""))
    quality_issues = batch.get("quality_issues", [])
    lines.extend(
        (
            f"- [{item['quality_status']}] {item['source']}｜"
            f"{item['locator']}｜{item['kind']}："
            f"{item.get('warning') or item.get('preview') or '无文字说明'}"
            for item in quality_issues
        )
        if quality_issues
        else ["- 无"]
    )
    lines.extend(
        [
            "",
            "## 引用资料",
            "",
            f"- 引用次数：{link_report.occurrence_count}",
            f"- 唯一资料：{link_report.unique_target_count}",
            f"- 已入库资料：{link_report.ingested_target_count}",
            f"- 已归档资料：{link_report.archived_target_count}",
            f"- 顾问可用资料：{link_report.advisor_target_count}",
            f"- 仅内部资料：{link_report.internal_only_target_count}",
            f"- 未入库资料：{link_report.missing_target_count}",
            f"- 内部锚点：{link_report.internal_anchor_count}",
            "- 类型："
            + "，".join(
                f"{kind}={count}"
                for kind, count in link_report.by_type.items()
            ),
            "",
            "## 来源审核记录",
            "",
        ]
    )
    for source in batch["sources"]:
        if not source.get("requires_review", False):
            continue
        lines.append(
            f"- {source['relative_path']}：{source['change']}；"
            f"建议输出 {', '.join(source['suggested_outputs']) or '待分类'}；"
            f"警告 {len(source.get('warnings', []))} 条"
        )
    if batch.get("unsupported_files"):
        lines.extend(("", "## 需转换的旧格式", ""))
        lines.extend(f"- {value}" for value in batch["unsupported_files"])
    lines.extend(("", "## 未入库资料明细", ""))
    for item in batch["missing_links"]:
        lines.append(
            f"- [{item['target_type']}] {item['target_url']} "
            f"（引用 {item['occurrences']} 次）"
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


class KnowledgeImportService:
    def __init__(
        self,
        knowledge_dir: Path,
        database_path: Path,
        staging_dir: Path,
        ocr_engine: DocumentOcr | None = None,
        excluded_source_parts: Iterable[str] = DEFAULT_EXCLUDED_SOURCE_PARTS,
    ) -> None:
        self.knowledge_dir = knowledge_dir
        self.database_path = database_path
        self.staging_dir = staging_dir
        self.ocr_engine = ocr_engine
        self.excluded_source_parts = {
            str(value).casefold() for value in excluded_source_parts
        }

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        _schema(connection)
        return connection

    def link_report(self) -> LinkReport:
        with self._connect() as connection:
            return _current_link_report(connection)

    def coverage_report(self) -> CoverageReport:
        with self._connect() as connection:
            return _coverage_report(connection)

    def _is_excluded(self, path: Path, source_dir: Path) -> bool:
        relative = path.relative_to(source_dir)
        return any(
            part.casefold() in self.excluded_source_parts
            for part in relative.parts[:-1]
        )

    def prepare(
        self, source_dir: Path, *, resume_batch_id: str | None = None
    ) -> PrepareReport:
        source_dir = source_dir.resolve()
        if not source_dir.is_dir():
            raise KnowledgeImportError(f"来源目录不存在：{source_dir}")
        candidates = sorted(
            path
            for path in source_dir.rglob("*")
            if path.is_file() and not self._is_excluded(path, source_dir)
        )
        files = [
            path
            for path in candidates
            if path.suffix.casefold() in SUPPORTED_SOURCE_SUFFIXES
        ]
        unsupported_files = [
            path.relative_to(source_dir).as_posix()
            for path in candidates
            if path.suffix.casefold() in LEGACY_SOURCE_SUFFIXES
        ]
        batch_id = resume_batch_id or (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:8]
        )
        batch_dir = self.staging_dir.resolve() / batch_id
        extracted_dir = batch_dir / "extracted"
        draft_dir = batch_dir / "draft" / "knowledge"
        if resume_batch_id:
            if not batch_dir.is_dir():
                raise KnowledgeImportError(f"待继续批次不存在：{batch_id}")
        else:
            batch_dir.mkdir(parents=True, exist_ok=False)
        extracted_dir.mkdir(parents=True, exist_ok=True)
        draft_dir.mkdir(parents=True, exist_ok=True)
        progress_path = batch_dir / "progress.json"
        source_root = str(source_dir)
        if progress_path.is_file():
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
            if Path(progress.get("source_dir", "")).resolve() != source_dir:
                raise KnowledgeImportError(
                    f"批次来源目录不一致：{progress.get('source_dir')}"
                )
        else:
            progress = {
                "batch_id": batch_id,
                "source_dir": source_root,
                "created_at": _utc_now(),
                "status": "preparing",
                "files": {},
            }
        batch_sources: list[dict[str, Any]] = []
        changed_records: list[tuple[int, Path, str, str, bool]] = []
        summary = Counter()

        with self._connect() as connection:
            cached = {
                row["sha256"]: (
                    row["text"],
                    row["warning"],
                    row["confidence"],
                )
                for row in connection.execute(
                    "SELECT sha256, text, warning, confidence FROM image_ocr_cache"
                )
            }
            ocr = _OcrCoordinator(self.ocr_engine, cached)
            for path in files:
                relative_path = path.relative_to(source_dir).as_posix()
                digest = _file_hash(path)
                stat = path.stat()
                extracted_name = _safe_name(relative_path) + ".txt"
                extracted_path = extracted_dir / extracted_name
                progress_entry = progress["files"].get(relative_path)
                row = connection.execute(
                    """
                    SELECT * FROM source_files
                    WHERE source_root = ? AND relative_path = ?
                    """,
                    (source_root, relative_path),
                ).fetchone()
                if row is None:
                    row = connection.execute(
                        """
                        SELECT * FROM source_files
                        WHERE source_root = ? AND sha256 = ?
                        ORDER BY id LIMIT 1
                        """,
                        (source_root, digest),
                    ).fetchone()
                if (
                    progress_entry
                    and progress_entry.get("sha256") == digest
                    and progress_entry.get("change") in {"new", "changed", "unchanged"}
                ):
                    change = progress_entry["change"]
                elif row is None:
                    change = "new"
                else:
                    change = "unchanged" if row["sha256"] == digest else "changed"
                if (
                    row is not None
                    and row["approved_sha256"] is None
                    and row["review_status"] in {"staged", "failed"}
                ):
                    change = "new"
                    if progress_entry is not None:
                        progress_entry["change"] = change

                if row is None:
                    cursor = connection.execute(
                        """
                        INSERT INTO source_files (
                            source_root, relative_path, name, file_format,
                            sha256, size_bytes, modified_ns, title,
                            review_status, last_seen_batch
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'staged', ?)
                        """,
                        (
                            source_root,
                            relative_path,
                            path.name,
                            path.suffix.casefold().removeprefix("."),
                            digest,
                            stat.st_size,
                            stat.st_mtime_ns,
                            path.stem,
                            batch_id,
                        ),
                    )
                    source_id = int(cursor.lastrowid)
                else:
                    source_id = int(row["id"])
                    review_status = row["review_status"]
                    if change == "changed":
                        review_status = "changes_pending"
                    elif change == "new":
                        review_status = "staged"
                    connection.execute(
                        """
                        UPDATE source_files
                        SET relative_path = ?, name = ?, file_format = ?,
                            sha256 = ?, size_bytes = ?, modified_ns = ?,
                            title = ?, review_status = ?, last_seen_batch = ?
                        WHERE id = ?
                        """,
                        (
                            relative_path,
                            path.name,
                            path.suffix.casefold().removeprefix("."),
                            digest,
                            stat.st_size,
                            stat.st_mtime_ns,
                            path.stem,
                            review_status,
                            batch_id,
                            source_id,
                        ),
                    )
                summary[change] += 1
                reuse_extracted = bool(
                    resume_batch_id and extracted_path.is_file()
                )
                if progress_entry is None or progress_entry.get("sha256") != digest:
                    progress_entry = {
                        "sha256": digest,
                        "change": change,
                        "status": "completed" if reuse_extracted else "pending",
                        "db_checkpoint": False,
                        "extracted_file": (
                            extracted_path.relative_to(batch_dir).as_posix()
                            if reuse_extracted
                            else ""
                        ),
                        "warnings": [],
                    }
                    progress["files"][relative_path] = progress_entry
                source_record: dict[str, Any] = {
                    "source_id": source_id,
                    "relative_path": relative_path,
                    "name": path.name,
                    "sha256": digest,
                    "change": change,
                    "suggested_outputs": suggested_outputs(path.name),
                    "warnings": list(progress_entry.get("warnings", [])),
                    "extracted_file": str(
                        progress_entry.get("extracted_file", "")
                    ),
                }
                revision_row = connection.execute(
                    """
                    SELECT id, status FROM source_revisions
                    WHERE source_id = ? AND sha256 = ?
                    """,
                    (source_id, digest),
                ).fetchone()
                revision_needed = revision_row is None
                source_record["requires_review"] = (
                    change in {"new", "changed", "failed"}
                    or revision_needed
                    or (
                        revision_row is not None
                        and revision_row["status"] != "approved"
                    )
                )
                source_record["revision_id"] = (
                    int(revision_row["id"]) if revision_row is not None else None
                )
                source_record["revision_needed"] = revision_needed
                if (
                    (change in {"new", "changed"} or revision_needed)
                    and not progress_entry.get("db_checkpoint", False)
                ):
                    changed_records.append(
                        (
                            source_id,
                            path,
                            relative_path,
                            change,
                            reuse_extracted,
                        )
                    )
                batch_sources.append(source_record)

            missing_rows = connection.execute(
                """
                SELECT id FROM source_files
                WHERE source_root = ? AND last_seen_batch <> ?
                  AND review_status <> 'missing'
                """,
                (source_root, batch_id),
            ).fetchall()
            summary["missing"] = len(missing_rows)
            connection.execute(
                """
                UPDATE source_files SET review_status = 'missing'
                WHERE source_root = ? AND last_seen_batch <> ?
                """,
                (source_root, batch_id),
            )
            connection.execute(
                """
                INSERT INTO import_batches (
                    batch_id, source_dir, staging_dir, status,
                    created_at, report_json
                ) VALUES (?, ?, ?, 'preparing', ?, '{}')
                ON CONFLICT(batch_id) DO UPDATE SET
                    source_dir = excluded.source_dir,
                    staging_dir = excluded.staging_dir,
                    status = 'preparing'
                """,
                (
                    batch_id,
                    source_root,
                    str(batch_dir),
                    progress["created_at"],
                ),
            )
            connection.commit()
            _write_json_atomic(progress_path, progress)

            records_by_id = {item["source_id"]: item for item in batch_sources}
            for (
                source_id,
                path,
                relative_path,
                change,
                reuse_extracted,
            ) in changed_records:
                record = records_by_id[source_id]
                try:
                    if reuse_extracted:
                        extracted = extract_source(
                            path,
                            _OcrCoordinator(None, cached, skip_images=True),
                        )
                    else:
                        extracted = extract_source(path, ocr)
                except KnowledgeImportError as exc:
                    record["change"] = "failed"
                    record["warnings"] = [str(exc)]
                    summary[change] -= 1
                    summary["failed"] += 1
                    connection.execute(
                        "UPDATE source_files SET review_status = 'failed' WHERE id = ?",
                        (source_id,),
                    )
                    progress_entry = progress["files"][relative_path]
                    progress_entry["status"] = "failed"
                    progress_entry["warnings"] = [str(exc)]
                    connection.commit()
                    _write_json_atomic(progress_path, progress)
                    continue
                extracted_name = _safe_name(relative_path) + ".txt"
                extracted_path = extracted_dir / extracted_name
                if not reuse_extracted:
                    _write_extracted(extracted_path, extracted)
                record["extracted_file"] = extracted_path.relative_to(batch_dir).as_posix()
                if not reuse_extracted:
                    record["warnings"] = list(extracted.warnings)
                revision_id = _store_source_revision(
                    connection,
                    source_id,
                    record["sha256"],
                    batch_id,
                    extracted,
                )
                record["revision_id"] = revision_id
                record["revision_needed"] = False
                _replace_source_links(connection, source_id, extracted.links)
                _store_ocr_pending(connection, ocr)
                connection.commit()
                progress_entry = progress["files"][relative_path]
                progress_entry.update(
                    {
                        "status": "completed",
                        "db_checkpoint": True,
                        "extracted_file": record["extracted_file"],
                        "warnings": record["warnings"],
                        "revision_id": revision_id,
                    }
                )
                _write_json_atomic(progress_path, progress)

            link_report = _current_link_report(connection)
            missing_links = _current_missing_links(connection)
            indexed_links = [
                LinkOccurrence(
                    row["target_url"],
                    row["canonical_key"],
                    row["target_type"],
                    row["display_text"],
                    row["locator"],
                    row["context"],
                )
                for row in connection.execute(
                    """
                    SELECT lt.target_url, lt.canonical_key, lt.target_type,
                           edge.display_text, edge.locator, edge.context
                    FROM source_link_edges AS edge
                    JOIN source_files AS source ON source.id = edge.source_id
                    JOIN link_targets AS lt ON lt.id = edge.target_id
                    WHERE source.review_status <> 'missing'
                    """
                )
            ]
            aliases = _candidate_aliases(
                (item["relative_path"] for item in batch_sources),
                indexed_links,
            )
            decisions: dict[str, Any] = {}
            base_hashes: dict[str, str | None] = {}
            for source in batch_sources:
                if not source.get("requires_review", False):
                    continue
                existing_outputs = [
                    str(row[0])
                    for row in connection.execute(
                        """
                        SELECT knowledge_path FROM source_outputs
                        WHERE source_id = ? ORDER BY knowledge_path
                        """,
                        (source["source_id"],),
                    )
                ]
                existing_aliases = [
                    {
                        "canonical_key": str(row[0]),
                        "source_url": str(row[1]),
                    }
                    for row in connection.execute(
                        """
                        SELECT canonical_key, source_url FROM source_aliases
                        WHERE source_id = ? ORDER BY canonical_key
                        """,
                        (source["source_id"],),
                    )
                ]
                locator_candidates: list[dict[str, str | int]] = []
                block_candidates: list[dict[str, Any]] = []
                suggested_internal: list[str] = []
                revision_id = source.get("revision_id")
                if revision_id is not None:
                    locator_candidates = [
                        {
                            "locator": str(row["locator"]),
                            "blocks": int(row["blocks"]),
                            "characters": int(row["characters"]),
                        }
                        for row in connection.execute(
                            """
                            SELECT locator, COUNT(*) AS blocks,
                                   SUM(LENGTH(text)) AS characters
                            FROM source_blocks WHERE revision_id = ?
                            GROUP BY locator ORDER BY MIN(block_index)
                            """,
                            (revision_id,),
                        )
                    ]
                    block_candidates = [
                        {
                            "block_key": str(row["block_key"]),
                            "locator": str(row["locator"]),
                            "kind": str(row["kind"]),
                            "characters": len(str(row["text"])),
                            "preview": str(row["text"])[:240],
                            "audience": str(row["audience"]),
                            "quality_status": str(row["quality_status"]),
                            "confidence": row["confidence"],
                            "warning": str(row["warning"] or ""),
                        }
                        for row in connection.execute(
                            """
                            SELECT block_key, locator, kind, text, audience,
                                   quality_status, confidence, warning
                            FROM source_blocks WHERE revision_id = ?
                            ORDER BY block_index
                            """,
                            (revision_id,),
                        )
                    ]
                    internal_terms = (
                        "内部",
                        "负责人",
                        "业务指标",
                        "培训排期",
                        "转化率",
                        "续报率",
                        "销售目标",
                        "业绩目标",
                    )
                    suggested_internal = [
                        str(row["locator"])
                        for row in connection.execute(
                            """
                            SELECT DISTINCT locator, text
                            FROM source_blocks WHERE revision_id = ?
                            """,
                            (revision_id,),
                        )
                        if any(
                            term in f"{row['locator']} {row['text']}"
                            for term in internal_terms
                        )
                    ]
                decisions[source["relative_path"]] = {
                    "outputs": existing_outputs,
                    "excluded_reason": "",
                    "alias_candidates": aliases.get(source["relative_path"], []),
                    "aliases": existing_aliases,
                    "raw": {
                        "status": "pending",
                        "audience": "",
                        "authority": "reference",
                        "internal_locators": [],
                        "suggested_internal_locators": list(
                            dict.fromkeys(suggested_internal)
                        ),
                        "locator_candidates": locator_candidates,
                        "block_candidates": block_candidates,
                        "block_overrides": {},
                    },
                }
                for output in (
                    existing_outputs or source["suggested_outputs"]
                ):
                    output_path = self.knowledge_dir / output
                    base_hashes[output] = (
                        _file_hash(output_path) if output_path.is_file() else None
                    )
                    draft_path = draft_dir / output
                    if output_path.is_file() and not draft_path.exists():
                        draft_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(output_path, draft_path)

            batch = {
                "batch_id": batch_id,
                "source_dir": source_root,
                "created_at": progress["created_at"],
                "summary": {
                    "new": summary["new"],
                    "changed": summary["changed"],
                    "unchanged": summary["unchanged"],
                    "missing": summary["missing"],
                    "failed": summary["failed"],
                },
                "sources": batch_sources,
                "knowledge_base_hashes": base_hashes,
                "missing_links": missing_links,
                "link_report": asdict(link_report),
                "unsupported_files": unsupported_files,
                "coverage_report": asdict(_coverage_report(connection)),
                "quality_issues": _current_quality_issues(connection),
            }
            batch_path = batch_dir / "batch.json"
            review_path = batch_dir / "review.json"
            report_path = batch_dir / "report.md"
            _write_json_atomic(batch_path, batch)
            _write_json_atomic(review_path, {"decisions": decisions})
            _write_report(report_path, batch, link_report)
            connection.execute(
                """
                UPDATE import_batches
                SET status = 'prepared', report_json = ?
                WHERE batch_id = ?
                """,
                (
                    json.dumps(asdict(link_report), ensure_ascii=False),
                    batch_id,
                ),
            )
            progress["status"] = "prepared"
            _write_json_atomic(progress_path, progress)

        return PrepareReport(
            batch_id=batch_id,
            new_count=summary["new"],
            changed_count=summary["changed"],
            unchanged_count=summary["unchanged"],
            missing_source_count=summary["missing"],
            failed_count=summary["failed"],
            link_report=link_report,
            review_path=review_path,
            report_path=report_path,
        )

    def resume(self, batch_id: str, source_dir: Path | None = None) -> PrepareReport:
        batch_dir = self.staging_dir.resolve() / batch_id
        progress_path = batch_dir / "progress.json"
        if progress_path.is_file():
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
            recorded_source = Path(progress["source_dir"])
        else:
            recorded_source = source_dir or Path()
        if source_dir is not None and recorded_source.resolve() != source_dir.resolve():
            raise KnowledgeImportError("继续批次时指定的来源目录与原批次不一致")
        if not str(recorded_source):
            raise KnowledgeImportError("旧批次缺少来源目录，请显式指定")
        return self.prepare(recorded_source, resume_batch_id=batch_id)

    def apply(self, batch_id: str) -> ApplyReport:
        batch_dir = self.staging_dir.resolve() / batch_id
        batch_path = batch_dir / "batch.json"
        review_path = batch_dir / "review.json"
        if not batch_path.is_file() or not review_path.is_file():
            raise KnowledgeImportError(f"导入批次不存在：{batch_id}")
        batch = json.loads(batch_path.read_text(encoding="utf-8"))
        review = json.loads(review_path.read_text(encoding="utf-8"))
        with self._connect() as connection:
            batch_row = connection.execute(
                "SELECT status FROM import_batches WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
            if batch_row is None:
                raise KnowledgeImportError(f"数据库中不存在批次：{batch_id}")
            if batch_row["status"] == "applied":
                raise KnowledgeImportError(f"批次已经应用：{batch_id}")
        decisions = review.get("decisions", {})
        source_records = {
            item["relative_path"]: item for item in batch["sources"]
        }
        output_sources: dict[str, set[str]] = {}
        for relative_path, source in source_records.items():
            if not source.get("requires_review", False):
                continue
            decision = decisions.get(relative_path)
            if not isinstance(decision, dict):
                raise KnowledgeImportError(f"来源尚未审核：{relative_path}")
            outputs = decision.get("outputs", [])
            excluded_reason = str(decision.get("excluded_reason", "")).strip()
            raw = decision.get("raw", {})
            if not isinstance(raw, dict):
                raise KnowledgeImportError(
                    f"原文审核配置无效：{relative_path}"
                )
            raw_status = str(raw.get("status", "")).strip()
            if raw_status not in {"approved", "deferred"}:
                raise KnowledgeImportError(
                    f"来源尚未完成原文审核：{relative_path}"
                )
            if raw_status == "approved" and source.get("revision_id") is None:
                raise KnowledgeImportError(
                    f"来源缺少可应用的原文修订：{relative_path}"
                )
            if source["change"] == "failed" and not excluded_reason:
                raise KnowledgeImportError(
                    f"提取失败来源必须说明排除原因：{relative_path}"
                )
            if (
                not outputs
                and not excluded_reason
                and raw_status not in {"approved", "deferred"}
            ):
                raise KnowledgeImportError(
                    f"来源必须指定知识输出或排除原因：{relative_path}"
                )
            for output in outputs:
                relative_output = Path(output)
                if (
                    relative_output.is_absolute()
                    or not relative_output.parts
                    or relative_output.parts[0] not in {"policy", "style_case"}
                    or ".." in relative_output.parts
                ):
                    raise KnowledgeImportError(f"无效知识输出路径：{output}")
                draft = batch_dir / "draft" / "knowledge" / relative_output
                if not draft.is_file():
                    raise KnowledgeImportError(f"知识草稿不存在：{draft}")
                output_sources.setdefault(relative_output.as_posix(), set()).add(
                    relative_path
                )

        backups: dict[Path, bytes | None] = {}
        copied: list[Path] = []
        for output in output_sources:
            target = self.knowledge_dir / output
            expected = batch["knowledge_base_hashes"].get(output)
            current = _file_hash(target) if target.is_file() else None
            if output not in batch["knowledge_base_hashes"] and target.exists():
                raise KnowledgeImportError(
                    f"批次准备后新增了同名知识文件，拒绝覆盖：{target}"
                )
            if current != expected:
                raise KnowledgeImportError(
                    f"知识文件在批次准备后已变化，拒绝覆盖：{target}"
                )
            backups[target] = target.read_bytes() if target.is_file() else None
            target.parent.mkdir(parents=True, exist_ok=True)
            draft = batch_dir / "draft" / "knowledge" / output
            temporary = target.with_suffix(target.suffix + f".{batch_id}.tmp")
            shutil.copyfile(draft, temporary)
            temporary.replace(target)
            copied.append(target)

        knowledge = KnowledgeBase(self.knowledge_dir, self.database_path)
        try:
            rebuild = knowledge.rebuild()
        except Exception as exc:
            for target, backup in backups.items():
                if backup is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(backup)
            try:
                knowledge.rebuild()
            except Exception:
                pass
            if isinstance(exc, KnowledgeError):
                raise KnowledgeImportError(str(exc)) from exc
            raise

        with self._connect() as connection:
            for relative_path, decision in decisions.items():
                source = source_records[relative_path]
                source_id = int(source["source_id"])
                outputs = [str(value) for value in decision.get("outputs", [])]
                excluded_reason = str(
                    decision.get("excluded_reason", "")
                ).strip()
                raw = decision.get("raw", {})
                raw_status = str(raw.get("status", "")).strip()
                if raw_status == "deferred":
                    connection.execute(
                        """
                        UPDATE source_files
                        SET review_status = ?, excluded_reason = ?
                        WHERE id = ?
                        """,
                        (
                            "excluded" if excluded_reason else "deferred",
                            excluded_reason,
                            source_id,
                        ),
                    )
                    continue
                revision_id = int(source["revision_id"])
                _apply_source_review(
                    connection, revision_id, decision
                )
                connection.execute(
                    "DELETE FROM source_outputs WHERE source_id = ?",
                    (source_id,),
                )
                connection.execute(
                    "DELETE FROM source_aliases WHERE source_id = ?",
                    (source_id,),
                )
                if outputs:
                    connection.executemany(
                        """
                        INSERT INTO source_outputs (source_id, knowledge_path)
                        VALUES (?, ?)
                        """,
                        ((source_id, output) for output in outputs),
                    )
                connection.execute(
                    """
                    UPDATE source_files
                    SET approved_sha256 = ?, review_status = 'approved',
                        excluded_reason = ?, approved_at = ?
                    WHERE id = ?
                    """,
                    (
                        source["sha256"],
                        excluded_reason,
                        _utc_now(),
                        source_id,
                    ),
                )
                aliases = decision.get("aliases", [])
                for alias in aliases:
                    canonical = str(alias.get("canonical_key", "")).strip()
                    source_url = str(alias.get("source_url", "")).strip()
                    if not canonical or not source_url:
                        raise KnowledgeImportError(
                            f"来源别名无效：{relative_path}"
                        )
                    connection.execute(
                        """
                        INSERT INTO source_aliases (
                            source_id, canonical_key, source_url
                        ) VALUES (?, ?, ?)
                        ON CONFLICT(canonical_key) DO UPDATE SET
                            source_id = excluded.source_id,
                            source_url = excluded.source_url
                        """,
                        (source_id, canonical, source_url),
                    )
            _rebuild_source_fts(connection)
            link_report = _current_link_report(connection)
            batch["missing_links"] = _current_missing_links(connection)
            batch["link_report"] = asdict(link_report)
            batch["coverage_report"] = asdict(_coverage_report(connection))
            batch["quality_issues"] = _current_quality_issues(connection)
            _write_json_atomic(batch_path, batch)
            _write_report(batch_dir / "report.md", batch, link_report)
            connection.execute(
                """
                UPDATE import_batches
                SET status = 'applied', applied_at = ?, report_json = ?
                WHERE batch_id = ?
                """,
                (
                    _utc_now(),
                    json.dumps(asdict(link_report), ensure_ascii=False),
                    batch_id,
                ),
            )
        staging_root = self.staging_dir.resolve()
        resolved_batch_dir = batch_dir.resolve()
        for temporary_name in ("extracted", "draft"):
            temporary_dir = (batch_dir / temporary_name).resolve()
            if (
                temporary_dir.is_dir()
                and temporary_dir.parent == resolved_batch_dir
                and resolved_batch_dir.is_relative_to(staging_root)
            ):
                shutil.rmtree(temporary_dir)
        return ApplyReport(
            batch_id=batch_id,
            output_count=len(copied),
            indexed_document_count=rebuild.document_count,
            indexed_chunk_count=rebuild.chunk_count,
            link_report=link_report,
        )


def format_link_report(report: LinkReport) -> str:
    types = "，".join(
        f"{kind}={count}" for kind, count in report.by_type.items()
    ) or "无"
    return (
        f"链接引用 {report.occurrence_count} 次，"
        f"唯一资料 {report.unique_target_count} 份，"
        f"已入库 {report.ingested_target_count} 份，"
        f"其中顾问可用 {report.advisor_target_count} 份、"
        f"仅内部 {report.internal_only_target_count} 份，"
        f"未入库 {report.missing_target_count} 份，"
        f"内部锚点 {report.internal_anchor_count} 个；类型：{types}"
    )


def format_coverage_report(report: CoverageReport) -> str:
    kinds = "，".join(
        f"{kind}={count}" for kind, count in report.by_kind.items()
    ) or "无"
    return (
        f"来源 {report.source_count} 个，修订 {report.revision_count} 个，"
        f"内容块 {report.block_count} 个，原文 {report.text_char_count} 字符，"
        f"顾问可检索 {report.searchable_char_count} 字符；"
        f"顾问块 {report.advisor_block_count} 个、"
        f"内部块 {report.internal_block_count} 个、"
        f"待审核块 {report.pending_block_count} 个、"
        f"无文字块 {report.no_text_block_count} 个、"
        f"失败块 {report.failed_block_count} 个；"
        f"已阻断块 {report.blocked_block_count} 个；"
        f"图片 {report.image_count} 个，其中 OCR 有文字 "
        f"{report.image_ocr_count} 个；类型：{kinds}"
    )
