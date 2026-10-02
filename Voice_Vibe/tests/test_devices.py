"""Input-device selection.

A loopback device (Realtek's "Stereo Mix") records what the speakers play, not
what is said. When Windows has one as the default input, every recording is
silence that looks exactly like a broken microphone -- which is what happened
in practice, so these tests pin the fallback behaviour down.
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def fake_sounddevice(devices: list[tuple[str, int]], default: int | None):
    """Stand in for the sounddevice module. `devices` is (name, in_channels)."""
    module = types.ModuleType("sounddevice")
    entries = [{"name": name, "max_input_channels": channels} for name, channels in devices]

    def query_devices(index=None):  # noqa: ANN001
        return entries if index is None else entries[index]

    module.query_devices = query_devices
    module.default = types.SimpleNamespace(device=(default, None))
    module.InputStream = object
    return module


class DeviceSelectionTest(unittest.TestCase):
    def resolve(self, devices, default, priority=None):  # noqa: ANN001
        sys.modules["sounddevice"] = fake_sounddevice(devices, default)
        for name in [n for n in sys.modules if n.startswith("voicevibe.")]:
            del sys.modules[name]
        from voicevibe.audio import default_input_device

        return default_input_device(priority)

    def tearDown(self) -> None:
        sys.modules.pop("sounddevice", None)
        for name in [n for n in sys.modules if n.startswith("voicevibe.")]:
            del sys.modules[name]

    def test_a_normal_default_is_left_alone(self) -> None:
        # None means "let PortAudio use the system default".
        chosen = self.resolve([("Microphone Array", 2), ("Stereo Mix", 2)], default=0)
        self.assertIsNone(chosen)

    def test_loopback_default_falls_back_to_a_real_microphone(self) -> None:
        chosen = self.resolve([("Stereo Mix (Realtek)", 2), ("Microphone Array", 2)], default=0)
        self.assertEqual(chosen, 1)

    def test_alias_devices_are_never_chosen(self) -> None:
        # Sound Mapper forwards to the Windows default, which is the loopback we
        # are trying to escape, so picking it would change nothing.
        chosen = self.resolve(
            [
                ("Microsoft Sound Mapper - Input", 2),
                ("Stereo Mix (Realtek)", 2),
                ("Primary Sound Capture Driver", 2),
                ("Microphone Array (Realtek)", 2),
            ],
            default=1,
        )
        self.assertEqual(chosen, 3)

    def test_microphones_are_preferred_over_unnamed_inputs(self) -> None:
        chosen = self.resolve(
            [("Stereo Mix", 2), ("Line In", 2), ("Headset Microphone", 2)], default=0
        )
        self.assertEqual(chosen, 2)

    def test_output_only_devices_are_ignored(self) -> None:
        chosen = self.resolve(
            [("Stereo Mix", 2), ("Speakers", 0), ("Microphone Array", 2)], default=0
        )
        self.assertEqual(chosen, 2)

    def test_all_loopback_gives_up_rather_than_guessing(self) -> None:
        chosen = self.resolve([("Stereo Mix", 2), ("What U Hear", 2)], default=0)
        self.assertIsNone(chosen)

    def test_no_input_devices_at_all(self) -> None:
        self.assertIsNone(self.resolve([("Speakers", 0)], default=None))

    def test_preferred_realtek_microphone_beats_array_and_stereo_mix(self) -> None:
        chosen = self.resolve(
            [("Stereo Mix (Realtek(R) Audio)", 2),
             ("Microphone Array (Realtek(R) Audio)", 2),
             ("Microphone (Realtek(R) Audio)", 2)], default=0,
            priority=["Microphone (Realtek(R) Audio)", "Stereo Mix"],
        )
        self.assertEqual(chosen, 2)

    def test_a_real_default_beats_even_an_explicit_stereo_mix(self) -> None:
        # Was the opposite until 2026-09-29: an explicit "Stereo Mix" entry
        # won over a real default mic, and dictation recorded silence. The
        # Windows default now wins whenever it is a real microphone.
        chosen = self.resolve(
            [("Microphone Array", 2), ("Stereo Mix (Realtek(R) Audio)", 2)],
            default=0, priority=["Microphone (Realtek(R) Audio)", "Stereo Mix"],
        )
        self.assertIsNone(chosen)

    def test_explicit_stereo_mix_is_still_honoured_when_the_default_is_a_loopback(self) -> None:
        with self.assertLogs("voicevibe.audio", level="WARNING"):
            chosen = self.resolve(
                [("Microphone Array", 2), ("Stereo Mix (Realtek(R) Audio)", 2)],
                default=1, priority=["Microphone (Realtek(R) Audio)", "Stereo Mix"],
            )
        self.assertEqual(chosen, 1)

    def test_a_preferred_loopback_is_warned_about(self) -> None:
        # Honoured because it was named -- but it records the speakers, which
        # is exactly how dictation ended up typing "Thank you." for silence.
        with self.assertLogs("voicevibe.audio", level="WARNING") as logs:
            self.resolve([("Stereo Mix (Realtek(R) Audio)", 2)], default=0,
                         priority=["Stereo Mix"])
        self.assertIn("loopback", logs.output[0])

    def test_a_real_windows_default_beats_the_priority_list(self) -> None:
        # Choosing a mic in Windows' sound settings is what gets recorded.
        chosen = self.resolve(
            [("Microphone Array (Realtek(R) Au", 2), ("Headset Microphone", 2)], default=1,
            priority=["Microphone Array"],
        )
        self.assertIsNone(chosen)  # None = PortAudio's default, i.e. Windows'

    def test_built_in_array_is_the_fallback_when_no_jack_mic(self) -> None:
        # The shipped config: MME truncates names to 31 characters, so the
        # array is matched as a substring.
        chosen = self.resolve(
            [("Microsoft Sound Mapper - Input", 2), ("Stereo Mix (Realtek(R) Audio)", 2),
             ("Microphone Array (Realtek(R) Au", 2)], default=1,
            priority=["Microphone (Realtek(R) Audio)", "Microphone Array"],
        )
        self.assertEqual(chosen, 2)


class RefreshTest(unittest.TestCase):
    """PortAudio only sees new devices / a new Windows default after a re-init."""

    def load(self, playing: bool | None):  # noqa: ANN201
        module = fake_sounddevice([("Microphone Array", 2)], 0)
        module.calls = []
        module._terminate = lambda: module.calls.append("terminate")
        module._initialize = lambda: module.calls.append("initialize")

        def get_stream():  # noqa: ANN202
            if playing is None:
                raise RuntimeError("play()/rec()/playrec() was not called yet")
            return types.SimpleNamespace(active=playing)

        module.get_stream = get_stream
        sys.modules["sounddevice"] = module
        for name in [n for n in sys.modules if n.startswith("voicevibe.")]:
            del sys.modules[name]
        from voicevibe.audio import refresh_devices

        return module, refresh_devices

    def tearDown(self) -> None:
        sys.modules.pop("sounddevice", None)
        for name in [n for n in sys.modules if n.startswith("voicevibe.")]:
            del sys.modules[name]

    def test_reinitialises(self) -> None:
        for playing in (None, False):
            with self.subTest(playing=playing):
                module, refresh = self.load(playing)
                self.assertTrue(refresh())
                self.assertEqual(module.calls, ["terminate", "initialize"])

    def test_never_cuts_off_speech_that_is_playing(self) -> None:
        module, refresh = self.load(True)
        self.assertFalse(refresh())
        self.assertEqual(module.calls, [])


class FollowMicrophoneTest(unittest.TestCase):
    """The app re-chooses before each recording and tells every part of itself."""

    def make(self, pinned: bool = False):  # noqa: ANN201
        sys.modules["sounddevice"] = fake_sounddevice([("Microphone Array", 2)], 0)
        for name in [n for n in sys.modules if n.startswith("voicevibe.")]:
            del sys.modules[name]
        try:
            from voicevibe import app
        except Exception:  # pragma: no cover - numpy / pillow missing
            self.skipTest("app.py needs numpy and pillow")
        choices = iter([3, 3, 7])
        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.config = types.SimpleNamespace(input_device_pinned=pinned,
                                          refresh_input_device=lambda: next(choices))
        vv._mic = 3
        vv.recorder = types.SimpleNamespace(device=3)
        vv.session = types.SimpleNamespace(device=3)
        vv.overlay_devices = []
        vv.airoot = types.SimpleNamespace(set_device=vv.overlay_devices.append)
        return vv

    def tearDown(self) -> None:
        sys.modules.pop("sounddevice", None)
        for name in [n for n in sys.modules if n.startswith("voicevibe.")]:
            del sys.modules[name]

    def test_a_new_microphone_reaches_recorders_and_overlay(self) -> None:
        vv = self.make()
        vv._choose_microphone()  # still 3: nothing to do
        self.assertEqual(vv.overlay_devices, [])
        vv._choose_microphone()  # 3 again
        vv._choose_microphone()  # Windows now says 7
        self.assertEqual((vv.recorder.device, vv.session.device, vv._mic), (7, 7, 7))
        self.assertEqual(vv.overlay_devices, [7])

    def test_a_pinned_device_is_never_changed(self) -> None:
        vv = self.make(pinned=True)
        vv._choose_microphone()
        self.assertEqual(vv.recorder.device, 3)


class LoopbackNamingTest(unittest.TestCase):
    def setUp(self) -> None:
        sys.modules["sounddevice"] = fake_sounddevice([], None)
        from voicevibe.audio import is_loopback

        self.is_loopback = is_loopback

    def tearDown(self) -> None:
        sys.modules.pop("sounddevice", None)
        for name in [n for n in sys.modules if n.startswith("voicevibe.")]:
            del sys.modules[name]

    def test_known_loopback_names(self) -> None:
        for name in (
            "Stereo Mix (Realtek(R) Audio)",
            "What U Hear",
            "Wave Out Mix",
            "PC Speaker (Realtek HD Audio output)",
            "CABLE Output (VB-Audio Loopback)",
        ):
            with self.subTest(name=name):
                self.assertTrue(self.is_loopback(name))

    def test_real_microphones_are_not_flagged(self) -> None:
        for name in (
            "Microphone Array (Realtek(R) Audio)",
            "Headset Microphone",
            "Blue Yeti",
            "Line In",
        ):
            with self.subTest(name=name):
                self.assertFalse(self.is_loopback(name))


if __name__ == "__main__":
    unittest.main()
