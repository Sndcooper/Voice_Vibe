"""voicevibe.focus: "computer focus on my cursor" pins a screen region.

The frame window is replaced by a recorder; the clock is injected.
"""

from __future__ import annotations

import unittest

import stubs

stubs.install()

from voicevibe import focus  # noqa: E402
from voicevibe.focus import FocusPin, region_around  # noqa: E402

MONITOR = (0, 0, 1920, 1200)


class FakeFrame:
    def __init__(self) -> None:
        self.calls: list = []

    def show(self, rect, seconds=None):  # noqa: ANN001, ANN201
        self.calls.append(("show", tuple(rect), seconds))

    def hide(self):  # noqa: ANN201
        self.calls.append(("hide",))


class RegionTests(unittest.TestCase):
    def test_centered_on_the_pointer(self) -> None:
        self.assertEqual(region_around((960, 600), MONITOR), (560, 350, 1360, 850))

    def test_clamped_inside_the_monitor(self) -> None:
        self.assertEqual(region_around((10, 10), MONITOR), (0, 0, 800, 500))
        self.assertEqual(region_around((1915, 1195), MONITOR), (1120, 700, 1920, 1200))

    def test_second_monitor_with_negative_coordinates(self) -> None:
        left = (-1280, 0, 0, 1024)
        self.assertEqual(region_around((-5, 500), left), (-800, 250, 0, 750))

    def test_small_monitor_is_the_whole_monitor(self) -> None:
        tiny = (0, 0, 640, 400)
        self.assertEqual(region_around((320, 200), tiny), tiny)

    def test_custom_size(self) -> None:
        self.assertEqual(region_around((960, 600), MONITOR, size=(400, 200)),
                         (760, 500, 1160, 700))


class PinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = [1000.0]
        self.frame = FakeFrame()
        self.pin = FocusPin(seconds=120, frame=self.frame, clock=lambda: self.now[0],
                            pointer=lambda: (960, 600), monitor_at=lambda p: MONITOR)

    def test_pin_uses_the_pointer_and_shows_the_frame(self) -> None:
        rect = self.pin.pin()
        self.assertEqual(rect, (560, 350, 1360, 850))
        self.assertEqual(self.pin.current(), rect)
        self.assertEqual(self.frame.calls[-1], ("show", rect, 120))

    def test_expires_after_the_timeout(self) -> None:
        self.pin.pin()
        self.now[0] += 119
        self.assertIsNotNone(self.pin.current())
        self.now[0] += 2
        self.assertIsNone(self.pin.current())
        self.assertEqual(self.frame.calls[-1], ("hide",))

    def test_unpin(self) -> None:
        self.pin.pin()
        self.assertTrue(self.pin.unpin())
        self.assertIsNone(self.pin.current())
        self.assertEqual(self.frame.calls[-1], ("hide",))
        self.assertFalse(self.pin.unpin())

    def test_repin_moves_and_restarts_the_clock(self) -> None:
        self.pin.pin()
        self.now[0] += 100
        self.pin.pointer = lambda: (100, 100)
        self.assertEqual(self.pin.pin(), (0, 0, 800, 500))
        self.now[0] += 100
        self.assertEqual(self.pin.current(), (0, 0, 800, 500))

    def test_pin_explicit_rect(self) -> None:
        self.assertEqual(self.pin.pin(rect=(1, 2, 3, 4)), (1, 2, 3, 4))

    def test_remaining(self) -> None:
        self.pin.pin()
        self.now[0] += 20
        self.assertAlmostEqual(self.pin.remaining(), 100)


class FrameRenderTests(unittest.TestCase):
    def test_render_is_an_outline_the_size_of_the_region(self) -> None:
        image, origin = focus.render_frame((100, 200, 900, 700))
        self.assertEqual(image.size, (800 + 2 * focus.FRAME_PAD, 500 + 2 * focus.FRAME_PAD))
        self.assertEqual(origin, (100 - focus.FRAME_PAD, 200 - focus.FRAME_PAD))
        cx, cy = image.size[0] // 2, image.size[1] // 2
        self.assertEqual(image.getpixel((cx, cy))[3], 0)  # the inside stays clear
        self.assertGreater(image.getpixel((cx, 1))[3], 0)  # the edge is drawn


if __name__ == "__main__":
    unittest.main()
