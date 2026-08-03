from pathlib import Path
from types import SimpleNamespace

import pytest
import numpy
from PySide6.QtGui import QColor, QImage

from lexiaodu.ocr import (
    OcrError,
    OcrUnavailableError,
    PaddleOcrEngine,
    Speaker,
    TEXT_DETECTION_MAX_SIDE,
    TextBox,
    TranscriptLine,
    filter_visual_metadata,
    document_lines_from_paddle_results,
    infer_speaker,
    lines_from_paddle_results,
    qimage_to_bgr_array,
)


def test_document_ocr_keeps_centered_and_edge_text() -> None:
    results = [
        {
            "rec_texts": ["左侧标题", "居中课程参数"],
            "rec_boxes": [[0, 10, 50, 40], [450, 10, 550, 40]],
            "rec_scores": [0.99, 0.98],
        }
    ]

    lines = document_lines_from_paddle_results(results, image_width=1000)

    assert [line.text for line in lines] == ["左侧标题", "居中课程参数"]


def test_transcript_line_normalizes_string_speaker_from_qt_editor() -> None:
    line = TranscriptLine(speaker="家长", text="怎么请假")

    assert line.speaker is Speaker.PARENT


def test_transcript_line_rejects_unknown_speaker() -> None:
    with pytest.raises(ValueError, match="发言人"):
        TranscriptLine(speaker="未知", text="怎么请假")


def test_build_sorted_transcript_and_infer_speaker_from_position() -> None:
    results = [
        {
            "res": {
                "rec_texts": ["右侧回复", "左侧第二句", "左侧第一句"],
                "rec_boxes": [
                    [620, 20, 900, 60],
                    [50, 100, 350, 140],
                    [40, 10, 300, 50],
                ],
                "rec_scores": [0.97, 0.92, 0.95],
            }
        }
    ]

    lines = lines_from_paddle_results(results, image_width=1000)

    assert [line.text for line in lines] == [
        "左侧第一句",
        "右侧回复",
        "左侧第二句",
    ]
    assert [line.speaker for line in lines] == [
        Speaker.PARENT,
        Speaker.ADVISOR,
        Speaker.PARENT,
    ]
    assert lines[0].confidence == pytest.approx(0.95)


def test_center_line_is_classified_as_advisor() -> None:
    box = TextBox(left=400, top=10, right=600, bottom=40)

    assert infer_speaker(box, image_width=1000) is Speaker.ADVISOR


def test_filter_chat_timestamp_avatar_icons_and_low_confidence_noise() -> None:
    results = [
        {
            "rec_texts": [
                "16:45",
                "1234567",
                "0",
                "0",
                "上课时间是什么",
                "您好",
                "123",
                "456",
                "0",
                "噪声",
            ],
            "rec_boxes": [
                [1011, 0, 1052, 14],
                [81, 52, 177, 87],
                [15, 52, 45, 87],
                [20, 139, 50, 188],
                [81, 139, 248, 188],
                [1926, 243, 1977, 272],
                [1932, 336, 1978, 363],
                [1931, 430, 1979, 456],
                [2010, 243, 2040, 272],
                [100, 220, 180, 250],
            ],
            "rec_scores": [
                0.98,
                1.0,
                0.62,
                0.99,
                1.0,
                0.99,
                1.0,
                1.0,
                0.99,
                0.89,
            ],
        }
    ]

    lines = lines_from_paddle_results(results, image_width=2058)

    assert [(line.speaker, line.text) for line in lines] == [
        (Speaker.PARENT, "1234567"),
        (Speaker.PARENT, "上课时间是什么"),
        (Speaker.ADVISOR, "您好"),
        (Speaker.ADVISOR, "123"),
        (Speaker.ADVISOR, "456"),
    ]


def test_keep_high_confidence_single_digit_inside_message_area() -> None:
    results = [
        {
            "rec_texts": ["0"],
            "rec_boxes": [[81, 100, 101, 125]],
            "rec_scores": [0.99],
        }
    ]

    lines = lines_from_paddle_results(results, image_width=2058)

    assert [(line.speaker, line.text) for line in lines] == [
        (Speaker.PARENT, "0")
    ]


def test_keep_compatible_result_without_confidence() -> None:
    results = [{"rec_texts": ["缺少置信度"], "rec_boxes": [[80, 50, 220, 80]]}]

    lines = lines_from_paddle_results(results, image_width=1000)

    assert [line.text for line in lines] == ["缺少置信度"]
    assert lines[0].confidence is None


def test_reject_mismatched_paddle_text_and_box_counts() -> None:
    results = [{"rec_texts": ["有文字"], "rec_boxes": []}]

    with pytest.raises(OcrError, match="数量不一致"):
        lines_from_paddle_results(results, image_width=1000)


def test_convert_qimage_to_bgr_array_without_file_round_trip() -> None:
    image = QImage(2, 1, QImage.Format.Format_RGB32)
    image.fill(QColor(10, 20, 30))

    pixels = qimage_to_bgr_array(image, numpy)

    assert pixels.shape == (1, 2, 3)
    assert pixels[0, 0].tolist() == [30, 20, 10]


def test_runtime_import_failure_is_reported_as_ocr_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_import(name: str) -> None:
        raise RuntimeError(f"cannot import {name}")

    monkeypatch.setattr("lexiaodu.ocr.import_module", fail_import)
    engine = PaddleOcrEngine(Path("E:/DevCaches/paddlex"))

    with pytest.raises(OcrUnavailableError, match="未安装"):
        engine.recognize(QImage(10, 10, QImage.Format.Format_RGB32))


def test_preload_reuses_model_and_limits_large_detection_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructor_calls: list[dict[str, object]] = []
    predict_calls: list[dict[str, object]] = []

    class FakeModel:
        def predict(self, **kwargs: object) -> list[dict[str, object]]:
            predict_calls.append(kwargs)
            return [{"rec_texts": [], "rec_boxes": []}]

    def build_model(**kwargs: object) -> FakeModel:
        constructor_calls.append(kwargs)
        return FakeModel()

    paddleocr = SimpleNamespace(PaddleOCR=build_model)

    def fake_import(name: str) -> object:
        if name == "numpy":
            return numpy
        if name == "paddleocr":
            return paddleocr
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("lexiaodu.ocr.import_module", fake_import)
    engine = PaddleOcrEngine(Path("E:/DevCaches/paddlex"))
    image = QImage(2000, 800, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))

    engine.preload()
    assert engine.recognize(image) == []

    assert len(constructor_calls) == 1
    assert len(predict_calls) == 1
    assert numpy.array_equal(
        predict_calls[0]["input"],
        qimage_to_bgr_array(image, numpy),
    )
    assert (
        predict_calls[0]["text_det_limit_side_len"]
        == TEXT_DETECTION_MAX_SIDE
    )
    assert predict_calls[0]["text_det_limit_type"] == "max"


def test_filter_gray_nicknames_and_quoted_previews_from_chat_lines() -> None:
    pixels = numpy.full((220, 1000, 3), 255, dtype=numpy.uint8)
    nickname_box = TextBox(60, 10, 240, 30)
    parent_message_box = TextBox(80, 40, 300, 75)
    advisor_message_box = TextBox(650, 100, 920, 135)
    quote_preview_box = TextBox(560, 145, 900, 167)

    def draw_text_strokes(box: TextBox, value: int) -> None:
        pixels[
            box.top : box.bottom,
            box.left : box.right : 4,
        ] = value

    pixels[
        advisor_message_box.top - 2 : advisor_message_box.bottom + 2,
        advisor_message_box.left - 2 : advisor_message_box.right + 2,
    ] = [105, 236, 149]
    draw_text_strokes(nickname_box, 160)
    draw_text_strokes(parent_message_box, 15)
    draw_text_strokes(advisor_message_box, 15)
    draw_text_strokes(quote_preview_box, 165)
    lines = [
        TranscriptLine(
            Speaker.PARENT,
            "17网安-张义伟",
            nickname_box,
            0.99,
        ),
        TranscriptLine(
            Speaker.PARENT,
            "收到",
            parent_message_box,
            1.0,
        ),
        TranscriptLine(
            Speaker.ADVISOR,
            "老公上班累 那老婆负责上老公~",
            advisor_message_box,
            0.97,
        ),
        TranscriptLine(
            Speaker.ADVISOR,
            "我家小猫：我也不忍心看老公这么累呀",
            quote_preview_box,
            0.92,
        ),
    ]

    filtered = filter_visual_metadata(lines, pixels, numpy)

    assert [(line.speaker, line.text) for line in filtered] == [
        (Speaker.PARENT, "收到"),
        (Speaker.ADVISOR, "老公上班累 那老婆负责上老公~"),
    ]
