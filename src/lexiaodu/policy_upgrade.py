from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from lexiaodu.knowledge import SourceBlock, chunk_block, read_document
from lexiaodu.knowledge_semantics import (
    BUSINESS_DOMAINS,
    suggest_block_disposition,
)


POLICY_UPGRADE_VERSION = 1
EXACT_FACT_NAMES = frozenset({"lesson_count", "price", "textbook_version"})


class PolicyUpgradeError(RuntimeError):
    """Raised when a policy-only batch is incomplete or unsafe."""


@dataclass(frozen=True, slots=True)
class PolicyCoverageReport:
    document_count: int
    section_count: int
    linked_section_count: int
    semantic_link_count: int
    valid_semantic_link_count: int
    binding_rate: float
    unlinked_section_count: int
    source_bound_section_count: int
    source_binding_rate: float
    retired_document_count: int
    by_domain: dict[str, dict[str, int]]


def ensure_policy_schema(connection: sqlite3.Connection) -> None:
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(policy_semantic_links)")
    }
    if not columns:
        connection.execute(
            """
            CREATE TABLE policy_semantic_links (
                knowledge_path TEXT NOT NULL,
                policy_locator TEXT NOT NULL DEFAULT '',
                policy_text_hash TEXT NOT NULL DEFAULT '',
                semantic_record_id INTEGER NOT NULL
                    REFERENCES semantic_records(id) ON DELETE CASCADE,
                PRIMARY KEY (
                    knowledge_path, policy_locator, semantic_record_id
                )
            )
            """
        )
        return
    if {"policy_locator", "policy_text_hash"} <= columns:
        return
    connection.execute(
        "ALTER TABLE policy_semantic_links RENAME TO policy_semantic_links_legacy"
    )
    connection.execute(
        """
        CREATE TABLE policy_semantic_links (
            knowledge_path TEXT NOT NULL,
            policy_locator TEXT NOT NULL DEFAULT '',
            policy_text_hash TEXT NOT NULL DEFAULT '',
            semantic_record_id INTEGER NOT NULL
                REFERENCES semantic_records(id) ON DELETE CASCADE,
            PRIMARY KEY (
                knowledge_path, policy_locator, semantic_record_id
            )
        )
        """
    )
    connection.execute(
        """
        INSERT INTO policy_semantic_links (
            knowledge_path, policy_locator, policy_text_hash,
            semantic_record_id
        )
        SELECT knowledge_path, '', '', semantic_record_id
        FROM policy_semantic_links_legacy
        """
    )
    connection.execute("DROP TABLE policy_semantic_links_legacy")


def semantic_snapshot_hash(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    rows = connection.execute(
        """
        SELECT record.id, record.payload_json, record.record_kind,
               record.scope_status, record.audience, record.authority,
               record.quality_status, record.campaign_status,
               record.source_revision_id, record.source_block_id,
               block.usage_status, block.quality_status,
               revision.status, source.sha256
        FROM semantic_records AS record
        JOIN source_blocks AS block ON block.id = record.source_block_id
        JOIN source_revisions AS revision
          ON revision.id = record.source_revision_id
        JOIN source_files AS source ON source.id = revision.source_id
        WHERE record.record_status = 'approved'
        ORDER BY record.id
        """
    )
    for row in rows:
        digest.update(
            json.dumps(tuple(row), ensure_ascii=False, separators=(",", ":"))
            .encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def collect_policy_evidence(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT record.id, record.record_kind, record.business_domain,
               record.stage, record.grade, record.subject,
               record.course_name, record.period, record.class_type,
               record.textbook_version, record.fact_name,
               record.fact_value, record.statement,
               record.relation_type, record.campaign_name,
               record.campaign_start, record.campaign_end,
               record.campaign_status, record.scope_status,
               record.authority, record.payload_json,
               record.source_revision_id, record.source_block_id,
               source.relative_path, block.locator, block.kind,
               block.text
        FROM semantic_records AS record
        JOIN source_blocks AS block ON block.id = record.source_block_id
        JOIN source_revisions AS revision
          ON revision.id = record.source_revision_id
        JOIN source_files AS source ON source.id = revision.source_id
        WHERE record.record_status = 'approved'
          AND record.quality_status = 'approved'
          AND record.audience = 'advisor'
          AND record.scope_status IN ('tianjin', 'tianjin_compatible')
          AND revision.status = 'approved'
          AND block.quality_status = 'approved'
          AND block.usage_status = 'advisor'
        ORDER BY record.business_domain, record.stage, record.subject,
                 record.course_name, record.id
        """
    ).fetchall()
    evidence: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(str(item.pop("payload_json")))
        evidence.append(item)
    return evidence


def section_hash(locator: str, text: str) -> str:
    canonical_text = "\n".join(
        chunk.text
        for chunk in chunk_block(SourceBlock(locator=locator, text=text))
    )
    return hashlib.sha256(
        f"{locator}\0{canonical_text}".encode("utf-8")
    ).hexdigest()


def read_policy_sections(path: Path) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    seen: set[str] = set()
    for block in read_document(path):
        locator = block.locator.strip()
        text = block.text.strip()
        if not locator or not text:
            continue
        if locator in seen:
            raise PolicyUpgradeError(
                f"policy章节标题必须唯一：{path} -> {locator}"
            )
        if len(text) > 500:
            raise PolicyUpgradeError(
                f"policy章节超过500字：{path} -> {locator}"
            )
        seen.add(locator)
        sections.append(
            {
                "locator": locator,
                "text": text,
                "text_hash": section_hash(locator, text),
            }
        )
    if not sections:
        raise PolicyUpgradeError(f"policy草稿没有可索引章节：{path}")
    return sections


def validate_policy_text(path: str, locator: str, text: str) -> None:
    usage, reason, scope = suggest_block_disposition(
        source_name=path,
        locator=locator,
        text=text,
    )
    if usage != "advisor" or scope not in {"tianjin", "tianjin_compatible"}:
        raise PolicyUpgradeError(
            f"policy章节触发范围、隐私或营销门槛：{path} -> {locator}"
            + (f"（{reason}）" if reason else "")
        )


def validate_evidence_rows(
    connection: sqlite3.Connection,
    semantic_record_ids: Iterable[int],
) -> list[sqlite3.Row]:
    ids = list(dict.fromkeys(int(value) for value in semantic_record_ids))
    if not ids:
        raise PolicyUpgradeError("每个policy章节至少需要一条semantic证据")
    placeholders = ",".join("?" for _ in ids)
    rows = connection.execute(
        f"""
        SELECT record.*, block.usage_status AS block_usage_status,
               block.quality_status AS block_quality_status,
               revision.status AS revision_status,
               revision.source_id
        FROM semantic_records AS record
        JOIN source_blocks AS block ON block.id = record.source_block_id
        JOIN source_revisions AS revision
          ON revision.id = record.source_revision_id
        WHERE record.id IN ({placeholders})
        """,
        ids,
    ).fetchall()
    if len(rows) != len(ids):
        raise PolicyUpgradeError("policy章节引用了不存在的semantic记录")
    current_day = date.today().isoformat()
    for row in rows:
        if (
            row["record_status"] != "approved"
            or row["quality_status"] != "approved"
            or row["audience"] != "advisor"
            or row["scope_status"] not in {"tianjin", "tianjin_compatible"}
            or row["block_usage_status"] != "advisor"
            or row["block_quality_status"] != "approved"
            or row["revision_status"] != "approved"
        ):
            raise PolicyUpgradeError("policy章节引用了非正式或不可用semantic记录")
        if row["fact_name"] in EXACT_FACT_NAMES and row["authority"] != "primary":
            raise PolicyUpgradeError(
                f"精确参数必须使用primary证据：semantic {row['id']}"
            )
        if row["record_kind"] == "campaign" and not (
            row["campaign_status"] == "active"
            and str(row["campaign_start"]) <= current_day
            <= str(row["campaign_end"])
        ):
            raise PolicyUpgradeError("非有效活动不能提升为policy")
    return rows


def policy_coverage_report(
    connection: sqlite3.Connection,
    *,
    retired_document_count: int | None = None,
) -> PolicyCoverageReport:
    ensure_policy_schema(connection)
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if not {"documents", "chunks"} <= tables:
        return PolicyCoverageReport(
            document_count=0,
            section_count=0,
            linked_section_count=0,
            semantic_link_count=0,
            valid_semantic_link_count=0,
            binding_rate=1.0,
            unlinked_section_count=0,
            source_bound_section_count=0,
            source_binding_rate=1.0,
            retired_document_count=retired_document_count or 0,
            by_domain={
                domain: {"documents": 0, "sections": 0}
                for domain in BUSINESS_DOMAINS
            },
        )
    policy_rows = connection.execute(
        """
        SELECT document.path, chunk.locator, chunk.text
        FROM documents AS document
        JOIN chunks AS chunk ON chunk.document_id = document.id
        WHERE document.knowledge_type = 'policy'
        GROUP BY document.path, chunk.locator, chunk.text
        """
    ).fetchall()
    section_hashes = {
        (str(row[0]), str(row[1])): section_hash(str(row[1]), str(row[2]))
        for row in policy_rows
    }
    sections = set(section_hashes)
    link_rows = connection.execute(
        """
        SELECT link.knowledge_path, link.policy_locator,
               link.policy_text_hash, link.semantic_record_id,
               CASE WHEN record.record_status = 'approved'
                          AND record.quality_status = 'approved'
                          AND record.audience = 'advisor'
                          AND record.scope_status IN (
                              'tianjin', 'tianjin_compatible'
                          )
                          AND block.usage_status = 'advisor'
                          AND block.quality_status = 'approved'
                          AND revision.status = 'approved'
                    THEN 1 ELSE 0 END AS valid
        FROM policy_semantic_links AS link
        LEFT JOIN semantic_records AS record
          ON record.id = link.semantic_record_id
        LEFT JOIN source_blocks AS block ON block.id = record.source_block_id
        LEFT JOIN source_revisions AS revision
          ON revision.id = record.source_revision_id
        """
    ).fetchall()
    linked = {
        key
        for row in link_rows
        if (key := (str(row[0]), str(row[1]))) in sections
        and str(row[2]) == section_hashes[key]
        and int(row[4]) == 1
    }
    by_domain: dict[str, dict[str, int]] = {
        domain: {"documents": 0, "sections": 0}
        for domain in BUSINESS_DOMAINS
    }
    for path, locator in sections:
        parts = Path(path).parts
        domain = parts[1] if len(parts) > 2 else "未分类"
        counts = by_domain.setdefault(domain, {"documents": 0, "sections": 0})
        counts["sections"] += 1
    for path in {path for path, _ in sections}:
        parts = Path(path).parts
        domain = parts[1] if len(parts) > 2 else "未分类"
        by_domain.setdefault(domain, {"documents": 0, "sections": 0})[
            "documents"
        ] += 1
    section_count = len(sections)
    linked_section_count = len(sections & linked)
    valid_links = sum(int(row[4]) == 1 for row in link_rows)
    if retired_document_count is None:
        last_upgrade = connection.execute(
            """
            SELECT report_json FROM import_batches
            WHERE source_dir = '<policy-upgrade>' AND status = 'applied'
            ORDER BY applied_at DESC LIMIT 1
            """
        ).fetchone()
        retired_document_count = 0
        if last_upgrade is not None:
            try:
                retired_document_count = int(
                    json.loads(str(last_upgrade[0])).get(
                        "retired_document_count", 0
                    )
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                retired_document_count = 0
    binding_rate = (
        linked_section_count / section_count if section_count else 1.0
    )
    return PolicyCoverageReport(
        document_count=len({path for path, _ in sections}),
        section_count=section_count,
        linked_section_count=linked_section_count,
        semantic_link_count=len(link_rows),
        valid_semantic_link_count=valid_links,
        binding_rate=binding_rate,
        unlinked_section_count=section_count - linked_section_count,
        source_bound_section_count=linked_section_count,
        source_binding_rate=binding_rate,
        retired_document_count=retired_document_count,
        by_domain=dict(sorted(by_domain.items())),
    )
