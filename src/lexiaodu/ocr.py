from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol

from PySide6.QtGui import QImage


MIN_TEXT_CONFIDENCE = 0.90
EDGE_EXCLUSION_RATIO = 0.035
CENTER_EXCLUSION_MIN_RATIO = 0.40
CENTER_EXCLUSION_MAX_RATIO = 0.60


class OcrError(RuntimeError):
    """Raised when OCR cannot produce usable text results."""


class OcrUnavailableError(OcrError):
    """Raised when the local PaddleOCR runtime or model is unavailable."""


class Speaker(StrEnum):
    PARENT = "家长"
    ADVISOR = "顾问"


@dataclass(frozen=True, slots=True)
class TextBox:
    left: int
    top: int
    right: int
    bottom: int

    def __post_init__(self) -> None:
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError("文字位置必须是有效矩形")

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2


@dataclass(frozen=True, slots=True)
class TranscriptLine:
    speaker: Speaker
    text: str
    box: TextBox | None = None
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("发言文字不能为空")


class OcrEngine(Protocol):
    def recognize(self, image: QImage) -> list[TranscriptLine]:
        """Recognize positioned text from an in-memory image."""


def infer_speaker(box: TextBox, image_width: int) -> Speaker:
    if image_width <= 0:
        raise ValueError("图像宽度必须为正整数")
    if box.center_x < image_width / 2:
        return Speaker.PARENT
    return Speaker.ADVISOR


def _is_chat_message(
    box: TextBox,
    image_width: int,
    confidence: float | None,
) -> bool:
    if image_width <= 0:
        raise ValueError("图像宽度必须为正整数")
    if confidence is not None and confidence < MIN_TEXT_CONFIDENCE:
        return False

    edge_width = image_width * EDGE_EXCLUSION_RATIO
    if box.right <= edge_width or box.left >= image_width - edge_width:
        return False

    center_ratio = box.center_x / image_width
    return not (
        CENTER_EXCLUSION_MIN_RATIO
        <= center_ratio
        <= CENTER_EXCLUSION_MAX_RATIO
    )


def _result_payload(result: Any) -> Mapping[str, Any]:
    candidate = result
    if not isinstance(candidate, Mapping) and hasattr(candidate, "json"):
        candidate = result.json
        if callable(candidate):
            candidate = candidate()
    if not isinstance(candidate, Mapping):
        raise OcrError("PaddleOCR 返回了无法解析的结果")
    nested = candidate.get("res")
    if isinstance(nested, Mapping):
        return nested
    return candidate


def _box_from_value(value: Any) -> TextBox:
    try:
        coordinates = list(value)
    except TypeError as exc:
        raise OcrError("PaddleOCR 返回了无效的文字位置") from exc

    if len(coordinates) == 4 and all(
        not hasattr(coordinate, "__iter__") for coordinate in coordinates
    ):
        left, top, right, bottom = (int(coordinate) for coordinate in coordinates)
        return TextBox(left, top, right, bottom)

    try:
        points = [list(point) for point in coordinates]
        xs = [int(point[0]) for point in points]
        ys = [int(point[1]) for point in points]
    except (IndexError, TypeError, ValueError) as exc:
        raise OcrError("PaddleOCR 返回了无效的文字多边形") from exc
    if not xs or not ys:
        raise OcrError("PaddleOCR 返回了空文字位置")
    return TextBox(min(xs), min(ys), max(xs), max(ys))


def lines_from_paddle_results(
    results: Iterable[Any], image_width: int
) -> list[TranscriptLine]:
    """Convert PaddleOCR 3.x result mappings into editable transcript lines."""

    lines: list[TranscriptLine] = []
    for result in results:
        payload = _result_payload(result)
        texts = list(payload.get("rec_texts", ()))
        boxes_value = payload.get("rec_boxes")
        if boxes_value is None:
            boxes_value = payload.get("rec_polys", ())
        boxes = list(boxes_value)
        scores = list(payload.get("rec_scores", ()))
        if len(texts) != len(boxes):
            raise OcrError("PaddleOCR 返回的文字与位置数量不一致")

        for index, (text_value, box_value) in enumerate(zip(texts, boxes)):
            text = str(text_value).strip()
            if not text:
                continue
            box = _box_from_value(box_value)
            confidence = (
                float(scores[index]) if index < len(scores) else None
            )
            if not _is_chat_message(box, image_width, confidence):
                continue
            lines.append(
                TranscriptLine(
                    speaker=infer_speaker(box, image_width),
                    text=text,
                    box=box,
                    confidence=confidence,
                )
            )
    return sorted(
        lines,
        key=lambda line: (
            line.box.top if line.box is not None else 0,
            line.box.left if line.box is not None else 0,
        ),
    )


def qimage_to_bgr_array(image: QImage, numpy_module: Any) -> Any:
    """Copy a QImage into the BGR ndarray layout expected by PaddleOCR."""

    if image.isNull():
        raise OcrError("无法识别空截图")
    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    buffer = numpy_module.frombuffer(
        rgb.constBits(),
        dtype=numpy_module.uint8,
        count=rgb.sizeInBytes(),
    )
    rows = buffer.reshape((rgb.height(), rgb.bytesPerLine()))
    pixels = rows[:, : rgb.width() * 3].reshape((rgb.height(), rgb.width(), 3))
    return pixels[:, :, ::-1].copy()


class PaddleOcrEngine:
    """Lazy local PaddleOCR adapter; no image bytes are written to disk."""

    def __init__(self, model_cache_dir: Path) -> None:
        self._model_cache_dir = model_cache_dir
        self._model: Any | None = None
        self._numpy: Any | None = None

    def _load(self) -> None:
        if self._model is not None:
            return
        os.environ.setdefault(
            "PADDLE_PDX_CACHE_HOME", str(self._model_cache_dir.resolve())
        )
        os.environ.setdefault(
            "PADDLE_HOME",
            str((self._model_cache_dir.parent / "paddle").resolve()),
        )
        try:
            self._numpy = import_module("numpy")
            paddleocr = import_module("paddleocr")
            paddle_ocr = paddleocr.PaddleOCR
        except Exception as exc:
            raise OcrUnavailableError(
                "本地 PaddleOCR 未安装，请安装项目的 ocr 依赖"
            ) from exc

        try:
            self._model = paddle_ocr(
                device="cpu",
                text_detection_model_name="PP-OCRv5_mobile_det",
                text_recognition_model_name="PP-OCRv5_mobile_rec",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                text_rec_score_thresh=MIN_TEXT_CONFIDENCE,
            )
        except Exception as exc:
            raise OcrUnavailableError(f"本地 OCR 模型不可用: {exc}") from exc

    def recognize(self, image: QImage) -> list[TranscriptLine]:
        self._load()
        if self._numpy is None or self._model is None:
            raise OcrUnavailableError("本地 PaddleOCR 未正确初始化")
        try:
            pixels = qimage_to_bgr_array(image, self._numpy)
            results = self._model.predict(input=pixels)
            return lines_from_paddle_results(results, image.width())
        except OcrError:
            raise
        except Exception as exc:
            raise OcrError(f"OCR 识别失败: {exc}") from exc
