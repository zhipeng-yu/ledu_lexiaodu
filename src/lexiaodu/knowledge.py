from __future__ import annotations

import hashlib
import math
import re
import sqlite3
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from importlib import import_module
from pathlib import Path
from xml.etree import ElementTree

from lexiaodu.knowledge_semantics import (
    query_semantic_filters,
    requests_campaign_information,
    requests_class_selection,
    requests_enrollment_rules,
    requests_internal_information,
    requests_national_tianjin_compatibility,
    requests_online_course_service,
    requests_out_of_scope_region,
    requests_product_overview,
    requests_teacher_information,
    requires_live_system_lookup,
    semantic_row_matches,
)


SUPPORTED_SUFFIXES = {".txt", ".docx", ".pdf"}
DEFAULT_CHUNK_SIZE = 500
MAX_SEARCH_RESULTS = 3
MAX_ADVICE_RESULTS = 5
_WORD_NAMESPACE = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
}
_WORD_VALUE = f"{{{_WORD_NAMESPACE['w']}}}val"
_HEADING_PATTERN = re.compile(
    r"^(?:#{1,6}\s+|第[一二三四五六七八九十百千万零〇\d]+[章节篇部]\s*)"
)
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]+", re.IGNORECASE)


class KnowledgeError(RuntimeError):
    """Raised when the local knowledge index cannot be built or queried."""


class KnowledgeType(StrEnum):
    POLICY = "policy"
    STYLE_CASE = "style_case"
    SOURCE = "source"


@dataclass(frozen=True, slots=True)
class SourceBlock:
    locator: str
    text: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    knowledge_type: KnowledgeType
    document_name: str
    locator: str
    evidence: str
    score: float
    source_tier: str = "curated"
    authority: str = "primary"


@dataclass(frozen=True, slots=True)
class RebuildReport:
    document_count: int
    chunk_count: int
    ignored_file_count: int


@dataclass(frozen=True, slots=True)
class _IndexedDocument:
    path: Path
    relative_path: str
    knowledge_type: KnowledgeType
    file_format: str
    blocks: tuple[SourceBlock, ...]


def _clean_text(value: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", value).strip()


def _is_heading(text: str) -> bool:
    stripped = text.strip()
    return bool(_HEADING_PATTERN.match(stripped)) or (
        len(stripped) <= 40 and stripped.endswith(("章", "节", "篇"))
    )


def _heading_text(text: str) -> str:
    return re.sub(r"^#{1,6}\s+", "", text).strip()


def _section_blocks(
    paragraphs: list[tuple[str, bool]], default_locator: str
) -> list[SourceBlock]:
    blocks: list[SourceBlock] = []
    locator = default_locator
    content: list[str] = []

    def flush() -> None:
        text = "\n".join(value for value in content if value).strip()
        if text:
            blocks.append(SourceBlock(locator=locator, text=text))
        content.clear()

    for raw_text, heading in paragraphs:
        text = _clean_text(raw_text)
        if not text:
            continue
        if heading:
            flush()
            locator = _heading_text(text)
        else:
            content.append(text)
    flush()
    return blocks


def _read_txt(path: Path) -> list[SourceBlock]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise KnowledgeError(f"TXT 必须使用 UTF-8 编码: {path}") from exc
    paragraphs = [
        (line, _is_heading(line))
        for line in text.splitlines()
        if line.strip()
    ]
    return _section_blocks(paragraphs, path.stem)


def _read_docx(path: Path) -> list[SourceBlock]:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml)
    except (
        KeyError,
        OSError,
        ElementTree.ParseError,
        zipfile.BadZipFile,
    ) as exc:
        raise KnowledgeError(f"DOCX 文件无效: {path}") from exc

    paragraphs: list[tuple[str, bool]] = []
    for paragraph in root.findall(".//w:body//w:p", _WORD_NAMESPACE):
        text = "".join(
            value.text or ""
            for value in paragraph.findall(".//w:t", _WORD_NAMESPACE)
        ).strip()
        if not text:
            continue
        style = paragraph.find("./w:pPr/w:pStyle", _WORD_NAMESPACE)
        style_name = style.get(_WORD_VALUE, "") if style is not None else ""
        is_heading = (
            style_name.casefold().startswith("heading") or _is_heading(text)
        )
        paragraphs.append((text, is_heading))
    return _section_blocks(paragraphs, path.stem)


def _read_pdf(path: Path) -> list[SourceBlock]:
    try:
        pdf_module = import_module("pypdf")
    except ImportError as exc:
        raise KnowledgeError("PDF 支持需要安装项目依赖 pypdf") from exc

    try:
        reader = pdf_module.PdfReader(str(path))
        blocks = [
            SourceBlock(
                locator=f"第 {number} 页",
                text=_clean_text(page.extract_text() or ""),
            )
            for number, page in enumerate(reader.pages, start=1)
        ]
    except Exception as exc:
        raise KnowledgeError(f"PDF 文件无法读取: {path}") from exc
    populated = [block for block in blocks if block.text]
    if not populated:
        raise KnowledgeError(f"PDF 未包含可提取文本（不支持扫描型 PDF）: {path}")
    return populated


def read_document(path: Path) -> list[SourceBlock]:
    suffix = path.suffix.casefold()
    if suffix == ".txt":
        blocks = _read_txt(path)
    elif suffix == ".docx":
        blocks = _read_docx(path)
    elif suffix == ".pdf":
        blocks = _read_pdf(path)
    else:
        raise KnowledgeError(f"不支持的知识文件格式: {path.suffix}")
    if not blocks:
        raise KnowledgeError(f"文档没有可索引文本: {path}")
    return blocks


def _split_unit(unit: str, maximum: int) -> list[str]:
    return [unit[index : index + maximum] for index in range(0, len(unit), maximum)]


def chunk_block(
    block: SourceBlock, maximum: int = DEFAULT_CHUNK_SIZE
) -> list[SourceBlock]:
    if maximum <= 0:
        raise ValueError("切分长度必须为正整数")
    units: list[str] = []
    for value in re.split(r"(?<=[。！？!?；;\n])", block.text):
        cleaned = value.strip()
        if cleaned:
            units.extend(_split_unit(cleaned, maximum))

    chunks: list[SourceBlock] = []
    current = ""
    for unit in units:
        separator = "\n" if current else ""
        if current and len(current) + len(separator) + len(unit) > maximum:
            chunks.append(SourceBlock(locator=block.locator, text=current))
            current = unit
        else:
            current = f"{current}{separator}{unit}"
    if current:
        chunks.append(SourceBlock(locator=block.locator, text=current))
    return chunks


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in _TOKEN_PATTERN.finditer(text.casefold()):
        value = match.group()
        if value.isascii():
            tokens.append(value)
            continue
        tokens.extend(value)
        tokens.extend(value[index : index + 2] for index in range(len(value) - 1))
    return tokens


def _bm25_scores(query: list[str], corpus: list[list[str]]) -> list[float]:
    if not query or not corpus:
        return [0.0] * len(corpus)
    document_frequency: Counter[str] = Counter()
    frequencies: list[Counter[str]] = []
    for document in corpus:
        counts = Counter(document)
        frequencies.append(counts)
        document_frequency.update(counts.keys())

    average_length = sum(len(document) for document in corpus) / len(corpus)
    average_length = average_length or 1.0
    query_frequency = Counter(query)
    scores: list[float] = []
    for document, counts in zip(corpus, frequencies):
        score = 0.0
        for term, query_count in query_frequency.items():
            frequency = counts[term]
            if not frequency:
                continue
            occurrences = document_frequency[term]
            inverse_frequency = math.log(
                1 + (len(corpus) - occurrences + 0.5) / (occurrences + 0.5)
            )
            denominator = frequency + 1.5 * (
                0.25 + 0.75 * len(document) / average_length
            )
            score += (
                inverse_frequency
                * frequency
                * 2.5
                / denominator
                * query_count
            )
        scores.append(score)
    return scores


def _evidence(text: str, query: str, maximum: int = 180) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= maximum:
        return compact
    folded = compact.casefold()
    candidates = [query.strip()] + [
        match.group() for match in _TOKEN_PATTERN.finditer(query)
    ]
    positions = [
        folded.find(candidate.casefold())
        for candidate in candidates
        if candidate and folded.find(candidate.casefold()) >= 0
    ]
    match_position = min(positions) if positions else 0
    start = max(0, match_position - maximum // 3)
    end = min(len(compact), start + maximum)
    start = max(0, end - maximum)
    prefix = "…" if start else ""
    suffix = "…" if end < len(compact) else ""
    return f"{prefix}{compact[start:end].strip()}{suffix}"


class KnowledgeBase:
    """Local SQLite metadata store and category-scoped BM25 retriever."""

    def __init__(self, knowledge_dir: Path, database_path: Path) -> None:
        self.knowledge_dir = knowledge_dir
        self.database_path = database_path

    def _collect_documents(self) -> tuple[list[_IndexedDocument], int]:
        if not self.knowledge_dir.is_dir():
            raise KnowledgeError(f"知识目录不存在: {self.knowledge_dir}")
        for knowledge_type in (KnowledgeType.POLICY, KnowledgeType.STYLE_CASE):
            expected = self.knowledge_dir / knowledge_type
            if not expected.is_dir():
                raise KnowledgeError(f"知识目录缺少分类子目录: {expected}")

        documents: list[_IndexedDocument] = []
        ignored = 0
        for path in sorted(self.knowledge_dir.rglob("*")):
            if not path.is_file():
                continue
            suffix = path.suffix.casefold()
            relative = path.relative_to(self.knowledge_dir)
            if suffix not in SUPPORTED_SUFFIXES:
                ignored += 1
                continue
            try:
                knowledge_type = KnowledgeType(relative.parts[0])
            except (IndexError, ValueError) as exc:
                raise KnowledgeError(
                    f"知识文件必须放在 policy 或 style_case 子目录中: {path}"
                ) from exc
            blocks = tuple(
                chunk
                for block in read_document(path)
                for chunk in chunk_block(block)
            )
            documents.append(
                _IndexedDocument(
                    path=path,
                    relative_path=relative.as_posix(),
                    knowledge_type=knowledge_type,
                    file_format=suffix.removeprefix("."),
                    blocks=blocks,
                )
            )
        return documents, ignored

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY,
                path TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                knowledge_type TEXT NOT NULL
                    CHECK (knowledge_type IN ('policy', 'style_case')),
                file_format TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                modified_ns INTEGER NOT NULL,
                indexed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY,
                document_id INTEGER NOT NULL
                    REFERENCES documents(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                locator TEXT NOT NULL,
                text TEXT NOT NULL,
                UNIQUE(document_id, chunk_index)
            );
            CREATE INDEX IF NOT EXISTS chunks_document_id
                ON chunks(document_id);
            CREATE INDEX IF NOT EXISTS documents_knowledge_type
                ON documents(knowledge_type);
            """
        )

    def _replace_index(
        self,
        connection: sqlite3.Connection,
        documents: list[_IndexedDocument],
        indexed_at: str,
    ) -> int:
        chunk_count = 0
        connection.execute("DELETE FROM chunks")
        connection.execute("DELETE FROM documents")
        for document in documents:
            stat = document.path.stat()
            cursor = connection.execute(
                """
                INSERT INTO documents (
                    path, name, knowledge_type, file_format,
                    size_bytes, modified_ns, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.relative_path,
                    document.path.name,
                    document.knowledge_type,
                    document.file_format,
                    stat.st_size,
                    stat.st_mtime_ns,
                    indexed_at,
                ),
            )
            document_id = cursor.lastrowid
            connection.executemany(
                """
                INSERT INTO chunks (
                    document_id, chunk_index, locator, text
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    (document_id, index, block.locator, block.text)
                    for index, block in enumerate(document.blocks)
                ),
            )
            chunk_count += len(document.blocks)
        return chunk_count

    def rebuild(
        self, connection: sqlite3.Connection | None = None
    ) -> RebuildReport:
        documents, ignored = self._collect_documents()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        indexed_at = datetime.now(UTC).isoformat()
        if connection is None:
            with sqlite3.connect(self.database_path) as owned_connection:
                owned_connection.execute("PRAGMA foreign_keys = ON")
                self._create_schema(owned_connection)
                chunk_count = self._replace_index(
                    owned_connection, documents, indexed_at
                )
        else:
            chunk_count = self._replace_index(
                connection, documents, indexed_at
            )
        return RebuildReport(
            document_count=len(documents),
            chunk_count=chunk_count,
            ignored_file_count=ignored,
        )

    def search(
        self,
        query: str,
        knowledge_type: KnowledgeType,
        *,
        top_k: int = MAX_SEARCH_RESULTS,
        include_internal: bool = False,
    ) -> list[SearchResult]:
        if not query.strip():
            raise ValueError("检索词不能为空")
        if not 1 <= top_k <= MAX_SEARCH_RESULTS:
            raise ValueError(f"top_k 必须在 1 到 {MAX_SEARCH_RESULTS} 之间")
        try:
            selected_type = KnowledgeType(knowledge_type)
        except ValueError as exc:
            raise ValueError("知识类型必须是 policy、style_case 或 source") from exc
        if not self.database_path.is_file():
            raise KnowledgeError("本地知识索引不存在，请先重建知识目录")

        if selected_type is KnowledgeType.SOURCE:
            return self._search_source(
                query,
                top_k=top_k,
                include_internal=include_internal,
            )
        if include_internal:
            raise ValueError("include_internal 只能用于 source 检索")

        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT
                    chunks.id,
                    documents.name,
                    documents.knowledge_type,
                    chunks.locator,
                    chunks.text
                FROM chunks
                JOIN documents ON documents.id = chunks.document_id
                WHERE documents.knowledge_type = ?
                ORDER BY chunks.id
                """,
                (selected_type,),
            ).fetchall()

        corpus = [
            tokenize(f"{row['name']} {row['locator']} {row['text']}")
            for row in rows
        ]
        scores = _bm25_scores(tokenize(query), corpus)
        ranked = sorted(
            (
                (score, index, row)
                for index, (score, row) in enumerate(zip(scores, rows))
                if score > 0
            ),
            key=lambda value: (-value[0], value[1]),
        )[:top_k]
        return [
            SearchResult(
                knowledge_type=KnowledgeType(row["knowledge_type"]),
                document_name=row["name"],
                locator=row["locator"],
                evidence=_evidence(row["text"], query),
                score=score,
            )
            for score, _, row in ranked
        ]

    @staticmethod
    def _source_query(query: str) -> str:
        terms = list(dict.fromkeys(tokenize(query)))
        return " OR ".join(
            f'"{term.replace(chr(34), chr(34) * 2)}"'
            for term in terms
            if term.strip()
        )

    def _search_source(
        self,
        query: str,
        *,
        top_k: int,
        include_internal: bool,
    ) -> list[SearchResult]:
        fts_query = self._source_query(query)
        if not fts_query:
            return []
        audience_filter = "" if include_internal else "AND fts.audience = 'advisor'"
        try:
            with sqlite3.connect(self.database_path) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    f"""
                    SELECT chunk.id AS chunk_id, source.name,
                           block.id AS block_id, block.locator, chunk.text,
                           block.authority,
                           -bm25(source_chunks_fts, 0, 0, 0, 2, 2, 3) AS score
                    FROM source_chunks_fts AS fts
                    JOIN source_chunks AS chunk
                      ON chunk.id = CAST(fts.source_chunk_id AS INTEGER)
                    JOIN source_blocks AS block ON block.id = chunk.block_id
                    JOIN source_revisions AS revision
                      ON revision.id = block.revision_id
                    JOIN source_files AS source ON source.id = revision.source_id
                    WHERE source_chunks_fts MATCH ?
                      {audience_filter}
                      AND revision.status = 'approved'
                      AND block.quality_status = 'approved'
                    ORDER BY score DESC, chunk.id
                    LIMIT ?
                    """,
                    (fts_query, max(top_k * 100, 300)),
                ).fetchall()
                filters = query_semantic_filters(query)
                if rows:
                    block_ids = sorted({int(row["block_id"]) for row in rows})
                    placeholders = ",".join("?" for _ in block_ids)
                    semantic_rows = connection.execute(
                        f"""
                        SELECT source_block_id, record_kind, grade, subject,
                               class_type, period, textbook_version,
                               campaign_start, campaign_end, campaign_status
                        FROM semantic_records
                        WHERE source_block_id IN ({placeholders})
                          AND record_status = 'approved'
                          AND quality_status = 'approved'
                          AND audience = 'advisor'
                          AND scope_status IN ('tianjin', 'tianjin_compatible')
                          AND (campaign_status = '' OR campaign_status = 'active')
                        """,
                        block_ids,
                    ).fetchall()
                    semantic_by_block: dict[int, list[sqlite3.Row]] = {}
                    for semantic_row in semantic_rows:
                        semantic_by_block.setdefault(
                            int(semantic_row["source_block_id"]), []
                        ).append(semantic_row)
                    current_day = date.today().isoformat()

                    def block_is_eligible(row: sqlite3.Row) -> bool:
                        records = semantic_by_block.get(int(row["block_id"]), [])
                        if not records:
                            return not filters
                        campaigns = [
                            record
                            for record in records
                            if record["record_kind"] == "campaign"
                        ]
                        if campaigns and not any(
                            record["campaign_status"] == "active"
                            and str(record["campaign_start"]) <= current_day
                            <= str(record["campaign_end"])
                            for record in campaigns
                        ):
                            return False
                        return not filters or any(
                            semantic_row_matches(candidate, filters)
                            for candidate in records
                        )

                    rows = [row for row in rows if block_is_eligible(row)]
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).casefold():
                return []
            raise KnowledgeError(f"原文知识索引查询失败：{exc}") from exc
        query_terms = set(tokenize(query))
        query_phrases = {
            value.casefold()
            for value in re.findall(r"[a-z0-9\u3400-\u9fff]+", query)
            if len(value) > 1
        }

        def weighted_score(row: sqlite3.Row) -> float:
            title = set(tokenize(row["name"]))
            locator = set(tokenize(row["locator"]))
            content = set(tokenize(row["text"]))
            folded_title = str(row["name"]).casefold()
            folded_locator = str(row["locator"]).casefold()
            folded_content = str(row["text"]).casefold()
            return (
                sum(
                    (0.35 if len(term) == 1 and not term.isascii() else 1.0)
                    * max(
                        5.0 if term in title else 0.0,
                        3.0 if term in locator else 0.0,
                        4.0 if term in content else 0.0,
                    )
                    for term in query_terms
                )
                + sum(
                    max(
                        10.0 if phrase in folded_title else 0.0,
                        7.0 if phrase in folded_locator else 0.0,
                        8.0 if phrase in folded_content else 0.0,
                    )
                    for phrase in query_phrases
                )
                + min(float(row["score"]), 1.0)
            )

        ranked = sorted(
            rows,
            key=lambda row: (-weighted_score(row), row["chunk_id"]),
        )[:top_k]
        return [
            SearchResult(
                knowledge_type=KnowledgeType.SOURCE,
                document_name=row["name"],
                locator=row["locator"],
                evidence=_evidence(row["text"], query),
                score=weighted_score(row),
                source_tier="approved_source",
                authority=str(row["authority"]),
            )
            for row in ranked
        ]

    def _search_semantic_source(
        self, query: str, *, top_k: int
    ) -> list[SearchResult]:
        filters = query_semantic_filters(query)
        campaign_only = requests_campaign_information(query)
        compatible_only = requests_national_tianjin_compatibility(query)
        query_terms = set(tokenize(query))
        try:
            with sqlite3.connect(self.database_path) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """
                    SELECT record.id AS record_id, record.source_block_id,
                           record.record_kind,
                           record.scope_status,
                           record.grade, record.subject, record.class_type,
                           record.period, record.textbook_version,
                           record.statement, source.name, block.locator,
                           block.authority, chunk.id AS chunk_id, chunk.text
                    FROM semantic_records AS record
                    JOIN source_blocks AS block
                      ON block.id = record.source_block_id
                    JOIN source_revisions AS revision
                      ON revision.id = record.source_revision_id
                    JOIN source_files AS source ON source.id = revision.source_id
                    JOIN source_chunks AS chunk ON chunk.block_id = block.id
                    WHERE record.record_status = 'approved'
                      AND record.quality_status = 'approved'
                      AND record.audience = 'advisor'
                      AND record.scope_status IN ('tianjin', 'tianjin_compatible')
                      AND (record.campaign_status = ''
                           OR (record.campaign_status = 'active'
                               AND record.campaign_start <= date('now', 'localtime')
                               AND record.campaign_end >= date('now', 'localtime')))
                      AND revision.status = 'approved'
                      AND block.quality_status = 'approved'
                      AND block.usage_status = 'advisor'
                    ORDER BY record.id, chunk.id
                    """
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).casefold() or "no such column" in str(
                exc
            ).casefold():
                return []
            raise KnowledgeError(f"语义知识索引查询失败：{exc}") from exc

        ranked: list[tuple[float, int, sqlite3.Row]] = []
        for row in rows:
            if campaign_only and row["record_kind"] != "campaign":
                continue
            if compatible_only and row["scope_status"] != "tianjin_compatible":
                continue
            if filters and not semantic_row_matches(row, filters):
                continue
            candidate_terms = set(
                tokenize(
                    " ".join(
                        str(row[field] or "")
                        for field in (
                            "name",
                            "locator",
                            "grade",
                            "subject",
                            "class_type",
                            "period",
                            "textbook_version",
                            "statement",
                            "text",
                        )
                    )
                )
            )
            overlap = len(query_terms.intersection(candidate_terms))
            if not overlap and not filters:
                continue
            ranked.append((float(overlap), int(row["chunk_id"]), row))
        ranked.sort(key=lambda value: (-value[0], value[1]))
        selected: list[SearchResult] = []
        seen_blocks: set[int] = set()
        for score, _, row in ranked:
            block_id = int(row["source_block_id"])
            if block_id in seen_blocks:
                continue
            seen_blocks.add(block_id)
            selected.append(
                SearchResult(
                    knowledge_type=KnowledgeType.SOURCE,
                    document_name=str(row["name"]),
                    locator=str(row["locator"]),
                    evidence=_evidence(str(row["text"]), query),
                    score=score,
                    source_tier="approved_source",
                    authority=str(row["authority"]),
                )
            )
            if len(selected) == top_k:
                break
        return selected

    def _filter_curated_by_semantics(
        self,
        results: list[SearchResult],
        filters: dict[str, str],
        *,
        campaign_only: bool = False,
        compatible_only: bool = False,
    ) -> list[SearchResult]:
        if not results:
            return results
        try:
            with sqlite3.connect(self.database_path) as connection:
                connection.row_factory = sqlite3.Row
                link_columns = {
                    str(row[1])
                    for row in connection.execute(
                        "PRAGMA table_info(policy_semantic_links)"
                    )
                }
                locator_sql = (
                    "link.policy_locator" if "policy_locator" in link_columns
                    else "'' AS policy_locator"
                )
                if "policy_text_hash" in link_columns:
                    hash_sql = "link.policy_text_hash"
                    chunk_sql = "policy_chunk.text AS policy_text"
                    chunk_join_sql = (
                        "LEFT JOIN chunks AS policy_chunk "
                        "ON policy_chunk.document_id = document.id "
                        "AND policy_chunk.locator = link.policy_locator"
                    )
                else:
                    hash_sql = "'' AS policy_text_hash"
                    chunk_sql = "'' AS policy_text"
                    chunk_join_sql = ""
                rows = connection.execute(
                    f"""
                    SELECT document.name, {locator_sql}, {hash_sql},
                           {chunk_sql},
                           record.record_kind,
                           record.scope_status,
                           record.grade, record.subject,
                           record.class_type, record.period,
                           record.textbook_version, record.campaign_start,
                           record.campaign_end, record.campaign_status
                    FROM policy_semantic_links AS link
                    JOIN documents AS document
                      ON document.path = link.knowledge_path
                    {chunk_join_sql}
                    JOIN semantic_records AS record
                      ON record.id = link.semantic_record_id
                    WHERE record.record_status = 'approved'
                      AND record.quality_status = 'approved'
                      AND record.scope_status IN ('tianjin', 'tianjin_compatible')
                    """
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).casefold():
                return results
            raise KnowledgeError(f"语义知识映射查询失败：{exc}") from exc
        by_section: dict[tuple[str, str], list[sqlite3.Row]] = {}
        legacy_by_document: dict[str, list[sqlite3.Row]] = {}
        mapped_documents: set[str] = set()
        for row in rows:
            document_name = str(row["name"])
            locator = str(row["policy_locator"] or "")
            mapped_documents.add(document_name)
            if locator:
                expected_hash = hashlib.sha256(
                    f"{locator}\0{str(row['policy_text'] or '')}".encode(
                        "utf-8"
                    )
                ).hexdigest()
                if str(row["policy_text_hash"] or "") != expected_hash:
                    continue
            if locator:
                by_section.setdefault((document_name, locator), []).append(row)
            else:
                legacy_by_document.setdefault(document_name, []).append(row)
        current_day = date.today().isoformat()

        def document_is_eligible(result: SearchResult) -> bool:
            records = by_section.get(
                (result.document_name, result.locator),
                legacy_by_document.get(result.document_name, []),
            )
            if not records:
                if result.document_name in mapped_documents:
                    return False
                return not campaign_only and not compatible_only
            if compatible_only and not any(
                row["scope_status"] == "tianjin_compatible" for row in records
            ):
                return False
            campaigns = [
                row for row in records if row["record_kind"] == "campaign"
            ]
            if campaign_only and not campaigns:
                return False
            if campaigns and not any(
                row["campaign_status"] == "active"
                and str(row["campaign_start"]) <= current_day
                <= str(row["campaign_end"])
                for row in campaigns
            ):
                return False
            return not filters or any(
                semantic_row_matches(row, filters) for row in records
            )

        return [result for result in results if document_is_eligible(result)]

    def search_advice_policy(
        self, query: str, *, top_k: int = MAX_ADVICE_RESULTS
    ) -> list[SearchResult]:
        if not 1 <= top_k <= MAX_ADVICE_RESULTS:
            raise ValueError(f"top_k 必须在 1 到 {MAX_ADVICE_RESULTS} 之间")
        if (
            requests_internal_information(query)
            or requests_out_of_scope_region(query)
            or requires_live_system_lookup(query)
        ):
            return []
        curated = self.search(
            query,
            KnowledgeType.POLICY,
            top_k=min(MAX_SEARCH_RESULTS, top_k),
        )
        filters = query_semantic_filters(query)
        campaign_only = requests_campaign_information(query)
        compatible_only = requests_national_tianjin_compatibility(query)
        product_overview_only = requests_product_overview(query)
        curated_only = any(
            predicate(query)
            for predicate in (
                requests_class_selection,
                requests_teacher_information,
                requests_enrollment_rules,
                requests_online_course_service,
            )
        ) or product_overview_only
        curated = self._filter_curated_by_semantics(
            curated,
            filters,
            campaign_only=campaign_only,
            compatible_only=compatible_only,
        )
        if product_overview_only:
            curated = [
                result for result in curated
                if result.document_name == "课程产品总览.txt"
                and result.locator.startswith("天津课程产品线｜")
            ]
        source = (
            []
            if campaign_only or compatible_only or curated_only
            else self.search(
                query,
                KnowledgeType.SOURCE,
                top_k=MAX_SEARCH_RESULTS,
            )
        )
        semantic_source = (
            []
            if curated_only
            else self._search_semantic_source(
                query, top_k=MAX_SEARCH_RESULTS
            )
        )
        query_terms = set(tokenize(query))

        def relevance(result: SearchResult) -> tuple[float, int]:
            candidate = tokenize(
                f"{result.document_name} {result.locator} {result.evidence}"
            )
            overlap = (
                len(query_terms.intersection(candidate)) / len(query_terms)
                if query_terms
                else 0.0
            )
            tier_bonus = 0.08 if result.source_tier == "curated" else 0.0
            authority_bonus = 0.03 if result.authority == "primary" else 0.0
            return overlap + tier_bonus + authority_bonus, (
                0 if result.source_tier == "curated" else 1
            )

        ranked = sorted(
            (*curated, *source, *semantic_source),
            key=lambda result: (-relevance(result)[0], relevance(result)[1]),
        )
        seen: set[tuple[str, str]] = set()
        selected: list[SearchResult] = []
        for result in ranked:
            key = (result.document_name, re.sub(r"\s+", "", result.evidence))
            if key in seen:
                continue
            seen.add(key)
            selected.append(result)
            if len(selected) == top_k:
                break
        return selected


def format_search_results(results: list[SearchResult]) -> str:
    if not results:
        return "未找到相关知识。"
    return "\n".join(
        (
            f"{index}. 【{result.knowledge_type}｜{result.document_name}"
            f"｜{result.locator}】\n证据：{result.evidence}"
        )
        for index, result in enumerate(results, start=1)
    )
