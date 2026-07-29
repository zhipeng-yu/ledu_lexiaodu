from pathlib import Path

import pytest
import numpy
from PySide6.QtGui import QColor, QImage

from lexiaodu.ocr import (
    OcrError,
    OcrUnavailableError,
    PaddleOcrEngine,
    Speaker,
    TextBox,
    infer_speaker,
    lines_from_paddle_results,
    qimage_to_bgr_array,
)


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
