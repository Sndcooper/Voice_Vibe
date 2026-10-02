"""vvhub.skills.app: windows and microphones, through Voice Vibe.

Fake bus and a fake window list; nothing is focused or switched for real.
"""

from __future__ import annotations

import asyncio
import unittest

import stubs

stubs.install()

from vvhub import smart_router  # noqa: E402
from vvhub.schemas import Decision  # noqa: E402
from vvhub.skills.app import AppSkill  # noqa: E402


def run(coro):  # noqa: ANN001, ANN201
    return asyncio.run(coro)


WINDOWS = [
    {"hwnd": 101, "title": "Spotify Premium", "process_name": "Spotify.exe", "z": 0},
    {"hwnd": 202, "title": "main.py - uBipedal - Visual Studio Code", "process_name": "Code.exe",
     "z": 1},
    {"hwnd": 303, "title": "Claude", "process_name": "claude.exe", "z": 2},
]
MICS = {"devices": ["Microphone Array (Realtek(R) Audio)", "Stereo Mix (Realtek(R) Audio)",
                    "Microphone (Realtek(R) Audio)"],
        "current": "Microphone Array (Realtek(R) Audio)"}


class FakeBus:
    def __init__(self, up: bool = True, replies: dict | None = None) -> None:
        self.up = up
        self.sent: list[dict] = []
        self.replies = replies or {}

    def connected(self, role: str) -> bool:
        return self.up and role == "voicevibe"

    async def send_to(self, role: str, msg: dict, timeout=None) -> dict:  # noqa: ANN001
        self.sent.append(msg)
        reply = self.replies.get(msg["type"], {"type": "ok"})
        return dict(reply, re=msg["id"])


class FakeHub:
    def __init__(self, bus: FakeBus) -> None:
        self.bus = bus
        self.skills = {}


def skill(bus: FakeBus | None = None) -> AppSkill:
    s = AppSkill(windows=lambda: list(WINDOWS))
    s.bind(FakeHub(bus or FakeBus()))
    return s


class FocusTests(unittest.TestCase):
    def test_actions_and_nothing_critical(self) -> None:
        s = skill()
        self.assertEqual(s.category, "app")
        self.assertEqual(set(s.actions), {"focus_window", "list_mics", "set_mic"})
        self.assertFalse(s.critical_actions)

    def test_target_options_are_live_windows(self) -> None:
        s = skill()
        options = s.target_options(Decision(action="focus_window"), {})
        self.assertIn("Spotify Premium", options)
        self.assertIn("Code.exe", options["main.py - uBipedal - Visual Studio Code"])
        self.assertEqual(s.target_options(Decision(action="list_mics"), {}), {})

    def test_named_window_is_picked_by_the_router(self) -> None:
        options = skill().target_options(Decision(action="focus_window"), {})
        self.assertEqual(smart_router.named_option("go to my vs code window", options),
                         "main.py - uBipedal - Visual Studio Code")
        self.assertEqual(smart_router.named_option("switch to spotify", options),
                         "Spotify Premium")

    def test_focus_runs_a_focus_step_in_voice_vibe(self) -> None:
        bus = FakeBus(replies={"run_steps": {"type": "steps_result", "ok": True}})
        s = skill(bus)
        plan = run(s.plan(Decision(category="app", action="focus_window",
                                   target="Spotify Premium"), {}))
        self.assertEqual(plan.args["hwnd"], 101)
        self.assertIn("Spotify Premium", plan.preview)
        result = run(s.run(plan))
        self.assertTrue(result.ok)
        sent = bus.sent[-1]
        self.assertEqual(sent["type"], "run_steps")
        self.assertEqual(sent["steps"], [{"focus": {"hwnd": 101, "title": "Spotify Premium"}}])
        self.assertFalse(sent["dry_run"])

    def test_spoken_name_falls_back_to_window_matching(self) -> None:
        plan = run(skill().plan(Decision(action="focus_window", target="claude"), {}))
        self.assertEqual(plan.args["hwnd"], 303)

    def test_unknown_window_says_so(self) -> None:
        s = skill()
        plan = run(s.plan(Decision(action="focus_window", target="photoshop"), {}))
        result = run(s.run(plan))
        self.assertFalse(result.ok)
        self.assertIn("photoshop", result.text.lower())

    def test_dry_run_sends_nothing(self) -> None:
        bus = FakeBus()
        s = skill(bus)
        plan = run(s.plan(Decision(action="focus_window", target="Claude"), {}))
        self.assertTrue(run(s.run(plan, dry_run=True)).ok)
        self.assertEqual(bus.sent, [])

    def test_voice_vibe_offline(self) -> None:
        s = skill(FakeBus(up=False))
        plan = run(s.plan(Decision(action="focus_window", target="Claude"), {}))
        result = run(s.run(plan))
        self.assertFalse(result.ok)
        self.assertIn("Voice Vibe", result.text)


class MicTests(unittest.TestCase):
    def test_list_mics_hides_loopbacks(self) -> None:
        s = skill(FakeBus(replies={"list_mics": dict(MICS, type="mics")}))
        result = run(s.run(run(s.plan(Decision(action="list_mics"), {}))))
        self.assertTrue(result.ok)
        self.assertIn("Microphone Array", result.text)
        self.assertNotIn("Stereo Mix", result.text)

    def test_set_mic_by_spoken_name(self) -> None:
        bus = FakeBus(replies={"list_mics": dict(MICS, type="mics"), "set_mic": {"type": "ok"}})
        s = skill(bus)
        plan = run(s.plan(Decision(action="set_mic", target="the microphone array"), {}))
        self.assertEqual(plan.args["device"], "Microphone Array (Realtek(R) Audio)")
        self.assertTrue(run(s.run(plan)).ok)
        self.assertEqual(bus.sent[-1]["type"], "set_mic")
        self.assertEqual(bus.sent[-1]["device"], "Microphone Array (Realtek(R) Audio)")

    def test_never_sets_stereo_mix(self) -> None:
        bus = FakeBus(replies={"list_mics": dict(MICS, type="mics")})
        s = skill(bus)
        plan = run(s.plan(Decision(action="set_mic", target="stereo mix"), {}))
        result = run(s.run(plan))
        self.assertFalse(result.ok)
        self.assertNotIn("set_mic", [m["type"] for m in bus.sent])


if __name__ == "__main__":
    unittest.main()
