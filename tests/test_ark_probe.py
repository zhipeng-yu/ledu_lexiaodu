from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from lexiaodu.ark_probe import (
    ProbeAnswer,
    ProbeCase,
    run_probe,
)


class FakeTransport:
    def __init__(
        self,
        answers: dict[str, ProbeAnswer | BaseException],
        *,
        mutate_on_upload: bool = False,
    ) -> None:
        self.answers = answers
        self.mutate_on_upload = mutate_on_upload
        self.uploads: list[tuple[Path, str]] = []
        self.deleted: list[str] = []

    def upload(self, path: Path, sha256: str) -> str:
        self.uploads.append((path, sha256))
        if self.mutate_on_upload:
            path.write_bytes(path.read_bytes() + b"changed")
        return f"file-{path.stem}"

    def ask(self, file_id: str, question: str) -> ProbeAnswer:
        answer = self.answers[question]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def delete(self, file_id: str) -> None:
        self.deleted.append(file_id)


class SteppingClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        self.value += 0.25
        return self.value


def make_case(
    tmp_path: Path,
    *,
    case_id: str = "pdf-text-01",
    suffix: str = ".pdf",
    format: str = "pdf",
    question: str = "虚构项目 A 的课次数是多少？",
    expected_answer: str = "18",
    expected_locator: str = "第 3 页",
    content_kind: str = "text",
) -> ProbeCase:
    path = tmp_path / f"sample{suffix}"
    path.write_bytes(b"fictional-original-file")
    return ProbeCase(
        case_id=case_id,
        path=path,
        format=format,
        question=question,
        expected_answer=expected_answer,
        expected_locator=expected_locator,
        content_kind=content_kind,
    )


def test_probe_passes_streamed_hash_and_detects_unchanged_original(tmp_path) -> None:
    case = make_case(tmp_path)
    expected_hash = hashlib.sha256(case.path.read_bytes()).hexdigest()
    transport = FakeTransport(
        {case.question: ProbeAnswer("课次数是 18", "第 3 页")}
    )

    report = run_probe((case,), transport, SteppingClock(), timeout_seconds=30)

    assert transport.uploads == [(case.path, expected_hash)]
    assert report.cases[0].hash_unchanged
    assert report.formats["pdf"].decision == "GO"


def test_probe_rejects_answer_without_locator(tmp_path) -> None:
    case = make_case(tmp_path)
    transport = FakeTransport(
        {case.question: ProbeAnswer("课次数是 18", "")}
    )

    report = run_probe((case,), transport, SteppingClock(), timeout_seconds=30)

    assert report.cases[0].answer_correct
    assert not report.cases[0].locator_correct
    assert report.formats["pdf"].decision == "NO_GO"


def test_probe_deletes_uploaded_file_when_query_fails(tmp_path) -> None:
    case = make_case(tmp_path)
    transport = FakeTransport({case.question: RuntimeError("service failed")})

    report = run_probe((case,), transport, SteppingClock(), timeout_seconds=30)

    assert transport.deleted == ["file-sample"]
    assert report.cases[0].error_category == "service"
    assert report.cases[0].cleanup_succeeded


def test_probe_report_omits_sensitive_inputs_and_provider_identifiers(tmp_path) -> None:
    case = make_case(
        tmp_path,
        question="PRIVATE QUESTION SENTINEL",
        expected_answer="PRIVATE ANSWER SENTINEL",
        expected_locator="PRIVATE LOCATOR SENTINEL",
    )
    transport = FakeTransport(
        {
            case.question: ProbeAnswer(
                "PRIVATE ANSWER SENTINEL",
                "PRIVATE LOCATOR SENTINEL",
            )
        }
    )

    report = run_probe((case,), transport, SteppingClock(), timeout_seconds=30)
    serialized = json.dumps(report.to_dict(), ensure_ascii=False)

    for secret in (
        str(case.path),
        case.question,
        case.expected_answer,
        case.expected_locator,
        "file-sample",
    ):
        assert secret not in serialized
    assert report.cases[0].file_id_hash


def test_timeout_marks_only_its_case_failed(tmp_path) -> None:
    timed_out = make_case(
        tmp_path,
        case_id="pdf-timeout",
        question="timeout question",
    )
    passed_path = tmp_path / "passed.pdf"
    passed_path.write_bytes(b"second-fictional-file")
    passed = ProbeCase(
        case_id="pdf-pass",
        path=passed_path,
        format="pdf",
        question="pass question",
        expected_answer="18",
        expected_locator="第 3 页",
        content_kind="table",
    )
    transport = FakeTransport(
        {
            timed_out.question: TimeoutError("slow"),
            passed.question: ProbeAnswer("18", "第 3 页"),
        }
    )

    report = run_probe(
        (timed_out, passed),
        transport,
        SteppingClock(),
        timeout_seconds=30,
    )

    assert report.cases[0].error_category == "timeout"
    assert report.cases[1].passed
    assert len(transport.uploads) == 2


@pytest.mark.parametrize("format", ("pdf", "docx", "pptx", "xlsx"))
def test_probe_supports_each_required_original_format(
    tmp_path,
    format,
) -> None:
    case = make_case(
        tmp_path,
        case_id=f"{format}-text-01",
        suffix=f".{format}",
        format=format,
    )
    transport = FakeTransport(
        {case.question: ProbeAnswer("18", case.expected_locator)}
    )

    report = run_probe((case,), transport, SteppingClock(), timeout_seconds=30)

    assert report.cases[0].passed
    assert report.formats[format].decision == "GO"


def test_probe_rejects_extension_mismatch_without_uploading(tmp_path) -> None:
    case = make_case(tmp_path, suffix=".docx", format="pdf")
    transport = FakeTransport({})

    report = run_probe((case,), transport, SteppingClock(), timeout_seconds=30)

    assert transport.uploads == []
    assert report.cases[0].error_category == "invalid_format"
    assert report.formats["pdf"].decision == "NO_GO"


def test_probe_rejects_original_file_mutation(tmp_path) -> None:
    case = make_case(tmp_path)
    transport = FakeTransport(
        {case.question: ProbeAnswer("18", "第 3 页")},
        mutate_on_upload=True,
    )

    report = run_probe((case,), transport, SteppingClock(), timeout_seconds=30)

    assert not report.cases[0].hash_unchanged
    assert not report.cases[0].passed
    assert report.formats["pdf"].decision == "NO_GO"


def test_probe_report_format_decisions_are_immutable(tmp_path) -> None:
    case = make_case(tmp_path)
    transport = FakeTransport(
        {case.question: ProbeAnswer("18", "第 3 页")}
    )
    report = run_probe((case,), transport, SteppingClock(), timeout_seconds=30)

    with pytest.raises(TypeError):
        report.formats["pdf"] = report.formats["pdf"]
