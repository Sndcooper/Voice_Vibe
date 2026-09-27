"""Run with the overlay's PySide6 environment to validate Qt transitions."""
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None


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
        spec = importlib.util.spec_from_file_location(
            "airoot_overlay", Path(__file__).resolve().parents[1] / "assets/airoot_overlay.py"
        )
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

    def test_dance_follows_voice_and_settles_in_silence(self):
        self.tick(10.1)
        self.assertEqual(self.overlay.frame_index, 0)
        self.overlay.audio_peak = .8
        self.tick(10.2)
        self.assertGreater(self.overlay.level, .6)
        self.assertGreater(self.overlay.frame_index, 0)
        self.overlay.audio_peak = 0
        for n in range(20):
            self.tick(10.3 + n * .1)
        frame = self.overlay.frame_index
        self.tick(12.4)
        self.assertEqual(self.overlay.frame_index, frame)
        self.assertLess(self.overlay.level, .001)

    def test_morph_starts_at_identical_recording_frame(self):
        self.overlay.level = .7
        before = self.overlay.grab().toImage()
        self.overlay.begin_transcribing()
        after = self.overlay.grab().toImage()
        self.assertEqual(before, after)
