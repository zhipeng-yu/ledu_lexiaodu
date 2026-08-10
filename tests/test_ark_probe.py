from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lexiaodu.ark_probe import (
    ArkFileApiProbeTransport,
    ManifestError,
    ProbeAnswer,
    ProbeCase,
    ProbeTransportError,
    load_probe_manifest,
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


class FakeFilesApi:
    def __init__(self) -> None:
        self.created: list[tuple[bytes, str, str]] = []
        self.retrieved: list[str] = []
        self.deleted: list[str] = []
        self.statuses = ["processing", "active"]

    def create(self, *, file, purpose: str):
        self.created.append((file.read(), file.name, purpose))
        return SimpleNamespace(id="file-provider-secret")

    def retrieve(self, file_id: str):
        self.retrieved.append(file_id)
        return SimpleNamespace(status=self.statuses.pop(0))

    def delete(self, file_id: str):
        self.deleted.append(file_id)
        return SimpleNamespace(deleted=True)


class FakeResponsesApi:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.calls: list[dict[str, object]] = []

    def create(self, **options):
        self.calls.append(options)
        return SimpleNamespace(output_text=self.output_text)


def make_ark_client(output_text: str = '{"answer":"18","locator":"第 3 页"}'):
    return SimpleNamespace(
        files=FakeFilesApi(),
        responses=FakeResponsesApi(output_text),
    )


def test_ark_file_transport_uploads_exact_pdf_and_waits_until_active(tmp_path) -> None:
    path = tmp_path / "unchanged.pdf"
    original = b"%PDF-1.7\nfictional sentinel"
    path.write_bytes(original)
    client = make_ark_client()
    sleeps: list[float] = []
    transport = ArkFileApiProbeTransport(
        client,
        "doubao-test",
        sleep=sleeps.append,
        poll_interval_seconds=0.01,
        ready_timeout_seconds=1.0,
    )

    file_id = transport.upload(path, hashlib.sha256(original).hexdigest())

    assert file_id == "file-provider-secret"
    assert client.files.created == [(original, str(path), "user_data")]
    assert client.files.retrieved == [file_id, file_id]
    assert sleeps == [0.01]
    assert path.read_bytes() == original


def test_ark_file_transport_rejects_office_format_without_upload(tmp_path) -> None:
    path = tmp_path / "unsupported.docx"
    path.write_bytes(b"fictional")
    client = make_ark_client()
    transport = ArkFileApiProbeTransport(client, "doubao-test")

    with pytest.raises(ProbeTransportError, match="PDF") as raised:
        transport.upload(path, hashlib.sha256(path.read_bytes()).hexdigest())

    assert raised.value.category == "unsupported_format"
    assert client.files.created == []


def test_ark_file_transport_asks_responses_api_for_json_locator() -> None:
    client = make_ark_client()
    transport = ArkFileApiProbeTransport(client, "doubao-test")

    answer = transport.ask("file-provider-secret", "虚构项目课次数？")

    assert answer == ProbeAnswer(answer="18", locator="第 3 页")
    options = client.responses.calls[0]
    assert options["model"] == "doubao-test"
    assert options["input"][0]["content"][0] == {
        "type": "input_file",
        "file_id": "file-provider-secret",
    }
    prompt = options["input"][0]["content"][1]
    assert prompt["type"] == "input_text"
    assert "虚构项目课次数？" in prompt["text"]
    assert "locator" in prompt["text"]


def test_ark_file_transport_rejects_invalid_response_and_deletes_file() -> None:
    client = make_ark_client("not-json")
    transport = ArkFileApiProbeTransport(client, "doubao-test")

    with pytest.raises(ProbeTransportError) as raised:
        transport.ask("file-provider-secret", "question")
    transport.delete("file-provider-secret")

    assert raised.value.category == "invalid_response"
    assert client.files.deleted == ["file-provider-secret"]


def test_probe_preserves_transport_error_category(tmp_path) -> None:
    case = make_case(tmp_path)
    transport = FakeTransport(
        {case.question: ProbeTransportError("permission", "denied")}
    )

    report = run_probe((case,), transport, SteppingClock(), timeout_seconds=30)

    assert report.cases[0].error_category == "permission"


@pytest.mark.parametrize(
    ("category", "cleanup_succeeded"),
    (("service", False), ("timeout", False), ("unsupported_format", True)),
)
def test_probe_marks_remote_cleanup_uncertain_when_upload_may_have_landed(
    tmp_path,
    category,
    cleanup_succeeded,
) -> None:
    case = make_case(tmp_path)

    class UploadFailureTransport(FakeTransport):
        def upload(self, path: Path, sha256: str) -> str:
            raise ProbeTransportError(category, "upload failed")

    transport = UploadFailureTransport({})

    report = run_probe((case,), transport, SteppingClock(), timeout_seconds=30)

    assert report.cases[0].cleanup_succeeded is cleanup_succeeded


def test_manifest_loader_resolves_only_files_inside_sample_root(tmp_path) -> None:
    sample_root = tmp_path / "inputs"
    sample_root.mkdir()
    document = sample_root / "fictional.pdf"
    document.write_bytes(b"%PDF-fictional")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cases": [
                    {
                        "case_id": "pdf-text-01",
                        "relative_path": "fictional.pdf",
                        "format": "pdf",
                        "question": "问题",
                        "expected_answer": "答案",
                        "expected_locator": "第 1 页",
                        "content_kind": "text",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    cases = load_probe_manifest(sample_root, manifest)

    assert cases == (
        ProbeCase(
            case_id="pdf-text-01",
            path=document,
            format="pdf",
            question="问题",
            expected_answer="答案",
            expected_locator="第 1 页",
            content_kind="text",
        ),
    )


@pytest.mark.parametrize("relative_path", ("../outside.pdf", "missing.pdf"))
def test_manifest_loader_rejects_escape_and_missing_file(
    tmp_path,
    relative_path,
) -> None:
    sample_root = tmp_path / "inputs"
    sample_root.mkdir()
    (tmp_path / "outside.pdf").write_bytes(b"outside")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cases": [
                    {
                        "case_id": "pdf-text-01",
                        "relative_path": relative_path,
                        "format": "pdf",
                        "question": "问题",
                        "expected_answer": "答案",
                        "expected_locator": "第 1 页",
                        "content_kind": "text",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ManifestError):
        load_probe_manifest(sample_root, manifest)
