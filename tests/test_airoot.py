"""The Airoot bridge: what it sends, and when.

A real UDP socket stands in for the overlay. Because something already owns the
port, the bridge treats the overlay as running and never tries to launch it.
"""

from __future__ import annotations

import socket
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voicevibe.airoot import AirootBridge  # noqa: E402


class FakeOverlay:
    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]

    def received(self) -> list[str]:
        out = []
        while True:
            try:
                data, _ = self.sock.recvfrom(256)
            except (socket.timeout, OSError):
                return out
            out.append(data.decode("ascii"))

    def close(self) -> None:
        self.sock.close()


@unittest.skipUnless(sys.platform == "win32", "the bridge is Windows-only")
class TestBridge(unittest.TestCase):
    def setUp(self) -> None:
        self.overlay = FakeOverlay()
        handle = tempfile.NamedTemporaryFile(suffix=".exe", delete=False)
        handle.close()
        self.exe = Path(handle.name)
        self.bridge = AirootBridge(
            {"enabled": True, "exe": str(self.exe), "port": self.overlay.port}
        )

    def tearDown(self) -> None:
        self.overlay.close()
        self.exe.unlink(missing_ok=True)

    def test_show_carries_the_chosen_input_device(self) -> None:
        # The overlay meters its own stream; without this it would use the
        # Windows default, which is the loopback we deliberately avoided.
        self.bridge.set_device(2)
        self.bridge.set_listening(True)
        self.assertEqual(self.overlay.received(), ["show 2"])

    def test_show_stays_bare_when_the_system_default_is_fine(self) -> None:
        self.bridge.set_device(None)
        self.bridge.set_listening(True)
        self.assertEqual(self.overlay.received(), ["show"])

    def test_a_device_name_is_not_sent_as_a_number(self) -> None:
        self.bridge.set_device("Microphone Array")
        self.bridge.set_listening(True)
        self.assertEqual(self.overlay.received(), ["show"])

    def test_show_and_hide_send_one_packet_each(self) -> None:
        self.bridge.set_listening(True)
        self.bridge.set_listening(False)
        self.assertEqual(self.overlay.received(), ["show", "hide"])

    def test_repeated_state_is_not_resent(self) -> None:
        # A dictating session re-indicates its state on every utterance.
        for _ in range(5):
            self.bridge.set_listening(True)
        self.assertEqual(self.overlay.received(), ["show"])

    def test_initial_idle_sends_nothing(self) -> None:
        self.bridge.set_listening(False)
        self.assertEqual(self.overlay.received(), [])

    def test_running_overlay_is_not_relaunched(self) -> None:
        self.bridge.start()
        self.bridge.set_listening(True)
        self.assertFalse(self.bridge._owns_process)  # noqa: SLF001

    def test_stop_hides_but_leaves_a_foreign_overlay_running(self) -> None:
        # The fake was running before us, so we must not tell it to quit.
        self.bridge.set_listening(True)
        self.overlay.received()
        self.bridge.stop()
        self.assertEqual(self.overlay.received(), ["hide"])

    def test_stop_quits_an_overlay_we_started(self) -> None:
        self.bridge._owns_process = True  # noqa: SLF001
        self.bridge.stop()
        self.assertEqual(self.overlay.received(), ["hide", "quit"])


class TestDisabled(unittest.TestCase):
    def test_missing_exe_disables_the_bridge(self) -> None:
        bridge = AirootBridge({"enabled": True, "exe": "C:/does/not/exist.exe"})
        self.assertFalse(bridge.enabled)
        bridge.set_listening(True)  # must be a harmless no-op
        bridge.stop()

    def test_off_by_default(self) -> None:
        self.assertFalse(AirootBridge({}).enabled)


if __name__ == "__main__":
    unittest.main()
