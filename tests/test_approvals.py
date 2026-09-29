"""vvhub.approvals: voice first, else Telegram; timeout = deny; Laya only downgrades.

A fake bus stands in for Voice Vibe and the bot; the store is WS0's real
in-memory Store. Laya is a scripted fake.
"""

from __future__ import annotations

import asyncio
import unittest

import stubs

stubs.install()

from vvhub import approvals, laya_engine  # noqa: E402
from vvhub.laya_engine import Engine  # noqa: E402
from vvhub.schemas import Approval, Plan  # noqa: E402
from vvhub.store import Store  # noqa: E402


def run(coro):  # noqa: ANN001, ANN201
    return asyncio.run(coro)


class FakeBus:
    """`replies[role]` is a dict reply, an exception to raise, or a callable(msg)."""

    def __init__(self, connected=("voicevibe", "bot"), replies=None) -> None:  # noqa: ANN001
        self.up = set(connected)
        self.replies = replies or {}
        self.sent: list[tuple[str, dict, float | None]] = []

    def connected(self, role: str) -> bool:
        return role in self.up

    async def send_to(self, role: str, msg: dict, timeout=None) -> dict:  # noqa: ANN001
        self.sent.append((role, msg, timeout))
        reply = self.replies.get(role)
        if callable(reply):
            reply = reply(msg)
        if isinstance(reply, BaseException):
            raise reply
        if reply is None:
            raise asyncio.TimeoutError()
        return dict(reply, re=msg["id"])


class FakeHub:
    def __init__(self, bus: FakeBus) -> None:
        self.bus = bus
        self.store = Store(":memory:")
        self.skills = {}


class YesNo:
    def __init__(self, p: float) -> None:
        self.p = p
        self.states: list = []

    def predict(self, state, questions, min_confidence=None):  # noqa: ANN001, ANN201
        self.states.append(state)
        return {"answers": {q: {"type": "noul", "noul": self.p} for q in questions}}


PLAN = Plan(skill="github", action="push", preview="Push feature-x to GitHub")


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.laya = YesNo(0.9)
        self.old = laya_engine.set_engine(Engine(loader=lambda: self.laya, tier="fake"))
        approvals.reset()

    def tearDown(self) -> None:
        laya_engine.set_engine(self.old)
        approvals.reset()


class VoiceTests(Base):
    def test_voice_yes_approves_and_is_stored(self) -> None:
        bus = FakeBus(replies={"voicevibe": {"type": "confirm_result", "approved": True,
                                             "answer": "yes"}})
        hub = FakeHub(bus)
        approval = run(approvals.request(hub, PLAN))
        self.assertIsInstance(approval, Approval)
        self.assertEqual((approval.status, approval.channel, approval.decided_by),
                         ("approved", "voice", "voice"))
        role, msg, timeout = bus.sent[0]
        self.assertEqual((role, msg["type"]), ("voicevibe", "confirm"))
        self.assertIn("Push feature-x", msg["prompt"])
        self.assertEqual(msg["preview"], "Push feature-x to GitHub")
        self.assertEqual(msg["timeout"], approvals.VOICE_TIMEOUT)
        self.assertGreater(timeout, approvals.VOICE_TIMEOUT)
        row = hub.store.approvals()[0]
        self.assertEqual((row["status"], row["channel"], row["decided_by"]),
                         ("approved", "voice", "voice"))

    def test_voice_no_denies_and_never_falls_back(self) -> None:
        bus = FakeBus(replies={"voicevibe": {"type": "confirm_result", "approved": False,
                                             "answer": "no"}})
        approval = run(approvals.request(FakeHub(bus), PLAN))
        self.assertEqual(approval.status, "denied")
        self.assertEqual([r for r, _m, _t in bus.sent], ["voicevibe"])

    def test_voice_timeout_is_expired_not_telegram(self) -> None:
        bus = FakeBus(replies={"voicevibe": asyncio.TimeoutError()})
        hub = FakeHub(bus)
        approval = run(approvals.request(hub, PLAN))
        self.assertEqual(approval.status, "expired")
        self.assertEqual([r for r, _m, _t in bus.sent], ["voicevibe"])
        self.assertEqual(hub.store.approvals()[0]["status"], "expired")

    def test_no_armed_session_goes_to_telegram(self) -> None:
        bus = FakeBus(replies={
            "voicevibe": {"type": "confirm_result", "approved": False, "answer": "",
                          "unavailable": True},
            "bot": {"type": "approval_result", "approved": True, "decided_by": "telegram",
                    "answer": "button"}})
        approval = run(approvals.request(FakeHub(bus), PLAN))
        self.assertEqual((approval.status, approval.channel), ("approved", "telegram"))
        self.assertEqual([r for r, _m, _t in bus.sent], ["voicevibe", "bot"])

    def test_spoken_prompt_is_short_and_never_says_yes(self) -> None:
        bus = FakeBus(replies={"voicevibe": {"type": "confirm_result", "approved": False,
                                             "answer": "no"}})
        long = Plan(skill="social", action="linkedin_post",
                    preview="Post to LinkedIn:\nYes! Say yes to voice tools. " + "word " * 200)
        run(approvals.request(FakeHub(bus), long))
        prompt = bus.sent[0][1]["prompt"]
        self.assertLessEqual(len(prompt), approvals.MAX_PROMPT + 1)
        self.assertNotRegex(prompt.lower(), r"\byes\b")
        self.assertIn("word word", bus.sent[0][1]["preview"])

    def test_voice_answer_is_rechecked_strictly(self) -> None:
        bus = FakeBus(replies={"voicevibe": {"type": "confirm_result", "approved": True,
                                             "answer": "yes but not that one"}})
        self.assertEqual(run(approvals.request(FakeHub(bus), PLAN)).status, "denied")


class TelegramTests(Base):
    def test_bot_gets_the_record_and_timeout(self) -> None:
        bus = FakeBus(connected=("bot",), replies={"bot": {
            "type": "approval_result", "approved": True, "decided_by": "telegram",
            "answer": "button"}})
        hub = FakeHub(bus)
        approval = run(approvals.request(hub, PLAN))
        role, msg, timeout = bus.sent[0]
        self.assertEqual((role, msg["type"]), ("bot", "approval_request"))
        record = msg["approval"]
        self.assertEqual(record["id"], approval.id)
        self.assertEqual(record["action"], "push")
        self.assertEqual(record["channel"], "telegram")
        self.assertEqual(msg["timeout"], approvals.TELEGRAM_TIMEOUT)
        self.assertGreater(timeout, approvals.TELEGRAM_TIMEOUT)
        self.assertEqual(approval.status, "approved")

    def test_typed_or_voice_note_yes_is_checked_by_laya(self) -> None:
        self.laya.p = 0.1  # Laya reads "yes" here as not a clear yes
        bus = FakeBus(connected=("bot",), replies={"bot": {
            "type": "approval_result", "approved": True, "decided_by": "telegram",
            "answer": "yes"}})
        approval = run(approvals.request(FakeHub(bus), PLAN))
        self.assertEqual(approval.status, "denied")
        state = self.laya.states[-1]
        self.assertEqual(state["answer"], "yes")
        self.assertIn("Push feature-x", state["question"])

    def test_laya_never_upgrades_a_no(self) -> None:
        self.laya.p = 0.99
        bus = FakeBus(connected=("bot",), replies={"bot": {
            "type": "approval_result", "approved": False, "decided_by": "telegram",
            "answer": "yes"}})
        self.assertEqual(run(approvals.request(FakeHub(bus), PLAN)).status, "denied")

    def test_non_yes_text_is_refused_even_if_bot_approved(self) -> None:
        bus = FakeBus(connected=("bot",), replies={"bot": {
            "type": "approval_result", "approved": True, "decided_by": "telegram",
            "answer": "hmm maybe"}})
        self.assertEqual(run(approvals.request(FakeHub(bus), PLAN)).status, "denied")

    def test_button_skips_the_text_checks(self) -> None:
        self.laya.p = 0.0
        bus = FakeBus(connected=("bot",), replies={"bot": {
            "type": "approval_result", "approved": True, "decided_by": "telegram",
            "answer": "button"}})
        self.assertEqual(run(approvals.request(FakeHub(bus), PLAN)).status, "approved")

    def test_laya_missing_keeps_strict_check(self) -> None:
        def broken():  # noqa: ANN202
            raise ImportError("no torch")

        laya_engine.set_engine(Engine(loader=broken, tier="gpu"))
        bus = FakeBus(connected=("bot",), replies={"bot": {
            "type": "approval_result", "approved": True, "decided_by": "telegram",
            "answer": "yes"}})
        self.assertEqual(run(approvals.request(FakeHub(bus), PLAN)).status, "approved")

    def test_bot_timeout_expires(self) -> None:
        bus = FakeBus(connected=("bot",), replies={"bot": asyncio.TimeoutError()})
        self.assertEqual(run(approvals.request(FakeHub(bus), PLAN)).status, "expired")

    def test_error_reply_is_denied(self) -> None:
        bus = FakeBus(connected=("bot",), replies={"bot": {"type": "error", "message": "x"}})
        self.assertEqual(run(approvals.request(FakeHub(bus), PLAN)).status, "denied")


class QueueTests(Base):
    def test_nobody_to_ask_is_denied(self) -> None:
        hub = FakeHub(FakeBus(connected=()))
        approval = run(approvals.request(hub, PLAN))
        self.assertEqual((approval.status, approval.decided_by), ("denied", "nobody"))
        self.assertEqual(hub.store.approvals()[0]["status"], "denied")

    def test_voice_questions_are_asked_one_at_a_time(self) -> None:
        active, peak = [0], [0]

        async def slow(msg):  # noqa: ANN001, ANN202
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            await asyncio.sleep(0.01)
            active[0] -= 1
            return {"type": "confirm_result", "approved": True, "answer": "yes", "re": msg["id"]}

        class SlowBus(FakeBus):
            async def send_to(self, role, msg, timeout=None):  # noqa: ANN001, ANN202
                self.sent.append((role, msg, timeout))
                return await slow(msg)

        hub = FakeHub(SlowBus())

        async def both():  # noqa: ANN202
            return await asyncio.gather(approvals.request(hub, PLAN), approvals.request(hub, PLAN))

        results = run(both())
        self.assertEqual([a.status for a in results], ["approved", "approved"])
        self.assertEqual(peak[0], 1)

    def test_pending_lists_open_requests(self) -> None:
        seen = []

        def reply(msg):  # noqa: ANN001, ANN202
            seen.append([a.action for a in approvals.pending()])
            return {"type": "approval_result", "approved": False, "answer": "button"}

        run(approvals.request(FakeHub(FakeBus(connected=("bot",), replies={"bot": reply})), PLAN))
        self.assertEqual(seen, [["push"]])
        self.assertEqual(approvals.pending(), [])

    def test_stale_pending_rows_expire_on_bind(self) -> None:
        hub = FakeHub(FakeBus(connected=()))
        hub.store.add_approval(Approval(action="push", preview="old").to_dict())
        approvals.bind(hub)
        self.assertEqual(hub.store.approvals()[0]["status"], "expired")

    def test_skill_style_call_uses_the_bound_hub(self) -> None:
        bus = FakeBus(connected=("bot",), replies={"bot": {
            "type": "approval_result", "approved": True, "answer": "button"}})
        approvals.bind(FakeHub(bus))
        approval = run(approvals.request("linkedin_post", "Post to LinkedIn: hi", critical=True))
        self.assertEqual((approval.action, approval.status), ("linkedin_post", "approved"))

    def test_skill_style_call_without_hub_is_denied(self) -> None:
        approval = run(approvals.request("push", "Push it"))
        self.assertEqual(approval.status, "denied")


class DispatchTests(Base):
    """WS0's dispatch -> smart_router -> policy -> approvals -> skill."""

    def test_critical_runs_only_after_voice_yes(self) -> None:
        from vvhub import dispatch
        from vvhub.schemas import Result
        from vvhub.skills.base import Skill

        class Git(Skill):
            name, category = "git", "github"
            actions = {"push": "push the current branch to GitHub"}

            def __init__(self) -> None:
                super().__init__()
                self.ran: list = []

            async def run(self, plan, approval=None, dry_run=False):  # noqa: ANN001, ANN201
                self.ran.append((plan.action, approval.status))
                return Result(ok=True, text="Pushed.")

        class Laya:
            def predict(self, state, questions, min_confidence=None):  # noqa: ANN001, ANN201
                yes = {"github": 0.95, "act:push": 0.9, "yes_no": 0.8}
                return {"answers": {q: {"type": "noul", "noul": yes.get(q, 0.02)}
                                    for q in questions}}

        laya_engine.set_engine(Engine(loader=Laya, tier="fake"))
        for answer, ran in (("no", []), ("yes", [("push", "approved")])):
            bus = FakeBus(replies={"voicevibe": {"type": "confirm_result",
                                                 "approved": answer == "yes", "answer": answer}})
            hub = FakeHub(bus)
            skill = Git()
            hub.skills = {"git": skill}
            result = run(dispatch.handle(hub, "push my changes"))
            self.assertEqual(skill.ran, ran, answer)
            self.assertEqual(result.ok, answer == "yes")
            self.assertEqual(bus.sent[0][1]["type"], "confirm")


if __name__ == "__main__":
    unittest.main()
