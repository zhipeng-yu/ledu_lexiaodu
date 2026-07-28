import pytest

from lexiaodu.capture import CaptureError, local_region
from lexiaodu.domain import ScreenRegion


def test_translate_desktop_region_to_secondary_screen_coordinates() -> None:
    screen = ScreenRegion(x=-1920, y=0, width=1920, height=1080)
    region = ScreenRegion(x=-1800, y=100, width=400, height=300)

    assert local_region(region, screen) == ScreenRegion(
        x=120, y=100, width=400, height=300
    )


def test_reject_region_crossing_screen_boundary() -> None:
    screen = ScreenRegion(x=0, y=0, width=1920, height=1080)
    crossing = ScreenRegion(x=1800, y=100, width=200, height=200)

    with pytest.raises(CaptureError, match="同一个屏幕"):
        local_region(crossing, screen)
