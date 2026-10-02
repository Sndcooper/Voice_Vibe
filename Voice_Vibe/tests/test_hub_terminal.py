"""Hub fixes from the 2026-09-30 18:51 log: routing, guesses, pythonw, warm-up."""

from __future__ import annotations

import asyncio
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import stubs

stubs.install()

from vvhub import dispatch  # noqa: E402
from vvhub.bus import Bus  # noqa: E402
from vvhub.schemas import Decision, Plan, Result  # noqa: E402
from vvhub.skills.base import Skill  # noqa: E402
from vvhub.store import Store  # noqa: E402


class FakeTerminal(Skill):
    name = "terminal"
    category = "code"
    actions = {"shell_command": "run a command"}

    def __init__(self, command: str = "dir") -> None:
        super().__init__()
        self.command, self.seen, self.ran = command, None, False

    async def plan(self, decision, context):  # noqa: ANN001
        self.seen = context
        return Plan(skill=self.name, action="shell_command",
                    args={"command": self.command, "noop": not self.command})

    async def run(self, plan, approval=None, dry_run=False):  # noqa: ANN001
        self.ran = True
        if not self.command:
            return Result(ok=False, data={"handled": False})
        return Result(ok=True, text=self.command)


class FakeOther(Skill):
    name = "screen"
    category = "screen"
    actions = {"explain": "explain the screen"}

    async def run(self, plan, approval=None, dry_run=False):  # noqa: ANN001
        return Result(ok=True, text="explained")


def hub(*skills: Skill):  # noqa: ANN201
    h = SimpleNamespace(store=Store(), bus=Bus(), skills={s.name: s for s in skills})
    for s in skills:
        s.bind(h)
    return h


def modules(router=None, policy=None, approvals=None):  # noqa: ANN001, ANN201
    table = {"smart_router": router, "policy": policy, "approvals": approvals}
    return lambda name: table.get(name)


class DispatchTests(unittest.TestCase):
    def test_plain_shell_goes_to_the_terminal_skill(self) -> None:
        term = FakeTerminal()
        with patch.object(dispatch, "_optional", modules()):
            result = asyncio.run(dispatch.handle(
                hub(term, FakeOther()), "list the files", {"terminal": {"shell": "cmd"}}))
        self.assertEqual(result.text, "dir")
        self.assertEqual(term.seen["request"], "list the files")

    def test_ai_cli_terminal_is_not_a_shell(self) -> None:
        term = FakeTerminal()
        with patch.object(dispatch, "_optional", modules()):
            result = asyncio.run(dispatch.handle(
                hub(term), "fix the bug", {"terminal": {"shell": "cmd", "ai": "claude"}}))
        self.assertFalse(result.data.get("handled", True))
        self.assertIsNone(term.seen)

    def test_nothing_found_is_not_asked_about(self) -> None:
        term = FakeTerminal(command="")
        always = SimpleNamespace(needs_approval=lambda d, p: True)
        with patch.object(dispatch, "_optional", modules(policy=always)):
            result = asyncio.run(dispatch.handle(
                hub(term), "delete everything", {"terminal": {"shell": "cmd"}}))
        self.assertTrue(term.ran)
        self.assertFalse(result.data.get("handled", True))

    def test_near_zero_guess_is_not_a_hub_task(self) -> None:
        async def decide(h, text, context):  # noqa: ANN001
            return Decision(category="screen", action="explain", confidence=0.0)

        router = SimpleNamespace(decide=decide)
        with patch.object(dispatch, "_optional", modules(router=router)):
            result = asyncio.run(dispatch.handle(hub(FakeOther()), "Wow, type dir.", {}))
        self.assertFalse(result.data.get("handled", True))

    def test_confident_decision_still_runs(self) -> None:
        async def decide(h, text, context):  # noqa: ANN001
            return Decision(category="screen", action="explain", confidence=0.9)

        router = SimpleNamespace(decide=decide)
        never = SimpleNamespace(needs_approval=lambda d, p: False)
        with patch.object(dispatch, "_optional", modules(router=router, policy=never)):
            result = asyncio.run(dispatch.handle(hub(FakeOther()), "explain this", {}))
        self.assertEqual(result.text, "explained")


class ServeTests(unittest.TestCase):
    def test_pythonw_streams_get_a_sink(self) -> None:
        from vvhub.__main__ import quiet_stdio

        saved = sys.stdout, sys.stderr
        try:
            sys.stdout = sys.stderr = None
            quiet_stdio()
            sys.stderr.write("progress bar\n")  # the call that killed Laya's load
            self.assertIsNotNone(sys.stdout)
        finally:
            for stream in (sys.stdout, sys.stderr):
                if stream not in saved:
                    stream.close()
            sys.stdout, sys.stderr = saved

    def test_laya_is_warmed_at_start_only_when_asked(self) -> None:
        try:
            from fastapi.testclient import TestClient

            from vvhub import server
        except ImportError:
            self.skipTest("hub dependencies not installed")
        calls = []
        with patch.object(server, "_warm_laya", lambda: calls.append(1)):
            for warm in (False, True):
                h = server.Hub(token="t", store=Store(), warm_laya=warm)
                with TestClient(server.create_app(h)):
                    pass
        self.assertEqual(calls, [1])


if __name__ == "__main__":
    unittest.main()
