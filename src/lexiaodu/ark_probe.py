from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol


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


class ProbeTransportError(RuntimeError):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


class ManifestError(ValueError):
    pass


def load_probe_manifest(
    sample_root: Path,
    manifest_path: Path,
) -> tuple[ProbeCase, ...]:
    try:
        root = sample_root.resolve(strict=True)
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError("无法读取能力探针清单") from exc
    if not root.is_dir() or payload.get("schema_version") != 1:
        raise ManifestError("能力探针清单版本或样本目录无效")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ManifestError("能力探针清单必须包含用例")

    cases: list[ProbeCase] = []
    case_ids: set[str] = set()
    for raw in raw_cases:
        try:
            case_id = _required_manifest_text(raw, "case_id")
            relative_path = Path(_required_manifest_text(raw, "relative_path"))
            format = _required_manifest_text(raw, "format").casefold()
            path = (root / relative_path).resolve(strict=True)
            if not path.is_relative_to(root) or not path.is_file():
                raise ManifestError("样本路径超出允许目录")
            if format not in SUPPORTED_FORMATS or path.suffix.casefold() != f".{format}":
                raise ManifestError("样本扩展名与格式不一致")
            if case_id in case_ids:
                raise ManifestError("能力探针用例 ID 重复")
            case_ids.add(case_id)
            cases.append(
                ProbeCase(
                    case_id=case_id,
                    path=path,
                    format=format,
                    question=_required_manifest_text(raw, "question"),
                    expected_answer=_required_manifest_text(raw, "expected_answer"),
                    expected_locator=_required_manifest_text(raw, "expected_locator"),
                    content_kind=_required_manifest_text(raw, "content_kind"),
                )
            )
        except (KeyError, TypeError, OSError) as exc:
            raise ManifestError("能力探针用例字段或路径无效") from exc
    return tuple(cases)


class ArkFileApiProbeTransport:
    """Probe adapter for Ark Files API + Responses API PDF input."""

    def __init__(
        self,
        client: Any,
        model: str,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        poll_interval_seconds: float = 0.5,
        ready_timeout_seconds: float = 300.0,
    ) -> None:
        if not model.strip():
            raise ValueError("模型名称不能为空")
        if poll_interval_seconds <= 0 or ready_timeout_seconds <= 0:
            raise ValueError("轮询间隔和等待超时必须大于 0")
        self._client = client
        self._model = model.strip()
        self._sleep = sleep
        self._monotonic = monotonic
        self._poll_interval_seconds = poll_interval_seconds
        self._ready_timeout_seconds = ready_timeout_seconds

    def upload(self, path: Path, sha256: str) -> str:
        if path.suffix.casefold() != ".pdf":
            raise ProbeTransportError(
                "unsupported_format",
                "方舟 Files API 的文档输入当前只支持 PDF",
            )
        if _sha256(path) != sha256:
            raise ProbeTransportError("invalid_input", "上传前文件哈希不一致")
        try:
            with path.open("rb") as source:
                uploaded = self._client.files.create(
                    file=source,
                    purpose="user_data",
                )
            file_id = getattr(uploaded, "id", None)
            if not isinstance(file_id, str) or not file_id:
                raise ProbeTransportError(
                    "invalid_response",
                    "Files API 未返回文件 ID",
                )
            self._wait_until_active(file_id)
            return file_id
        except ProbeTransportError:
            raise
        except Exception as exc:
            raise _provider_error(exc, "上传 PDF 失败") from exc

    def ask(self, file_id: str, question: str) -> ProbeAnswer:
        prompt = (
            "只根据所附 PDF 回答用户问题。返回且只返回一个 JSON 对象，"
            '格式为 {"answer":"简洁答案","locator":"第 N 页"}。'
            "locator 必须是支撑答案的 PDF 页码；无法确定时使用空字符串，"
            "不得猜测。\n用户问题："
            f"{question}"
        )
        try:
            response = self._client.responses.create(
                model=self._model,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_file", "file_id": file_id},
                            {"type": "input_text", "text": prompt},
                        ],
                    }
                ],
            )
            output_text = getattr(response, "output_text", None)
            if not isinstance(output_text, str) or not output_text.strip():
                raise ProbeTransportError(
                    "invalid_response",
                    "Responses API 未返回文本",
                )
            payload = json.loads(output_text)
            answer = payload.get("answer")
            locator = payload.get("locator")
            if not isinstance(answer, str) or not isinstance(locator, str):
                raise ProbeTransportError(
                    "invalid_response",
                    "Responses API 返回的定位 JSON 无效",
                )
            return ProbeAnswer(answer=answer.strip(), locator=locator.strip())
        except ProbeTransportError:
            raise
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            raise ProbeTransportError(
                "invalid_response",
                "Responses API 返回的定位 JSON 无效",
            ) from exc
        except Exception as exc:
            raise _provider_error(exc, "PDF 提问失败") from exc

    def delete(self, file_id: str) -> None:
        try:
            self._client.files.delete(file_id)
        except Exception as exc:
            raise _provider_error(exc, "删除远端文件失败") from exc

    def _wait_until_active(self, file_id: str) -> None:
        deadline = self._monotonic() + self._ready_timeout_seconds
        while True:
            remote = self._client.files.retrieve(file_id)
            status = getattr(remote, "status", None)
            if status == "active":
                return
            if status in {"failed", "error", "cancelled", "expired"}:
                raise ProbeTransportError(
                    "service",
                    "方舟文件预处理未成功",
                )
            if self._monotonic() >= deadline:
                raise ProbeTransportError("timeout", "等待方舟文件就绪超时")
            self._sleep(self._poll_interval_seconds)


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
    phase = "before_upload"

    if format not in SUPPORTED_FORMATS or case.path.suffix.casefold() != f".{format}":
        error_category = "invalid_format"
    else:
        try:
            initial_hash = _sha256(case.path)
            phase = "uploading"
            file_id = transport.upload(case.path, initial_hash)
            file_id_hash = hashlib.sha256(file_id.encode("utf-8")).hexdigest()
            phase = "asking"
            answer = transport.ask(file_id, case.question)
            answer_correct = _contains(answer.answer, case.expected_answer)
            locator_correct = _contains(answer.locator, case.expected_locator)
        except ProbeTransportError as exc:
            error_category = exc.category
            if (
                phase == "uploading"
                and file_id is None
                and exc.category in {"service", "timeout"}
            ):
                cleanup_succeeded = False
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


def _required_manifest_text(payload: object, field: str) -> str:
    if not isinstance(payload, dict):
        raise ManifestError("能力探针用例必须是对象")
    value = payload[field]
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"能力探针字段 {field} 不能为空")
    return value.strip()


def _provider_error(exc: Exception, fallback_message: str) -> ProbeTransportError:
    status_code = getattr(exc, "status_code", None)
    if status_code in {401}:
        category = "auth"
    elif status_code in {403}:
        category = "permission"
    elif status_code in {408}:
        category = "timeout"
    elif status_code in {413}:
        category = "size_limit"
    elif status_code in {429}:
        category = "rate_limit"
    elif isinstance(status_code, int) and status_code >= 500:
        category = "service"
    else:
        category = "service"
    return ProbeTransportError(category, fallback_message)
