"""The terminal skill: spoken request -> one shell command (fake Laya, no GPU).

The real-model check is tools/eval_terminal.py (46/46 on 2026-09-30).
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

import stubs

stubs.install()

from vvhub import laya_engine, protocol  # noqa: E402
from vvhub.schemas import Decision  # noqa: E402
from vvhub.shell_words import shell_text, spoken_to_shell, strip_submit  # noqa: E402
from vvhub.skills import terminal as t  # noqa: E402


class FakeLaya:
    """Says yes to the page whose question mentions `wanted`."""

    def __init__(self, wanted: str = "", risk: float = 0.0, tier: str = "gpu") -> None:
        self.wanted, self.risk, self.tier = wanted, risk, tier

    def decide(self, state, questions, min_confidence=None):  # noqa: ANN001
        answers = {}
        for name, q in questions.items():
            if name == "risk":
                answers[name] = {"noul": self.risk}
            else:
                hit = self.wanted and f"(the {self.wanted} command)" in q["instructions"]
                answers[name] = {"noul": 0.9 if hit else 0.05}
        return {"answers": answers, "tier": self.tier}


def choose(text: str, shell: str = "cmd", laya: FakeLaya | None = None) -> t.Choice:
    old = laya_engine.decide
    laya_engine.decide = (laya or FakeLaya()).decide
    try:
        return asyncio.run(t.choose(text, shell))
    finally:
        laya_engine.decide = old


class WordsTests(unittest.TestCase):
    def test_spoken_symbols(self) -> None:
        self.assertEqual(spoken_to_shell("python app dot py"), "python app.py")
        self.assertEqual(spoken_to_shell("git log dash dash oneline"), "git log --oneline")
        self.assertEqual(spoken_to_shell("dir slash a"), "dir /a")
        self.assertEqual(shell_text("cd dot dot"), "cd ..")
        self.assertEqual(shell_text("Git status."), "git status")
        self.assertEqual(strip_submit("list the files, and press enter."), "list the files")


class DirectTests(unittest.TestCase):
    def test_words_that_are_commands(self) -> None:
        for said, command in (("git status", "git status"), ("Claude.", "claude"),
                              ("cd dot dot", "cd .."), ("ping google", "ping google.com"),
                              ("check the git status", "git status")):
            c = choose(said)
            self.assertEqual((c.source, c.command, c.run), ("direct", command, True), said)

    def test_sentences_are_not_direct(self) -> None:
        for said in ("find the word error in log.txt", "show installed python packages",
                     "print hello world"):
            self.assertNotEqual(choose(said).source, "direct", said)

    def test_danger_is_critical(self) -> None:
        self.assertTrue(choose("git push").critical)
        self.assertTrue(choose("del notes.txt").critical)
        self.assertFalse(choose("git log").critical)


class CatalogTests(unittest.TestCase):
    def test_laya_picks_the_page_variant_from_the_request(self) -> None:
        c = choose("go to the downloads folder", laya=FakeLaya("cd"))
        self.assertEqual(c.command, "cd /d %USERPROFILE%\\Downloads")
        self.assertTrue(c.run)
        self.assertEqual(choose("go back one folder", laya=FakeLaya("cd")).command, "cd ..")
        self.assertEqual(choose("make a folder called test", laya=FakeLaya("mkdir")).command,
                         "mkdir test")
        self.assertEqual(choose("show hidden files", laya=FakeLaya("dir")).command, "dir /a")

    def test_powershell_variants(self) -> None:
        c = choose("go to the downloads folder", "powershell", FakeLaya("cd"))
        self.assertEqual(c.command, "cd $HOME\\Downloads")
        # "dir /a" is cmd syntax: never offered to PowerShell.
        self.assertNotIn("/a", choose("show hidden files", "powershell", FakeLaya("dir")).command)

    def test_placeholder_left_open_is_not_run(self) -> None:
        c = choose("clone a repo", laya=FakeLaya("git clone"))
        self.assertEqual(c.source, "catalog")
        self.assertFalse(c.run)
        self.assertNotIn("{{", c.command)

    def test_danger_from_catalog_and_laya_risk(self) -> None:
        c = choose("kill notepad", laya=FakeLaya("taskkill"))
        self.assertEqual(c.command, "taskkill /im notepad.exe")
        self.assertTrue(c.critical)
        c = choose("show the folder structure", laya=FakeLaya("tree", risk=0.95))
        self.assertTrue(c.critical)  # Laya can only add a question

    def test_not_a_command(self) -> None:
        for said in ("hello how are you", "i like pizza a lot"):
            self.assertEqual(choose(said, laya=FakeLaya()).command, "", said)
        c = choose("clear the screen", laya=FakeLaya("nothing-matches"))
        self.assertEqual(c.command, "")  # Laya says no to every command

    def test_keyword_tier_needs_a_clear_winner(self) -> None:
        c = choose("hello there", laya=FakeLaya(tier="keywords"))
        self.assertEqual(c.command, "")


class FakeBus:
    def __init__(self) -> None:
        self.sent = []

    def connected(self, role: str) -> bool:
        return role == "voicevibe"

    async def send_to(self, role, msg, timeout=None):  # noqa: ANN001
        self.sent.append(msg)
        return protocol.reply_to(msg, "steps_result", ok=True)


class SkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = t.TerminalSkill()
        self.bus = FakeBus()
        self.skill.bind(SimpleNamespace(bus=self.bus))

    def plan(self, said: str, laya: FakeLaya | None = None):  # noqa: ANN201
        old = laya_engine.decide
        laya_engine.decide = (laya or FakeLaya()).decide
        try:
            return asyncio.run(self.skill.plan(
                Decision(category="code", action="shell_command"),
                {"request": said, "terminal": {"shell": "cmd"}}))
        finally:
            laya_engine.decide = old

    def test_types_and_runs(self) -> None:
        plan = self.plan("git status")
        result = asyncio.run(self.skill.run(plan))
        self.assertTrue(result.ok)
        steps = self.bus.sent[0]["steps"]
        self.assertEqual(steps, [{"keys": "esc"}, {"type_text": "git status"}, {"keys": "enter"}])
        self.assertEqual(result.data, {"command": "git status", "ran": True})

    def test_nothing_found_is_handed_back_untyped(self) -> None:
        plan = self.plan("hello how are you")
        self.assertTrue(plan.args["noop"])
        result = asyncio.run(self.skill.run(plan))
        self.assertFalse(result.data["handled"])
        self.assertEqual(self.bus.sent, [])

    def test_critical_needs_an_approved_approval(self) -> None:
        plan = self.plan("del notes.txt")
        self.assertTrue(plan.critical)
        self.assertEqual(plan.preview, "Run del notes.txt?")
        self.assertEqual(asyncio.run(self.skill.run(plan)).text, "Cancelled.")
        self.assertEqual(self.bus.sent, [])
        ok = asyncio.run(self.skill.run(plan, approval=SimpleNamespace(status="approved")))
        self.assertTrue(ok.ok)


if __name__ == "__main__":
    unittest.main()
