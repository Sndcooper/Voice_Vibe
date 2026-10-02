"""WS0 follow-ups F1-F7: what the other streams asked the link and hub for.

Desktop, microphone, models, network and real data are all faked; the hub
data folder is a temp dir (VVHUB_HOME).
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

import stubs

stubs.install()

from voicevibe import app  # noqa: E402
from voicevibe.actions import ActionError  # noqa: E402
from voicevibe.confirm import VoiceConfirmer  # noqa: E402
from voicevibe.hub_client import HubClient  # noqa: E402
from vvhub import protocol  # noqa: E402

try:
    import uvicorn
    from fastapi.testclient import TestClient

    from vvhub import __main__ as cli
    from vvhub.server import Hub, create_app
    from vvhub.skills import reports
    from vvhub.store import Store
except ImportError:
    TestClient = None


def _wait(predicate, timeout: float = 5.0) -> bool:  # noqa: ANN001
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class _TempHome(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        old = os.environ.get("VVHUB_HOME")
        os.environ["VVHUB_HOME"] = tmp.name
        self.addCleanup(lambda: os.environ.__setitem__("VVHUB_HOME", old) if old
                        else os.environ.pop("VVHUB_HOME", None))


class ConfirmTests(unittest.TestCase):
    """F1: approvals need 'nobody can hear' and the words that were heard."""

    def test_confirmer_keeps_the_heard_answer(self) -> None:
        confirmer = VoiceConfirmer(transcribe=lambda audio: "Yes.", yes_words=("yes",),
                                   no_words=("no",))
        result = {}
        worker = threading.Thread(target=lambda: result.update(v=confirmer("Post it", 3.0)))
        worker.start()
        self.assertTrue(_wait(lambda: confirmer.pending))
        confirmer.offer(b"audio")
        worker.join(3)
        self.assertIs(result["v"], True)
        self.assertEqual(confirmer.last_answer, "Yes.")

    def test_link_passes_answer_and_unavailable(self) -> None:
        client = HubClient({"confirm": lambda p, t: {"approved": True, "answer": "yes do it"}})
        reply = client._handle(protocol.message("confirm", prompt="?", timeout=2))
        self.assertEqual((reply["approved"], reply["answer"]), (True, "yes do it"))
        self.assertNotIn("unavailable", reply)

        client = HubClient({"confirm": lambda p, t: {"approved": False, "unavailable": True}})
        reply = client._handle(protocol.message("confirm", prompt="?"))
        self.assertEqual((reply["approved"], reply["unavailable"]), (False, True))

        # Old-style boolean handlers still work, but carry no answer text.
        reply = HubClient({"confirm": lambda p, t: True})._handle(protocol.message("confirm"))
        self.assertEqual((reply["approved"], reply["answer"]), (True, ""))

    def _vv(self, recording: bool, verdict: bool = True):  # noqa: ANN202
        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.session = SimpleNamespace(is_recording=recording)
        confirmer = Mock(return_value=verdict)
        confirmer.last_answer = "yes" if verdict else "no"
        vv.confirmer = confirmer
        return vv

    def test_no_open_session_is_unavailable_not_denied(self) -> None:
        vv = self._vv(recording=False)
        self.assertEqual(vv._hub_confirm("Post it?", 15),
                         {"approved": False, "answer": "", "unavailable": True})
        vv.confirmer.assert_not_called()

    def test_open_session_asks_and_reports_the_words(self) -> None:
        vv = self._vv(recording=True)
        self.assertEqual(vv._hub_confirm("Post it?", 15), {"approved": True, "answer": "yes"})
        vv.confirmer.assert_called_once_with("Post it?", 15)


class ContextPinTests(unittest.TestCase):
    """F2: the hub's focus / unfocus must reach the pin."""

    def test_pin_is_forwarded(self) -> None:
        seen = []
        client = HubClient({"get_context": lambda deep, pin=None: seen.append((deep, pin)) or {}})
        client._handle(protocol.message("get_context", deep=True, pin=True))
        client._handle(protocol.message("get_context", pin=False))
        client._handle(protocol.message("get_context"))
        self.assertEqual(seen, [(True, True), (False, False), (False, None)])


class MicTests(unittest.TestCase):
    """F3: list and switch microphones for the hub, never onto a loopback."""

    NAMES = [(1, "Stereo Mix (Realtek(R) Audio)"), (2, "Microphone Array (Realtek(R) Audio)"),
             (3, "Microphone (Realtek(R) Audio)")]

    def _vv(self, recording: bool = False):  # noqa: ANN202
        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.config = SimpleNamespace(audio={})
        vv.session = SimpleNamespace(is_recording=recording, device=None)
        vv.recorder = SimpleNamespace(is_recording=False, device=None)
        vv.airoot = Mock()
        vv._mic = 2
        vv._mic_names = lambda: list(self.NAMES)
        return vv

    def test_list(self) -> None:
        vv = self._vv()
        with patch.object(app, "refresh_devices") as refresh, \
                patch.object(app, "device_label", return_value="[2] Microphone Array (Realtek(R) Audio)"):
            mics = vv._list_mics()
        refresh.assert_called_once()
        self.assertEqual(mics["current"], "Microphone Array (Realtek(R) Audio)")
        self.assertEqual(len(mics["devices"]), 3)

    def test_no_refresh_under_an_open_stream(self) -> None:
        vv = self._vv(recording=True)
        with patch.object(app, "refresh_devices") as refresh, \
                patch.object(app, "device_label", return_value="[2] X"):
            vv._list_mics()
        refresh.assert_not_called()

    def test_set_exact_name_pins_for_this_run(self) -> None:
        vv = self._vv()
        with patch.object(app, "device_label", return_value="[3] Microphone"):
            vv._set_mic("microphone (realtek(r) audio)")
        self.assertEqual(vv.config.audio["input_device"], 3)
        self.assertEqual((vv._mic, vv.recorder.device, vv.session.device), (3, 3, 3))
        vv.airoot.set_device.assert_called_once_with(3)

    def test_set_refuses_loopback_and_unknown(self) -> None:
        vv = self._vv()
        with self.assertRaises(ValueError):
            vv._set_mic("stereo mix")
        with self.assertRaises(LookupError):
            vv._set_mic("bluetooth headset")
        with self.assertRaises(LookupError):
            vv._set_mic("")
        self.assertNotIn("input_device", vv.config.audio)


class VoiceNoteTests(unittest.TestCase):
    """F4: Telegram voice notes go through the already-loaded Whisper."""

    def test_decode_and_transcribe(self) -> None:
        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.config = SimpleNamespace(audio={"sample_rate": 16000})
        vv.transcriber = object()
        vv._transcribe_job = Mock(return_value="  send the report  ")
        audio = np.zeros(16000, dtype=np.float32)
        with patch("faster_whisper.audio.decode_audio", return_value=audio) as decode:
            self.assertEqual(vv._transcribe_note(b"OggS...", "ogg"), "send the report")
        self.assertEqual(decode.call_args.kwargs["sampling_rate"], 16000)
        vv._transcribe_job.assert_called_once_with(audio, app.INSERT, armed=False)

    def test_model_not_loaded(self) -> None:
        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.transcriber = None
        with self.assertRaises(RuntimeError):
            vv._transcribe_note(b"x")

    def test_link_decodes_base64(self) -> None:
        import base64

        got = []
        client = HubClient({"transcribe": lambda data, fmt: got.append((data, fmt)) or "hi"})
        reply = client._handle(protocol.message(
            "transcribe", audio_b64=base64.b64encode(b"\x01\x02").decode(), format="ogg"))
        self.assertEqual((reply["type"], reply["text"]), ("text", "hi"))
        self.assertEqual(got, [(b"\x01\x02", "ogg")])


class StepsTests(unittest.TestCase):
    """run_steps goes through the app's executor; a dry run only validates."""

    def _vv(self):  # noqa: ANN202
        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.executor = Mock()
        return vv

    def test_dry_run_validates_without_running(self) -> None:
        vv = self._vv()
        vv._hub_steps([{"keys": "ctrl+s"}], True)
        vv.executor.run.assert_not_called()
        with self.assertRaises(ActionError):
            vv._hub_steps([{"keys": "ctrl+notakey"}], True)

    def test_real_run_uses_the_executor(self) -> None:
        vv = self._vv()
        vv._hub_steps([{"keys": "ctrl+s"}], False)
        vv.executor.run.assert_called_once_with([{"keys": "ctrl+s"}], command="hub")


class SpokenOnArmTests(unittest.TestCase):
    """F6: the report summary is said once, on the next arm."""

    def test_app_speaks_the_reply(self) -> None:
        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.history, vv.overlay, vv.voice = Mock(), Mock(), Mock()
        vv._say_hub_reply({"text": "Two new pull requests.", "speak": True})
        vv.voice.say.assert_called_once_with("Two new pull requests.")
        vv._say_hub_reply({"text": ""})
        self.assertEqual(vv.voice.say.call_count, 1)


@unittest.skipIf(TestClient is None, "hub dependencies not installed")
class HubWiringTests(_TempHome):
    def hello(self, ws) -> None:  # noqa: ANN001
        ws.send_text(protocol.encode(protocol.message("hello", token="tok", role="voicevibe")))
        self.assertEqual(protocol.decode(ws.receive_text())["type"], "welcome")

    def test_armed_hands_out_the_summary_once(self) -> None:
        reports.save_spoken(reports.reports_dir(), "Two new pull requests.")
        with TestClient(create_app(Hub(token="tok", store=Store()))) as client, \
                client.websocket_connect("/ws") as ws:
            self.hello(ws)
            ws.send_text(protocol.encode(protocol.message("armed")))
            first = protocol.decode(ws.receive_text())
            ws.send_text(protocol.encode(protocol.message("armed")))
            second = protocol.decode(ws.receive_text())
        self.assertEqual((first["text"], first["speak"]), ("Two new pull requests.", True))
        self.assertEqual((second["text"], second["handled"]), ("", False))

    def test_scheduler_runs_with_the_hub(self) -> None:
        fake = Mock()
        hub = Hub(token="tok", store=Store(), scheduler_factory=Mock(return_value=fake))
        with TestClient(create_app(hub)):
            fake.start.assert_called_once()
            fake.shutdown.assert_not_called()
        fake.shutdown.assert_called_once()

    def test_broken_scheduler_does_not_stop_the_hub(self) -> None:
        hub = Hub(token="tok", store=Store(),
                  scheduler_factory=Mock(side_effect=RuntimeError("no apscheduler")))
        with TestClient(create_app(hub)) as client:
            ok = client.get("/health", headers={"Authorization": "Bearer tok"})
        self.assertEqual(ok.status_code, 200)

    def test_cli_forwards_report_and_eval(self) -> None:
        with patch("vvhub.scheduler.main", return_value=0) as report:
            self.assertEqual(cli.main(["report", "--now", "--no-poll"]), 0)
        report.assert_called_once_with(["report", "--now", "--no-poll"])
        with patch("vvhub.evals.runner.main", return_value=0) as evals:
            self.assertEqual(cli.main(["eval", "--tier", "keywords"]), 0)
        evals.assert_called_once_with(["--tier", "keywords"])

    def test_file_log(self) -> None:
        path = cli.attach_file_log()
        root = logging.getLogger()
        handler = root.handlers[-1]
        self.addCleanup(root.removeHandler, handler)
        self.addCleanup(handler.close)
        logging.getLogger("vvhub.test").warning("hello log")
        handler.flush()
        self.assertEqual(path.parent.name, "logs")
        self.assertIn("hello log", path.read_text(encoding="utf-8"))


@unittest.skipIf(TestClient is None, "hub dependencies not installed")
class LiveArmTests(_TempHome):
    """The real link: arm -> hub -> summary -> callback on a worker thread."""

    def test_armed_round_trip(self) -> None:
        import socket

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(
            create_app(Hub(token="k", store=Store())), host="127.0.0.1", port=port,
            log_level="error", lifespan="on"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        self.assertTrue(_wait(lambda: server.started, 10))
        self.addCleanup(thread.join, 5)
        self.addCleanup(setattr, server, "should_exit", True)

        client = HubClient(url=f"ws://127.0.0.1:{port}/ws", token=lambda: "k").start()
        self.addCleanup(client.stop)
        self.assertTrue(_wait(lambda: client.connected))
        reports.save_spoken(reports.reports_dir(), "Nothing new today.")
        heard = []
        client.armed(heard.append)
        self.assertTrue(_wait(lambda: heard))
        self.assertEqual(heard[0]["text"], "Nothing new today.")


if __name__ == "__main__":
    unittest.main()
