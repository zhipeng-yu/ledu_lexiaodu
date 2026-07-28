import pytest

from lexiaodu.domain import ScreenRegion, centered_region


def test_screen_region_requires_positive_size() -> None:
    with pytest.raises(ValueError):
        ScreenRegion(x=0, y=0, width=0, height=10)


def test_centered_region_clamps_to_screen_bounds() -> None:
    bounds = ScreenRegion(x=-1920, y=0, width=1920, height=1080)

    region = centered_region(bounds, desired_width=3000, desired_height=200)

    assert region == ScreenRegion(x=-1920, y=440, width=1920, height=200)
    assert region.is_within(bounds)
