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
    def resolve(self, devices, default):  # noqa: ANN001
        sys.modules["sounddevice"] = fake_sounddevice(devices, default)
        for name in [n for n in sys.modules if n.startswith("voicevibe.")]:
            del sys.modules[name]
        from voicevibe.audio import default_input_device

        return default_input_device()

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
