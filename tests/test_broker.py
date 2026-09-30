"""Broker (vvhub.broker): Gemini Flash interprets, Laya decides, your words set the floor.

What matters: the model sees the system (skills, coding tools, the context
as fenced data) and answers the hub, not the user; its JSON is validated
field by field; a cleaned request that adds or drops a critical word is
ignored (the user's words are routed instead); a drafted coder prompt is
kept only if Laya agrees it says what the user asked; nothing goes out when
there's no key, the screen is private, or the broker is switched off; and
any failure falls back to the old path. No network, no Laya, no windows.
"""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vvhub import broker, dispatch  # noqa: E402
from vvhub.schemas import Decision, Plan, Result  # noqa: E402
from vvhub.store import Store  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class FakeSkill:
    def __init__(self, name, category, actions, critical=()):
        self.name, self.category, self.actions = name, category, actions
        self.critical_actions = set(critical)
        self.phrases = {}
        self.plans, self.runs = [], []

    async def plan(self, decision, context):
        self.plans.append(decision)
        return Plan(skill=self.name, action=decision.action, args={"prompt": decision.target}, preview="p")

    async def run(self, plan, approval=None, dry_run=False):
        self.runs.append((plan, approval))
        return Result(ok=True, text="done")


SKILLS = {
    "code": FakeSkill("code", "code", {"prompt": "send a coding request to Claude, Codex, Kiro", "fix_this": "fix it"}),
    "app": FakeSkill("app", "app", {"open_app": "open an app"}),
}


def reply(**fields):
    base = {"intent": "Ask Claude Code to add tests", "category": "code", "action": "prompt",
            "target": "claude_code", "request": "ask claude code to add tests for the parser",
            "coder_prompt": "Add unit tests for the parser in src/parser.py covering empty input.",
            "clarify": "", "confidence": 0.9}
    base.update(fields)
    return json.dumps(base)


class FakeLLM:
    def __init__(self, text=None, exc=None, delay=0.0):
        self.text, self.exc, self.delay = text, exc, delay
        self.calls = []

    async def __call__(self, messages, model="auto", max_tokens=800):
        self.calls.append({"messages": messages, "model": model, "max_tokens": max_tokens})
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.text


def hub(store=None):
    return SimpleNamespace(skills=SKILLS, store=store or Store(":memory:"), bus=None)


def make(llm, agree=0.9, models=("gemini-2.5-flash-lite", "gemini-2.5-flash", "llama-3.3-70b"), key="k",
         work=lambda: ""):
    b = broker.Broker(complete=llm, yes_no=lambda state, q: agree, list_models=lambda: list(models),
                      key=lambda: key, work=work)
    return b


class WorkContextTests(unittest.TestCase):
    def test_work_context_sent_fenced(self):
        llm = FakeLLM(reply())
        work = 'Claude Code session "Parser refactor" in C:\\work\\parser\nagent: Next I will add tests.'
        run(make(llm, work=lambda: work).interpret(hub(), "carry on with that", {}))
        user = llm.calls[0]["messages"][1]["content"]
        self.assertIn("Parser refactor", user)
        self.assertIn("working on", user)
        self.assertIn("source=coding sessions", user)

    def test_no_work_context_on_private_screen_or_failure(self):
        llm = FakeLLM(reply())
        run(make(llm, work=lambda: "SECRET PROJECT").interpret(hub(), "x", {"redacted": True}))
        self.assertNotIn("SECRET PROJECT", llm.calls[-1]["messages"][1]["content"])

        def broken():
            raise OSError("disk")

        brief = run(make(llm, work=broken).interpret(hub(), "add tests", {}))
        self.assertIsNotNone(brief)


class InterpretTests(unittest.TestCase):
    def test_brief_from_gemini_flash(self):
        llm = FakeLLM(reply())
        b = make(llm)
        ctx = {"window": {"title": "parser.py - myproj - Visual Studio Code", "process": "Code.exe"},
               "selection": "def parse(x):"}
        brief = run(b.interpret(hub(), "computer ask claude code to add tests for the parse her", ctx))
        self.assertEqual(llm.calls[0]["model"], "gemini-2.5-flash")
        self.assertEqual((brief.category, brief.action, brief.target), ("code", "prompt", "claude_code"))
        self.assertIn("parser", brief.coder_prompt)
        system, user = llm.calls[0]["messages"][0]["content"], llm.calls[0]["messages"][1]["content"]
        for needle in ("prompt", "open_app", "claude_code", "JSON", "Laya", "approval"):
            self.assertIn(needle, system)
        self.assertIn("parse her", user)
        self.assertIn("Visual Studio Code", user)
        self.assertIn("UNTRUSTED", user.upper())  # screen text is fenced as data

    def test_model_override_and_fallback(self):
        llm = FakeLLM(reply())
        b = make(llm, models=("llama-3.3-70b",))
        run(b.interpret(hub(), "add tests", {}))
        self.assertEqual(llm.calls[-1]["model"], "auto")
        b = make(llm)
        b.model_override = "gemini-2.0-flash"
        run(b.interpret(hub(), "add tests", {}))
        self.assertEqual(llm.calls[-1]["model"], "gemini-2.0-flash")

    def test_recent_turns_give_context(self):
        store = Store(":memory:")
        store.add_turn("user", "open the parser project", "c1")
        store.add_turn("hub", "Opened VS Code.", "c1")
        llm = FakeLLM(reply())
        run(make(llm).interpret(hub(store), "now add tests to it", {}, conversation="c1"))
        user = llm.calls[0]["messages"][1]["content"]
        self.assertIn("open the parser project", user)
        self.assertIn("Opened VS Code.", user)

    def test_private_screen_sends_no_screen_text(self):
        llm = FakeLLM(reply())
        ctx = {"redacted": True, "window": {"title": "Bank - Edge"}, "selection": "acct 1234"}
        run(make(llm).interpret(hub(), "explain this", ctx))
        user = llm.calls[0]["messages"][1]["content"]
        self.assertNotIn("1234", user)
        self.assertNotIn("Bank", user)

    def test_failures_fall_back(self):
        from vvhub.llm import LLMUnavailable

        for llm in (FakeLLM("not json at all"), FakeLLM(exc=LLMUnavailable("exhausted", "pool empty")),
                    FakeLLM(exc=RuntimeError("boom")), FakeLLM("{\"category\": 5}")):
            self.assertIsNone(run(make(llm).interpret(hub(), "add tests", {})), llm.text or llm.exc)

    def test_timeout(self):
        b = make(FakeLLM(reply(), delay=1.0))
        b.timeout = 0.05
        self.assertIsNone(run(b.interpret(hub(), "add tests", {})))

    def test_off_without_key_or_when_disabled(self):
        llm = FakeLLM(reply())
        self.assertIsNone(run(make(llm, key=None).interpret(hub(), "add tests", {})))
        b = make(llm)
        b.enabled = False
        self.assertIsNone(run(b.interpret(hub(), "add tests", {})))
        self.assertEqual(llm.calls, [])

    def test_code_fences_and_unknown_fields(self):
        llm = FakeLLM("```json\n" + reply(category="weather", action="rm_rf", target="x" * 500) + "\n```")
        brief = run(make(llm).interpret(hub(), "add tests", {}))
        self.assertEqual((brief.category, brief.action), ("", ""))
        self.assertLessEqual(len(brief.target), 80)


class ModelChoiceTests(unittest.TestCase):
    CATALOG = ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-robotics-er-2-preview",
               "gemini-3.5-flash-lite", "gemini-3-flash-preview", "gemini-3.1-flash-lite", "gemini-2.5-flash",
               "gemini-2.5-flash-lite", "llama-3.3-70b", "google/gemini-3.6-flash-image"]

    def test_newest_flash_first_lite_and_preview_later(self):
        order = broker.candidates(self.CATALOG)
        self.assertEqual(order[:5], ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
                                     "gemini-2.5-flash", "gemini-3-flash-preview"])
        self.assertEqual(order[-1], "auto")
        self.assertNotIn("gemini-robotics-er-2-preview", order)
        self.assertNotIn("google/gemini-3.6-flash-image", order)
        self.assertEqual(broker.pick_model(self.CATALOG), "gemini-3.7-flash")

    def test_failing_model_is_rested_and_next_one_used(self):
        from vvhub.llm import LLMUnavailable

        class Picky(FakeLLM):
            async def __call__(self, messages, model="auto", max_tokens=800):
                self.calls.append({"model": model})
                if model == "gemini-3.7-flash":
                    raise LLMUnavailable("exhausted", "429 rate limited")
                return reply()

        llm = Picky()
        b = make(llm, models=self.CATALOG)
        brief = run(b.interpret(hub(), "add tests", {}))
        self.assertEqual(brief.model, "gemini-3.6-flash")
        self.assertEqual([c["model"] for c in llm.calls], ["gemini-3.7-flash", "gemini-3.6-flash"])
        run(b.interpret(hub(), "add tests", {}))
        self.assertEqual(llm.calls[-1]["model"], "gemini-3.6-flash")  # 3.7 is resting
        self.assertEqual(len(llm.calls), 3)


class SafetyTests(unittest.TestCase):
    def test_request_cannot_add_or_drop_critical_words(self):
        self.assertEqual(broker.safe_request("delete the old branch", "clean up the old branch"),
                         "delete the old branch")
        self.assertEqual(broker.safe_request("tidy the old branch", "delete the old branch"),
                         "tidy the old branch")
        self.assertEqual(broker.safe_request("surround the cloud", "run claude"), "run claude")
        self.assertEqual(broker.safe_request("push it", "push the current branch"), "push the current branch")
        self.assertEqual(broker.safe_request("open notepad", ""), "open notepad")

    def test_coder_prompt_kept_only_if_laya_agrees(self):
        brief = run(make(FakeLLM(reply()), agree=0.1).interpret(hub(), "ask claude to add parser tests", {}))
        self.assertEqual(brief.coder_prompt, "")
        brief = run(make(FakeLLM(reply()), agree=0.8).interpret(hub(), "ask claude to add parser tests", {}))
        self.assertTrue(brief.coder_prompt)

    def test_coder_prompt_with_new_critical_words_dropped(self):
        llm = FakeLLM(reply(coder_prompt="Add tests, then git push --force and delete old files."))
        brief = run(make(llm).interpret(hub(), "ask claude to add parser tests", {}))
        self.assertEqual(brief.coder_prompt, "")


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.seen = {}
        seen = self.seen

        async def decide(hub_, text, context):
            seen["routed"] = text
            return Decision(category="code", action="prompt", target=text, confidence=0.9, risk=0.1,
                            laya_raw={"request": text})

        class Approvals:
            @staticmethod
            async def request(hub_, plan, conversation=None):
                seen["asked"] = plan.action
                return SimpleNamespace(status="denied")

        import vvhub.policy as policy

        self.modules = {"smart_router": SimpleNamespace(decide=decide), "policy": policy,
                        "approvals": Approvals}
        self._orig = dispatch._optional

    def tearDown(self):
        dispatch._optional = self._orig

    def use(self, brief):
        async def interpret(hub_, text, context, conversation=None):
            return brief

        mods = dict(self.modules, broker=SimpleNamespace(interpret=interpret))
        dispatch._optional = lambda name: mods.get(name)

    def test_broker_request_routed_and_recorded(self):
        brief = broker.Brief(intent="Ask Claude Code", category="code", action="prompt", target="claude_code",
                             request="ask claude code to add tests", coder_prompt="Add tests.", clarify="",
                             confidence=0.9, model="gemini-2.5-flash", elapsed_ms=800)
        self.use(brief)
        h = hub()
        skills = {"code": FakeSkill("code", "code", {"prompt": "x"})}
        h.skills = skills
        result = run(dispatch.handle(h, "ask cloud code to add tests", {}))
        self.assertTrue(result.ok)
        self.assertEqual(self.seen["routed"], "ask claude code to add tests")
        decision = skills["code"].plans[0]
        self.assertEqual(decision.laya_raw["broker"]["coder_prompt"], "Add tests.")
        self.assertEqual(decision.laya_raw["heard"], "ask cloud code to add tests")
        self.assertIn("Ask Claude Code", decision.reason)

    def test_no_broker_same_as_before(self):
        self.use(None)
        h = hub()
        h.skills = {"code": FakeSkill("code", "code", {"prompt": "x"})}
        run(dispatch.handle(h, "add tests", {}))
        self.assertEqual(self.seen["routed"], "add tests")

    def test_floor_uses_the_users_words(self):
        brief = broker.Brief(intent="x", category="code", action="prompt", target="", request="publish it",
                             coder_prompt="", clarify="", confidence=0.9, model="m", elapsed_ms=1)
        self.use(brief)
        h = hub()
        h.skills = {"code": FakeSkill("code", "code", {"prompt": "x"})}
        # The user's own words name a critical act; the decision's risk is high enough.
        async def decide(hub_, text, context):
            return Decision(category="code", action="prompt", target=text, confidence=0.9, risk=0.6)

        self.modules["smart_router"] = SimpleNamespace(decide=decide)
        self.use(brief)
        result = run(dispatch.handle(h, "post it to linkedin", {}))
        self.assertEqual(self.seen.get("asked"), "prompt")
        self.assertEqual(result.text, "Cancelled.")


class CodeSkillTests(unittest.TestCase):
    def test_plan_uses_broker_prompt_and_tool(self):
        from vvhub.skills.code import CodeSkill

        skill = CodeSkill()
        d = Decision(category="code", action="prompt", target="", confidence=0.9,
                     laya_raw={"request": "ask it to add parser tests",
                               "broker": {"coder_prompt": "Add unit tests for src/parser.py.",
                                          "target": "claude_code"}})
        plan = run(skill.plan(d, {}))
        self.assertEqual(plan.args["prompt"], "Add unit tests for src/parser.py.")
        self.assertEqual(plan.args["tool"], "claude_code")

    def test_plan_without_broker_unchanged(self):
        from vvhub.skills.code import CodeSkill

        d = Decision(category="code", action="prompt", target="", confidence=0.9,
                     laya_raw={"request": "ask claude code to add parser tests"})
        plan = run(CodeSkill().plan(d, {}))
        self.assertEqual(plan.args["tool"], "claude_code")
        self.assertIn("parser tests", plan.args["prompt"])


if __name__ == "__main__":
    unittest.main()
