"""Gemini through FreeLLMAPI: the model chain, spoken answers, terminal proposals.

Fakes only: no network, no Gemini, no Laya model.
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

import stubs

stubs.install()

from vvhub import laya_engine, llm  # noqa: E402
from vvhub.skills import terminal as t  # noqa: E402
from vvhub.skills.ask import AskSkill, is_question  # noqa: E402


class FakeLLM:
    def __init__(self, reply: str = "", error: Exception | None = None) -> None:
        self.reply, self.error, self.calls = reply, error, []

    async def complete(self, messages, model="auto", max_tokens=800):  # noqa: ANN001
        self.calls.append(messages)
        if self.error:
            raise self.error
        return self.reply


def with_laya(yes: float):  # noqa: ANN201
    class Ctx:
        def __enter__(self):  # noqa: ANN204
            self.old = laya_engine.yes_no
            laya_engine.yes_no = lambda state, instruction: yes
            return self

        def __exit__(self, *exc):  # noqa: ANN002, ANN204
            laya_engine.yes_no = self.old

    return Ctx()


def propose(request: str, reply: str, yes: float) -> t.Choice:
    with with_laya(yes):
        return asyncio.run(t.propose(request, "cmd", t.Choice(reason="x"), FakeLLM(reply)))


class ProposalTests(unittest.TestCase):
    def test_safe_read_only_and_sure_runs(self) -> None:
        c = propose("count the lines in app.py",
                    '{"command": "find /v /c \\"\\" app.py", "does": "Count lines in app.py"}', 0.9)
        self.assertEqual((c.command, c.run, c.critical, c.source),
                         ('find /v /c "" app.py', True, False, "gemini"))

    def test_anything_else_asks(self) -> None:
        c = propose("find big python files",
                    '```json\n{"command": "for /r %F in (*.py) do @echo %F", "does": "List py files"}\n```',
                    0.9)
        self.assertTrue(c.critical)
        c = propose("delete the logs", '{"command": "del *.log", "does": "Delete log files"}', 0.95)
        self.assertTrue(c.critical)
        c = propose("show commits", '{"command": "git log -n 5 > out.txt", "does": "Save log"}', 0.9)
        self.assertTrue(c.critical)  # a redirect writes a file

    def test_laya_veto_and_none(self) -> None:
        self.assertEqual(propose("x", '{"command": "dir", "does": "List files"}', 0.2).command, "")
        self.assertEqual(propose("hello", '{"command": "NONE", "does": ""}', 0.9).command, "")
        self.assertEqual(propose("x", "not json at all", 0.9).command, "")

    def test_blank_is_typed_not_run(self) -> None:
        c = propose("wifi password", '{"command": "netsh wlan show profile name=\\"[SSID]\\" key=clear",'
                                     ' "does": "Show a Wi-Fi password"}', 0.9)
        self.assertEqual((c.run, c.critical), (False, False))

    def test_no_llm_keeps_the_previous_choice(self) -> None:
        prev = t.Choice(reason="laya unsure")
        with with_laya(0.9):
            c = asyncio.run(t.propose("x", "cmd", prev, FakeLLM(error=llm.LLMUnavailable("offline", "x"))))
        self.assertIs(c, prev)

    def test_read_only(self) -> None:
        for cmd in ("dir /a", "git log -n 5", "findstr error log.txt", "python --version",
                    "tasklist | findstr chrome"):
            self.assertTrue(t.read_only(cmd), cmd)
        for cmd in ("del x", "git push", "dir > out.txt", "echo hi && del x", "tasklist | taskkill"):
            self.assertFalse(t.read_only(cmd), cmd)
        self.assertTrue(t.dangerous("tar xvf reports"))


class AskTests(unittest.TestCase):
    def run_ask(self, question: str, fake: FakeLLM):  # noqa: ANN201
        skill = AskSkill(llm=fake)
        plan = asyncio.run(skill.plan(SimpleNamespace(target=""), {"request": question}))
        return plan, asyncio.run(skill.run(plan))

    def test_answers_questions(self) -> None:
        plan, r = self.run_ask("how do I undo a git commit?",
                               FakeLLM("Draft 1: Run **git reset --soft HEAD~1**."))
        self.assertTrue(r.ok)
        self.assertEqual(r.text, "Run git reset --soft HEAD~1.")

    def test_non_questions_are_handed_back(self) -> None:
        fake = FakeLLM("should not be asked")
        plan, r = self.run_ask("draft the meeting notes", fake)
        self.assertTrue(plan.args["noop"])
        self.assertFalse(r.data["handled"])
        self.assertEqual(fake.calls, [])

    def test_unavailable_is_spoken(self) -> None:
        err = llm.LLMUnavailable("exhausted", "429", "The free AI pool is used up for now.")
        _plan, r = self.run_ask("what is rust?", FakeLLM(error=err))
        self.assertEqual(r.text, "The free AI pool is used up for now.")

    def test_is_question(self) -> None:
        self.assertTrue(is_question("what's the capital of Australia"))
        self.assertTrue(is_question("explain recursion"))
        self.assertFalse(is_question("open terminal"))


class ChainTests(unittest.TestCase):
    def test_falls_through_to_the_next_model(self) -> None:
        client = llm.Client(key=lambda: "k", models=llm.PREFERRED)
        seen = []

        async def post(body, retries=None):  # noqa: ANN001
            seen.append(body["model"])
            if body["model"] == "gemini-3.7-flash":
                raise llm.LLMUnavailable("unavailable", "503 high demand")
            return "ok"

        client._post = post
        self.assertEqual(asyncio.run(client.complete([{"role": "user", "content": "hi"}])), "ok")
        self.assertEqual(seen[:2], ["gemini-3.7-flash", "gemini-3.6-flash"])
        self.assertEqual(client.last_model, "gemini-3.6-flash")
        # The failed model cools down: the next call skips it.
        seen.clear()
        asyncio.run(client.complete([{"role": "user", "content": "hi"}]))
        self.assertEqual(seen, ["gemini-3.6-flash"])

    def test_no_key_is_not_retried_on_other_models(self) -> None:
        client = llm.Client(key=lambda: "k", models=llm.PREFERRED)
        calls = []

        async def post(body, retries=None):  # noqa: ANN001
            calls.append(body["model"])
            raise llm.LLMUnavailable("no_key", "401")

        client._post = post
        with self.assertRaises(llm.LLMUnavailable):
            asyncio.run(client.complete([{"role": "user", "content": "hi"}]))
        self.assertEqual(len(calls), 1)

    def test_explicit_model_is_used_alone(self) -> None:
        client = llm.Client(key=lambda: "k", models=llm.PREFERRED)
        seen = []

        async def post(body, retries=None):  # noqa: ANN001
            seen.append(body["model"])
            return "ok"

        client._post = post
        asyncio.run(client.complete([], model="gemini-2.5-flash"))
        self.assertEqual(seen, ["gemini-2.5-flash"])


if __name__ == "__main__":
    unittest.main()
