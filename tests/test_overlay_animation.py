"""Run with the overlay's PySide6 environment to validate Qt transitions."""
import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None

ASSETS = Path(__file__).resolve().parents[1] / "assets"


class Packets:
    def __init__(self):
        self.queue = []

    def recvfrom(self, size):
        if not self.queue:
            raise BlockingIOError
        return self.queue.pop(0), ("127.0.0.1", 53873)


@unittest.skipIf(QApplication is None, "requires the overlay PySide6 environment")
class TestOverlayAnimation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        spec = importlib.util.spec_from_file_location("airoot_overlay", ASSETS / "airoot_overlay.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def setUp(self):
        self.clock = patch.object(self.module.time, "monotonic", return_value=10.0)
        self.now = self.clock.start()
        self.packets = Packets()
        self.overlay = self.module.AirootOverlay(self.packets)
        self.overlay.animation_timer.stop()
        self.overlay.commands_timer.stop()
        self.overlay.start_microphone = lambda: None
        self.overlay.show_listening()

    def tearDown(self):
        self.overlay.tray.hide()
        self.overlay.close()
        self.clock.stop()

    def tick(self, now):
        self.now.return_value = now
        self.overlay.advance()

    def run_for(self, start, seconds, peak, step=.05):
        """Feed a constant voice peak for a while; returns the end time."""
        self.overlay.audio_peak = peak
        for n in range(1, round(seconds / step) + 1):
            self.tick(start + n * step)
        return start + round(seconds / step) * step

    def grab(self):
        return self.overlay.grab().toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)

    def rendered(self, pixmap, scale=1.0):
        """The listening overlay drawn by hand showing pixmap at scale."""
        m = self.module
        image = QImage(self.overlay.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(0)
        p = QPainter(image)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        width, height = m.LOGO_WIDTH * scale, m.LOGO_HEIGHT * scale
        bounds = QRectF((self.overlay.width() - width) / 2, m.LOGO_TOP - (height - m.LOGO_HEIGHT) / 2, width, height)
        p.drawPixmap(bounds, pixmap, QRectF(pixmap.rect()))
        p.end()
        return image

    def test_processing_stays_compact_and_fades_on_completion(self):
        size, position = self.overlay.size(), self.overlay.pos()
        self.overlay.begin_transcribing()
        self.tick(10.4)
        self.assertEqual(self.overlay.mode, "transcribing")
        self.assertEqual(self.overlay.status, "Transcribing...")
        self.assertEqual(self.overlay.size(), size)
        self.assertEqual(self.overlay.pos(), position)
        self.overlay.finish_transcribing()
        self.tick(10.55)
        self.assertLess(self.overlay.windowOpacity(), 1)
        self.tick(10.7)
        self.assertEqual(self.overlay.mode, "hidden")
        self.assertFalse(self.overlay.isVisible())

    def test_fast_result_finishes_morph_before_fade(self):
        self.overlay.begin_transcribing()
        self.overlay.finish_transcribing()
        self.tick(10.2)
        self.assertEqual(self.overlay.mode, "gather")
        self.tick(10.4)
        self.assertEqual(self.overlay.mode, "dismiss")
        self.tick(10.7)
        self.assertEqual(self.overlay.mode, "hidden")

    def test_completion_does_not_display_transcript_and_session_resumes(self):
        self.overlay.begin_transcribing()
        self.packets.queue = [json.dumps({"event": "transcript", "text": "hello"}).encode(), b"show 2"]
        self.overlay.read_commands()
        self.assertEqual(self.overlay.pending, "show")
        self.assertFalse(hasattr(self.overlay, "transcript"))
        self.tick(10.4)
        self.tick(10.7)
        self.assertEqual(self.overlay.mode, "listening")
        self.assertEqual(self.overlay.device, 2)

    def test_duplicate_idle_does_not_restart_fade(self):
        self.overlay.begin_transcribing()
        self.tick(10.4)
        self.overlay.hide_listening()
        self.tick(10.55)
        self.overlay.hide_listening()
        self.tick(10.7)
        self.assertEqual(self.overlay.mode, "hidden")

    def test_new_recording_interrupts_unfinished_processing(self):
        self.overlay.begin_transcribing()
        self.overlay.show_listening()
        self.assertEqual(self.overlay.mode, "listening")
        self.assertEqual(self.overlay.windowOpacity(), 1)

    def test_recording_has_no_status_pill(self):
        image = self.overlay.grab().toImage()
        for y in range(140, image.height()):
            for x in range(image.width()):
                self.assertEqual(image.pixelColor(x, y).alpha(), 0)

    def test_silence_shows_static_logo_without_frames_or_repaints(self):
        m = self.module
        frame = self.overlay.frame_index
        with patch.object(self.overlay, "update") as update:
            end = self.run_for(10.0, 2.0, 0)
            # Room noise under TALK_ON is still silence: no dance, no growth.
            self.run_for(end, 1.0, .06)
        self.assertGreater(self.overlay.level, m.TALK_OFF)
        self.assertLess(self.overlay.level, m.TALK_ON)
        update.assert_not_called()
        self.assertFalse(self.overlay.talking)
        self.assertEqual(self.overlay.talk_mix, 0)
        self.assertEqual(self.overlay.frame_index, frame)
        self.assertIs(self.overlay.current_logo(), self.overlay.static_logo)
        self.assertEqual(self.overlay.logo_scale(), 1.0)
        self.assertEqual(self.grab(), self.rendered(self.overlay.static_logo))
        self.assertNotEqual(self.grab(), self.rendered(self.overlay.frames[frame]))

    def test_talking_dances_at_a_steady_pace(self):
        m = self.module
        # A soft voice, just over TALK_ON: dancing within the 0.15 s crossfade.
        end = self.run_for(10.0, .2, .12)
        self.assertTrue(self.overlay.talking)
        self.assertEqual(self.overlay.talk_mix, 1.0)
        self.assertIs(self.overlay.current_logo(), self.overlay.frames[self.overlay.frame_index])
        self.assertGreater(self.overlay.logo_scale(), 1.0)
        start, seen = self.overlay.dance_phase, {self.overlay.frame_index}
        with patch.object(self.overlay, "update") as update:
            for n in range(1, 21):
                self.tick(end + n * .05)
                seen.add(self.overlay.frame_index)
        self.assertEqual(update.call_count, 20)
        # One second of soft talk still runs at 60-100 % of full speed.
        advanced = self.overlay.dance_phase - start
        self.assertGreaterEqual(advanced, .6 * m.DANCE_SPEED)
        self.assertLessEqual(advanced, m.DANCE_SPEED)
        self.assertGreater(len(seen), 20)
        self.assertEqual(self.grab(), self.rendered(self.overlay.current_logo(), self.overlay.logo_scale()))

    def test_short_dip_under_talk_off_does_not_flicker(self):
        m = self.module
        end = self.run_for(10.0, .3, .8)
        self.assertEqual(self.overlay.talk_mix, 1.0)
        # A breath between words: the level drops under TALK_OFF, but for less
        # than QUIET_HOLD, so the dance neither stops nor fades.
        self.overlay.audio_peak = 0
        lowest, phase = 1.0, self.overlay.dance_phase
        for n in range(1, 11):
            self.tick(end + n * .05)
            lowest = min(lowest, self.overlay.level)
            self.assertTrue(self.overlay.talking)
            self.assertEqual(self.overlay.talk_mix, 1.0)
        self.assertLess(lowest, m.TALK_OFF)
        self.assertGreater(self.overlay.dance_phase, phase)
        end = self.run_for(end + .5, .3, .8)
        self.assertTrue(self.overlay.talking)
        self.assertIsNone(self.overlay.quiet_since)
        self.assertEqual(self.overlay.talk_mix, 1.0)

    def test_dance_follows_voice_and_settles_in_silence(self):
        m = self.module
        self.tick(10.1)
        self.assertEqual(self.overlay.frame_index, 0)
        self.assertIs(self.overlay.current_logo(), self.overlay.static_logo)
        self.overlay.audio_peak = .8
        self.tick(10.2)
        self.assertGreater(self.overlay.level, .6)
        self.assertGreater(self.overlay.frame_index, 0)
        # It keeps dancing until the level has stayed under TALK_OFF for
        # QUIET_HOLD, then crossfades back to the static logo.
        self.overlay.audio_peak = 0
        now, quiet_from = 10.2, None
        while self.overlay.talking:
            now += .05
            self.tick(now)
            if quiet_from is None and self.overlay.level < m.TALK_OFF:
                quiet_from = now
        self.assertGreaterEqual(now - quiet_from, m.QUIET_HOLD - 1e-9)
        self.assertGreater(self.overlay.talk_mix, 0)
        now = self.run_for(now, m.TALK_FADE + .05, 0)
        self.assertEqual(self.overlay.talk_mix, 0)
        self.assertIs(self.overlay.current_logo(), self.overlay.static_logo)
        frame = self.overlay.frame_index
        self.run_for(now, 2.0, 0)
        self.assertEqual(self.overlay.frame_index, frame)
        self.assertLess(self.overlay.level, .001)
        self.assertEqual(self.grab(), self.rendered(self.overlay.static_logo))

    def test_crossfade_blends_static_logo_into_the_dance(self):
        self.run_for(10.0, .1, .8)
        mix = self.overlay.logo_mix()
        self.assertGreater(mix, 0)
        self.assertLess(mix, 1)
        blend = self.overlay.current_logo()
        self.assertIsNot(blend, self.overlay.static_logo)
        self.assertIsNot(blend, self.overlay.frames[self.overlay.frame_index])
        self.assertEqual(blend.size(), self.overlay.static_logo.size())

    def test_morph_starts_at_identical_recording_frame(self):
        # Whatever is on screen: the static logo (a level alone never grows
        # it), the full dance, or the crossfade between the two.
        for peak, seconds in ((None, 0), (.8, .5), (.8, .1)):
            with self.subTest(peak=peak, seconds=seconds):
                self.overlay.show_listening()
                if peak is None:
                    self.overlay.level = .7
                else:
                    self.run_for(10.0, seconds, peak)
                before = self.overlay.grab().toImage()
                self.overlay.begin_transcribing()
                after = self.overlay.grab().toImage()
                self.assertEqual(before, after)
                # Back to a fresh recording for the next case.
                self.overlay.mode, self.overlay.completed = "hidden", False
                self.overlay.last_tick = 10.0

    def test_logo_asset_has_clear_corners_and_an_opaque_red_stroke(self):
        image = QImage(str(ASSETS / "airoot-logo.png"))
        self.assertFalse(image.isNull())
        self.assertTrue(image.hasAlphaChannel())
        self.assertEqual((image.width(), image.height()), (600, 417))
        for x, y in ((0, 0), (599, 0), (0, 416), (599, 416)):
            self.assertEqual(image.pixelColor(x, y).alpha(), 0)
        rgba = image.convertToFormat(QImage.Format_RGBA8888)
        data = bytes(rgba.constBits())[: rgba.sizeInBytes()]
        visible = {data[i:i + 3] for i in range(0, len(data), 4) if data[i + 3]}
        # One colour wherever it shows: no gray fringe left from the checkerboard.
        self.assertEqual(len(visible), 1)
        red, green, blue = next(iter(visible))
        self.assertGreater(red, 200)
        self.assertLess(green, 40)
        self.assertLess(blue, 80)
        self.assertGreater(data[3::4].count(255), 5000)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(self.module.self_test(), 0)
        self.assertIn("static logo 600x417 with transparency", out.getvalue())


if __name__ == "__main__":
    unittest.main()
