from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from lexiaodu.knowledge import KnowledgeBase, SUPPORTED_SUFFIXES
from lexiaodu.policy_upgrade import (
    PolicyUpgradeError,
    collect_policy_evidence,
    policy_coverage_report,
    read_policy_sections,
    semantic_snapshot_hash,
    validate_evidence_rows,
    validate_policy_text,
)


POLICY_SOURCE_MARKER = "<policy-upgrade>"


@dataclass(frozen=True, slots=True)
class PreparedPolicyUpgrade:
    batch_id: str
    review_path: Path
    report_path: Path


@dataclass(frozen=True, slots=True)
class AppliedPolicyUpgrade:
    output_count: int
    indexed_document_count: int
    indexed_chunk_count: int


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _knowledge_hashes(knowledge_dir: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(knowledge_dir.rglob("*")):
        if path.is_file() and path.suffix.casefold() in SUPPORTED_SUFFIXES:
            hashes[path.relative_to(knowledge_dir).as_posix()] = _file_hash(path)
    return hashes


def _validate_relative_policy_path(value: str) -> Path:
    path = Path(value)
    if (
        path.is_absolute()
        or not path.parts
        or path.parts[0] != "policy"
        or ".." in path.parts
        or path.suffix.casefold() != ".txt"
    ):
        raise PolicyUpgradeError(f"无效policy路径：{value}")
    return path


def prepare_policy_upgrade(
    knowledge_dir: Path,
    staging_dir: Path,
    connect: Callable[[], sqlite3.Connection],
) -> PreparedPolicyUpgrade:
    batch_id = (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    with connect() as connection:
        unfinished = connection.execute(
            """
            SELECT batch_id FROM import_batches
            WHERE source_dir = ? AND status = 'prepared'
            ORDER BY created_at DESC LIMIT 1
            """,
            (POLICY_SOURCE_MARKER,),
        ).fetchone()
        if unfinished is not None:
            raise PolicyUpgradeError(
                f"已有待审核policy批次：{unfinished['batch_id']}"
            )
    batch_dir = staging_dir.resolve() / batch_id
    batch_dir.mkdir(parents=True, exist_ok=False)
    draft_dir = batch_dir / "draft" / "knowledge" / "policy"
    baseline_dir = batch_dir / "baseline" / "knowledge"
    draft_dir.mkdir(parents=True)
    baseline_dir.mkdir(parents=True)
    hashes = _knowledge_hashes(knowledge_dir)
    policy_paths = sorted(path for path in hashes if path.startswith("policy/"))
    for relative in policy_paths:
        source = knowledge_dir / relative
        target = baseline_dir / relative
        draft = batch_dir / "draft" / "knowledge" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        draft.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        shutil.copyfile(source, draft)

    created_at = _utc_now()
    with connect() as connection:
        unfinished = connection.execute(
            """
            SELECT batch_id FROM import_batches
            WHERE source_dir = ? AND status = 'prepared'
            ORDER BY created_at DESC LIMIT 1
            """,
            (POLICY_SOURCE_MARKER,),
        ).fetchone()
        if unfinished is not None:
            raise PolicyUpgradeError(
                f"已有待审核policy批次：{unfinished['batch_id']}"
            )
        evidence = collect_policy_evidence(connection)
        snapshot = semantic_snapshot_hash(connection)
        current_links: dict[tuple[str, str, str], list[int]] = {}
        for row in connection.execute(
            """
            SELECT knowledge_path, policy_locator, policy_text_hash,
                   semantic_record_id
            FROM policy_semantic_links
            ORDER BY knowledge_path, policy_locator, semantic_record_id
            """
        ):
            key = (str(row[0]), str(row[1]), str(row[2]))
            current_links.setdefault(key, []).append(int(row[3]))
        incremental_documents: list[dict[str, object]] = []
        for relative in policy_paths:
            draft = batch_dir / "draft" / "knowledge" / relative
            sections = read_policy_sections(draft)
            incremental_documents.append(
                {
                    "path": relative,
                    "file_sha256": _file_hash(draft),
                    "sections": [
                        {
                            "locator": section["locator"],
                            "text_hash": section["text_hash"],
                            "decision": "pending",
                            "semantic_record_ids": current_links.get(
                                (relative, section["locator"], section["text_hash"]),
                                [],
                            ),
                        }
                        for section in sections
                    ],
                }
            )
        formal_batch = connection.execute(
            """
            SELECT batch_id FROM import_batches
            WHERE status = 'applied' AND source_dir <> ?
            ORDER BY applied_at DESC LIMIT 1
            """,
            (POLICY_SOURCE_MARKER,),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO import_batches (
                batch_id, source_dir, staging_dir, status,
                created_at, report_json
            ) VALUES (?, ?, ?, 'prepared', ?, '{}')
            """,
            (batch_id, POLICY_SOURCE_MARKER, str(batch_dir), created_at),
        )
        connection.commit()

    batch = {
        "batch_id": batch_id,
        "mode": "policy_upgrade",
        "created_at": created_at,
        "formal_source_batch": str(formal_batch[0]) if formal_batch else "",
        "semantic_snapshot_hash": snapshot,
        "formal_semantic_count": len(evidence),
        "knowledge_base_hashes": hashes,
        "existing_policy_paths": policy_paths,
    }
    review = {
        "batch_id": batch_id,
        "mode": "policy_upgrade",
        "policy_upgrade": {
            "status": "pending",
            "retire_paths": policy_paths,
            "documents": incremental_documents,
            "review_notes": "",
        },
    }
    _write_json(batch_dir / "batch.json", batch)
    _write_json(batch_dir / "review.json", review)
    _write_json(batch_dir / "evidence.json", {"records": evidence})
    report_path = batch_dir / "report.md"
    report_path.write_text(
        "\n".join(
            (
                f"# Policy升级批次 {batch_id}",
                "",
                f"- 正式semantic证据：{len(evidence)} 条",
                f"- 当前policy：{len(policy_paths)} 份",
                "- prepare未扫描来源文件、未提取、未OCR、未修改正式检索。",
                "- draft/knowledge/policy已带出当前草稿和章节证据；修改后在review.json逐章节审核。",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return PreparedPolicyUpgrade(
        batch_id=batch_id,
        review_path=batch_dir / "review.json",
        report_path=report_path,
    )


def apply_policy_upgrade(
    batch_id: str,
    knowledge_dir: Path,
    staging_dir: Path,
    connect: Callable[[], sqlite3.Connection],
) -> AppliedPolicyUpgrade:
    batch_dir = staging_dir.resolve() / batch_id
    batch_path = batch_dir / "batch.json"
    review_path = batch_dir / "review.json"
    if not batch_path.is_file() or not review_path.is_file():
        raise PolicyUpgradeError(f"policy升级批次不存在：{batch_id}")
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if batch.get("mode") != "policy_upgrade" or review.get("mode") != "policy_upgrade":
        raise PolicyUpgradeError("批次不是policy升级模式")
    policy_review = review.get("policy_upgrade")
    if not isinstance(policy_review, dict) or policy_review.get("status") != "approved":
        raise PolicyUpgradeError("policy升级尚未完成审核")
    documents = policy_review.get("documents")
    retire_values = policy_review.get("retire_paths")
    if not isinstance(documents, list) or not documents:
        raise PolicyUpgradeError("policy升级没有审核文档")
    if not isinstance(retire_values, list):
        raise PolicyUpgradeError("policy退休路径必须是数组")

    current_hashes = _knowledge_hashes(knowledge_dir)
    if current_hashes != batch.get("knowledge_base_hashes"):
        raise PolicyUpgradeError("prepare后正式knowledge文件发生变化，拒绝覆盖")
    current_policy = {
        path for path in current_hashes if path.startswith("policy/")
    }
    retire_paths = {
        _validate_relative_policy_path(str(value)).as_posix()
        for value in retire_values
    }
    if not retire_paths <= current_policy:
        raise PolicyUpgradeError("policy退休清单包含不存在的正式文件")

    document_paths: set[str] = set()
    parsed_documents: list[
        tuple[str, Path, list[dict[str, str]], list[dict[str, object]]]
    ] = []
    all_links: list[tuple[str, str, str, int]] = []
    output_sources: set[tuple[int, str]] = set()
    with connect() as validation_connection:
        row = validation_connection.execute(
            "SELECT status FROM import_batches WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        if row is None or row["status"] != "prepared":
            raise PolicyUpgradeError("policy升级批次状态不是prepared")
        if semantic_snapshot_hash(validation_connection) != str(
            batch.get("semantic_snapshot_hash", "")
        ):
            raise PolicyUpgradeError("prepare后正式source或semantic发生变化")
        for document in documents:
            if not isinstance(document, dict):
                raise PolicyUpgradeError("policy文档审核项必须是对象")
            relative = _validate_relative_policy_path(
                str(document.get("path", ""))
            ).as_posix()
            if relative in document_paths:
                raise PolicyUpgradeError(f"重复policy输出：{relative}")
            document_paths.add(relative)
            draft = batch_dir / "draft" / "knowledge" / relative
            if not draft.is_file():
                raise PolicyUpgradeError(f"policy草稿不存在：{draft}")
            if str(document.get("file_sha256", "")) != _file_hash(draft):
                raise PolicyUpgradeError(f"policy草稿哈希不匹配：{relative}")
            parsed = read_policy_sections(draft)
            reviewed_sections = document.get("sections")
            if not isinstance(reviewed_sections, list):
                raise PolicyUpgradeError(f"policy章节审核缺失：{relative}")
            review_by_locator = {
                str(item.get("locator", "")): item
                for item in reviewed_sections
                if isinstance(item, dict)
            }
            if len(review_by_locator) != len(reviewed_sections):
                raise PolicyUpgradeError(f"policy章节审核标题重复：{relative}")
            if set(review_by_locator) != {item["locator"] for item in parsed}:
                raise PolicyUpgradeError(f"policy章节审核与草稿不完整匹配：{relative}")
            for section in parsed:
                item = review_by_locator[section["locator"]]
                if item.get("decision") != "approved":
                    raise PolicyUpgradeError(
                        f"policy章节尚未批准：{relative} -> {section['locator']}"
                    )
                if str(item.get("text_hash", "")) != section["text_hash"]:
                    raise PolicyUpgradeError(
                        f"policy章节正文哈希不匹配：{relative} -> {section['locator']}"
                    )
                validate_policy_text(
                    relative, section["locator"], section["text"]
                )
                evidence_ids = item.get("semantic_record_ids")
                if not isinstance(evidence_ids, list):
                    raise PolicyUpgradeError("policy章节semantic证据必须是数组")
                evidence_rows = validate_evidence_rows(
                    validation_connection, evidence_ids
                )
                for evidence_row in evidence_rows:
                    semantic_id = int(evidence_row["id"])
                    all_links.append(
                        (
                            relative,
                            section["locator"],
                            section["text_hash"],
                            semantic_id,
                        )
                    )
                    output_sources.add(
                        (int(evidence_row["source_id"]), relative)
                    )
            parsed_documents.append(
                (relative, draft, parsed, reviewed_sections)
            )

    draft_files = {
        path.relative_to(batch_dir / "draft" / "knowledge").as_posix()
        for path in (batch_dir / "draft" / "knowledge" / "policy").rglob("*.txt")
    }
    if draft_files != document_paths:
        raise PolicyUpgradeError("policy草稿目录包含未审核文件或缺少审核文件")
    retained_old = current_policy - retire_paths
    if retained_old & document_paths:
        retained_old -= document_paths
    final_policy = retained_old | document_paths
    if len(final_policy) != len(document_paths):
        raise PolicyUpgradeError("旧policy未全部退休，可能造成重复检索")

    targets = {
        knowledge_dir / path
        for path in current_policy | document_paths
    }
    backups = {
        target: target.read_bytes() if target.is_file() else None
        for target in targets
    }
    knowledge = KnowledgeBase(knowledge_dir, Path())
    connection = connect()
    try:
        knowledge.database_path = Path(
            connection.execute("PRAGMA database_list").fetchone()[2]
        )
        connection.execute("BEGIN IMMEDIATE")
        previous_rows = connection.execute(
            """
            SELECT report_json FROM import_batches
            WHERE source_dir = ? AND status = 'applied'
              AND batch_id <> ?
            ORDER BY applied_at DESC
            """,
            (POLICY_SOURCE_MARKER, batch_id),
        ).fetchall()
        previously_retired = 0
        legacy_counts: list[int] = []
        for previous_row in previous_rows:
            try:
                previous_report = json.loads(str(previous_row[0]))
                count = int(previous_report.get("retired_document_count", 0))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if previous_report.get("retired_count_mode") == "cumulative":
                previously_retired = count
                break
            if count > 0:
                legacy_counts.append(count)
        else:
            previously_retired = min(legacy_counts, default=0)
        cumulative_retired = previously_retired + len(
            retire_paths - document_paths
        )
        for relative, draft, _, _ in parsed_documents:
            target = knowledge_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + f".{batch_id}.tmp")
            shutil.copyfile(draft, temporary)
            temporary.replace(target)
        for relative in retire_paths - document_paths:
            (knowledge_dir / relative).unlink(missing_ok=True)

        rebuild = knowledge.rebuild(connection)
        connection.execute("DELETE FROM policy_semantic_links")
        connection.executemany(
            """
            INSERT INTO policy_semantic_links (
                knowledge_path, policy_locator, policy_text_hash,
                semantic_record_id
            ) VALUES (?, ?, ?, ?)
            """,
            all_links,
        )
        connection.execute(
            "DELETE FROM source_outputs WHERE knowledge_path LIKE 'policy/%'"
        )
        connection.executemany(
            """
            INSERT INTO source_outputs (source_id, knowledge_path)
            VALUES (?, ?)
            """,
            sorted(output_sources),
        )
        report = policy_coverage_report(
            connection,
            retired_document_count=cumulative_retired,
        )
        if report.unlinked_section_count or report.binding_rate != 1.0:
            raise PolicyUpgradeError("正式policy存在无证据章节")
        connection.execute(
            """
            UPDATE import_batches
            SET status = 'applied', applied_at = ?, report_json = ?
            WHERE batch_id = ?
            """,
            (
                _utc_now(),
                json.dumps(
                    {
                        **asdict(report),
                        "retired_count_mode": "cumulative",
                    },
                    ensure_ascii=False,
                ),
                batch_id,
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        for target, backup in backups.items():
            if backup is None:
                target.unlink(missing_ok=True)
            else:
                temporary = target.with_suffix(target.suffix + ".restore.tmp")
                temporary.write_bytes(backup)
                temporary.replace(target)
        raise
    finally:
        connection.close()
    return AppliedPolicyUpgrade(
        output_count=len(document_paths),
        indexed_document_count=rebuild.document_count,
        indexed_chunk_count=rebuild.chunk_count,
    )
