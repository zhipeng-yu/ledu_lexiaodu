from __future__ import annotations

from pathlib import Path

import pytest

from lexiaodu.document_catalog import DocumentCatalog, DocumentCatalogError
from lexiaodu.document_router import DocumentRouter
from lexiaodu.local_crypto import DataCipher


def make_catalog(tmp_path: Path) -> tuple[DocumentCatalog, Path]:
    root = tmp_path / "originals"
    root.mkdir()
    catalog = DocumentCatalog(
        tmp_path / "catalog.sqlite3",
        DataCipher(b"d" * 32),
        allowed_roots=(root,),
    )
    return catalog, root


def test_catalog_registers_original_bytes_without_parsing(tmp_path) -> None:
    catalog, root = make_catalog(tmp_path)
    source = root / "天津五年级语文.pdf"
    source.write_bytes(b"not-a-real-pdf-but-original-bytes")

    record = catalog.register(
        source,
        tags=("天津", "五年级", "语文"),
        allow_upload=True,
    )

    assert record.path == source.resolve()
    assert record.format == "pdf"
    assert record.tags == ("天津", "五年级", "语文")
    assert source.read_bytes() == b"not-a-real-pdf-but-original-bytes"


def test_catalog_rejects_files_outside_allowed_roots(tmp_path) -> None:
    catalog, _ = make_catalog(tmp_path)
    source = tmp_path / "outside.pdf"
    source.write_bytes(b"outside")

    with pytest.raises(DocumentCatalogError, match="允许目录"):
        catalog.register(source, tags=("天津",), allow_upload=True)


def test_router_selects_at_most_three_matching_originals(tmp_path) -> None:
    catalog, root = make_catalog(tmp_path)
    for index, tags in enumerate(
        (
            ("天津", "五年级", "语文"),
            ("天津", "五年级", "阅读"),
            ("天津", "语文", "班型"),
            ("上海", "五年级", "语文"),
        )
    ):
        source = root / f"document-{index}.pdf"
        source.write_bytes(f"file-{index}".encode())
        catalog.register(source, tags=tags, allow_upload=True)

    selected = DocumentRouter(catalog).select(
        "天津五年级语文班型怎么选",
        eligible_formats=frozenset({"pdf"}),
    )

    assert 1 <= len(selected) <= 3
    assert selected[0].matched_tags == ("天津", "五年级", "语文")
    assert all(candidate.record.format == "pdf" for candidate in selected)


def test_router_excludes_default_denied_and_changed_files(tmp_path) -> None:
    catalog, root = make_catalog(tmp_path)
    denied = root / "denied.pdf"
    denied.write_bytes(b"denied")
    catalog.register(denied, tags=("天津",), allow_upload=False)
    changed = root / "changed.pdf"
    changed.write_bytes(b"v1")
    catalog.register(changed, tags=("天津",), allow_upload=True)
    changed.write_bytes(b"v2")

    selected = DocumentRouter(catalog).select(
        "天津",
        eligible_formats=frozenset({"pdf"}),
    )

    assert selected == ()


def test_router_respects_verified_format_set(tmp_path) -> None:
    catalog, root = make_catalog(tmp_path)
    source = root / "course.docx"
    source.write_bytes(b"original-docx")
    catalog.register(source, tags=("天津", "课程"), allow_upload=True)

    selected = DocumentRouter(catalog).select(
        "天津课程",
        eligible_formats=frozenset({"pdf"}),
    )

    assert selected == ()
