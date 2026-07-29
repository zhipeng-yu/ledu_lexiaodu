from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PySide6.QtGui import QGuiApplication, QImage, QScreen

from lexiaodu.domain import ScreenRegion


class CaptureError(RuntimeError):
    """Raised when a requested screen region cannot be captured."""


@dataclass(frozen=True, slots=True)
class CaptureResult:
    image: QImage
    region: ScreenRegion
    screen_name: str

    @property
    def pixel_width(self) -> int:
        return self.image.width()

    @property
    def pixel_height(self) -> int:
        return self.image.height()


class ScreenCapture(Protocol):
    def capture(self, region: ScreenRegion) -> CaptureResult:
        """Capture one logical desktop region into memory."""


def screen_bounds(screen: QScreen) -> ScreenRegion:
    geometry = screen.geometry()
    return ScreenRegion(
        x=geometry.x(),
        y=geometry.y(),
        width=geometry.width(),
        height=geometry.height(),
    )


def local_region(region: ScreenRegion, bounds: ScreenRegion) -> ScreenRegion:
    """Translate a desktop region into screen-local coordinates."""

    if not region.is_within(bounds):
        raise CaptureError("截图区域必须完整位于同一个屏幕内")
    return ScreenRegion(
        x=region.x - bounds.x,
        y=region.y - bounds.y,
        width=region.width,
        height=region.height,
    )


class QtScreenCapture:
    """QScreen adapter that keeps the captured pixels in memory."""

    def capture(self, region: ScreenRegion) -> CaptureResult:
        if QGuiApplication.instance() is None:
            raise CaptureError("截图前必须先创建 Qt 应用")

        screen = next(
            (
                candidate
                for candidate in QGuiApplication.screens()
                if region.is_within(screen_bounds(candidate))
            ),
            None,
        )
        if screen is None:
            raise CaptureError("截图区域不在任何单个可用屏幕内")

        relative = local_region(region, screen_bounds(screen))
        pixmap = screen.grabWindow(
            0,
            relative.x,
            relative.y,
            relative.width,
            relative.height,
        )
        if pixmap.isNull():
            raise CaptureError("Qt 未能从目标屏幕取得图像")

        return CaptureResult(
            image=pixmap.toImage().copy(),
            region=region,
            screen_name=screen.name(),
        )
