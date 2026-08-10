from __future__ import annotations

from dataclasses import dataclass

from .document_catalog import DocumentCatalog, DocumentRecord, hash_file


@dataclass(frozen=True, slots=True)
class DocumentCandidate:
    record: DocumentRecord
    score: int
    matched_tags: tuple[str, ...]


class DocumentRouter:
    def __init__(self, catalog: DocumentCatalog) -> None:
        self._catalog = catalog

    def select(
        self,
        query: str,
        *,
        eligible_formats: frozenset[str],
        limit: int = 3,
    ) -> tuple[DocumentCandidate, ...]:
        if not 1 <= limit <= 3:
            raise ValueError("候选数量必须在 1 到 3 之间")
        normalized_query = "".join(query.casefold().split())
        candidates: list[DocumentCandidate] = []
        for record in self._catalog.list_active():
            if record.format not in eligible_formats or not record.allow_upload:
                continue
            if not record.path.is_file() or hash_file(record.path) != record.sha256:
                continue
            matched = tuple(
                tag
                for tag in record.tags
                if "".join(tag.casefold().split()) in normalized_query
            )
            if matched:
                candidates.append(
                    DocumentCandidate(record, len(matched), matched)
                )
        candidates.sort(
            key=lambda candidate: (
                -candidate.score,
                candidate.record.display_name.casefold(),
                candidate.record.id,
            )
        )
        return tuple(candidates[:limit])
