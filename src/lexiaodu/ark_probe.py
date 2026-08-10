from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Protocol


SUPPORTED_FORMATS = frozenset({"pdf", "docx", "pptx", "xlsx"})


@dataclass(frozen=True, slots=True)
class ProbeCase:
    case_id: str
    path: Path
    format: str
    question: str
    expected_answer: str
    expected_locator: str
    content_kind: str


@dataclass(frozen=True, slots=True)
class ProbeAnswer:
    answer: str
    locator: str


class OriginalFileProbeTransport(Protocol):
    def upload(self, path: Path, sha256: str) -> str: ...

    def ask(self, file_id: str, question: str) -> ProbeAnswer: ...

    def delete(self, file_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ProbeCaseResult:
    case_id: str
    format: str
    content_kind: str
    answer_correct: bool
    locator_correct: bool
    hash_unchanged: bool
    cleanup_succeeded: bool
    error_category: str | None
    file_id_hash: str | None
    duration_seconds: float

    @property
    def passed(self) -> bool:
        return (
            self.answer_correct
            and self.locator_correct
            and self.hash_unchanged
            and self.cleanup_succeeded
            and self.error_category is None
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "format": self.format,
            "content_kind": self.content_kind,
            "answer_correct": self.answer_correct,
            "locator_correct": self.locator_correct,
            "hash_unchanged": self.hash_unchanged,
            "cleanup_succeeded": self.cleanup_succeeded,
            "error_category": self.error_category,
            "file_id_hash": self.file_id_hash,
            "duration_seconds": self.duration_seconds,
        }


@dataclass(frozen=True, slots=True)
class FormatDecision:
    decision: str
    case_count: int
    passed_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "case_count": self.case_count,
            "passed_count": self.passed_count,
        }


@dataclass(frozen=True, slots=True)
class ProbeReport:
    cases: tuple[ProbeCaseResult, ...]
    formats: Mapping[str, FormatDecision]

    def to_dict(self) -> dict[str, object]:
        return {
            "cases": [case.to_dict() for case in self.cases],
            "formats": {
                format: decision.to_dict()
                for format, decision in sorted(self.formats.items())
            },
        }


def run_probe(
    cases: Iterable[ProbeCase],
    transport: OriginalFileProbeTransport,
    clock: Callable[[], float],
    *,
    timeout_seconds: float,
) -> ProbeReport:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    results = tuple(
        _run_case(case, transport, clock)
        for case in cases
    )
    formats: dict[str, FormatDecision] = {}
    for format in dict.fromkeys(result.format for result in results):
        format_results = tuple(
            result for result in results if result.format == format
        )
        passed_count = sum(result.passed for result in format_results)
        formats[format] = FormatDecision(
            decision=(
                "GO"
                if format_results and passed_count == len(format_results)
                else "NO_GO"
            ),
            case_count=len(format_results),
            passed_count=passed_count,
        )
    return ProbeReport(results, MappingProxyType(formats))


def _run_case(
    case: ProbeCase,
    transport: OriginalFileProbeTransport,
    clock: Callable[[], float],
) -> ProbeCaseResult:
    started = clock()
    format = case.format.strip().casefold()
    file_id: str | None = None
    file_id_hash: str | None = None
    answer_correct = False
    locator_correct = False
    hash_unchanged = False
    cleanup_succeeded = True
    error_category: str | None = None
    initial_hash: str | None = None

    if format not in SUPPORTED_FORMATS or case.path.suffix.casefold() != f".{format}":
        error_category = "invalid_format"
    else:
        try:
            initial_hash = _sha256(case.path)
            file_id = transport.upload(case.path, initial_hash)
            file_id_hash = hashlib.sha256(file_id.encode("utf-8")).hexdigest()
            answer = transport.ask(file_id, case.question)
            answer_correct = _contains(answer.answer, case.expected_answer)
            locator_correct = _contains(answer.locator, case.expected_locator)
        except TimeoutError:
            error_category = "timeout"
        except (OSError, ValueError):
            error_category = "invalid_input"
        except Exception:
            error_category = "service"
        finally:
            if file_id is not None:
                try:
                    transport.delete(file_id)
                except Exception:
                    cleanup_succeeded = False
                    error_category = error_category or "cleanup"
            if initial_hash is not None:
                try:
                    hash_unchanged = _sha256(case.path) == initial_hash
                except OSError:
                    hash_unchanged = False

    finished = clock()
    return ProbeCaseResult(
        case_id=case.case_id,
        format=format,
        content_kind=case.content_kind,
        answer_correct=answer_correct,
        locator_correct=locator_correct,
        hash_unchanged=hash_unchanged,
        cleanup_succeeded=cleanup_succeeded,
        error_category=error_category,
        file_id_hash=file_id_hash,
        duration_seconds=max(0.0, finished - started),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contains(actual: str, expected: str) -> bool:
    normalized_expected = _normalize(expected)
    return bool(normalized_expected) and normalized_expected in _normalize(actual)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()
