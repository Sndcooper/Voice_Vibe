"""vvhub.policy: when the hub acts as the user and when it asks first.

Rules under test (TASK.md rule 10): critical actions always ask; policy can
only add a requirement, never remove one; low confidence asks; free text
forwarded to another agent asks when it names a critical act.
"""

from __future__ import annotations

import unittest

import stubs

stubs.install()

from vvhub import policy  # noqa: E402
from vvhub.schemas import Decision, Plan  # noqa: E402


def decision(**kw) -> Decision:  # noqa: ANN003
    base = dict(category="github", action="status", confidence=0.9, risk=0.1)
    base.update(kw)
    return Decision(**base)


class FloorTests(unittest.TestCase):
    def test_critical_action_names_always_ask(self) -> None:
        for action in ("push", "create_repo", "create_pr", "linkedin_post", "instagram_post",
                       "send_message", "delete_file", "pay_bill"):
            plan = Plan(skill="x", action=action)
            self.assertTrue(policy.needs_approval(decision(action=action), plan), action)

    def test_plan_or_decision_critical_asks(self) -> None:
        self.assertTrue(policy.needs_approval(decision(), Plan(skill="x", action="status",
                                                               critical=True)))
        self.assertTrue(policy.needs_approval(decision(critical=True),
                                              Plan(skill="x", action="status")))

    def test_confident_small_task_acts_as_user(self) -> None:
        self.assertFalse(policy.needs_approval(decision(), Plan(skill="x", action="status")))

    def test_decision_needs_approval_is_never_dropped(self) -> None:
        d = decision(needs_approval=True)
        self.assertTrue(policy.needs_approval(d, Plan(skill="x", action="status")))

    def test_plan_cannot_unmark_critical(self) -> None:
        plan = Plan(skill="x", action="git_push", critical=False)
        self.assertTrue(plan.critical)
        self.assertTrue(policy.needs_approval(decision(action="git_push"), plan))


class EscalationTests(unittest.TestCase):
    def test_low_confidence_asks(self) -> None:
        d = decision(confidence=0.1)
        self.assertTrue(policy.needs_approval(d, Plan(skill="x", action="status")))
        self.assertIn("low confidence", " ".join(policy.reasons(d, Plan(skill="x",
                                                                         action="status"))))

    def test_low_confidence_does_not_ask_to_say_an_error(self) -> None:
        d = decision(confidence=0.1)
        self.assertFalse(policy.needs_approval(d, Plan(skill="x", action="say",
                                                       preview="I can't do that")))

    def test_high_risk_asks(self) -> None:
        d = decision(risk=0.95)
        self.assertTrue(policy.needs_approval(d, Plan(skill="x", action="status")))

    def test_critical_word_with_some_risk_asks(self) -> None:
        reasons = policy.preflight("delete my latest linkedin post",
                                   decision(action="linkedin_feed", risk=0.6))
        self.assertTrue(any("delete" in r for r in reasons), reasons)

    def test_critical_word_alone_is_not_enough(self) -> None:
        # "how did my last post do" names "post" but reads; Laya sees no risk.
        self.assertEqual(policy.preflight("how did my last linkedin post do",
                                          decision(action="linkedin_feed", risk=0.1)), [])

    def test_forwarded_prompt_with_critical_act_asks(self) -> None:
        plan = Plan(skill="code", action="prompt",
                    args={"prompt": "fix the tests then push to main"})
        self.assertTrue(policy.needs_approval(decision(category="code", action="prompt"), plan))
        plan = Plan(skill="code", action="prompt", args={"prompt": "add unit tests"})
        self.assertFalse(policy.needs_approval(decision(category="code", action="prompt"), plan))

    def test_critical_words_are_whole_words(self) -> None:
        self.assertEqual(policy.critical_words("repost the compost"), [])
        self.assertEqual(policy.critical_words("please send it"), ["send"])
        self.assertIn("pull request", policy.critical_words("open a pull request"))
        self.assertIn("create repo", policy.critical_words("create a new github repository"))

    def test_reasons_explain_auto(self) -> None:
        self.assertEqual(policy.reasons(decision(), Plan(skill="x", action="status")), [])


class PipelineTests(unittest.TestCase):
    """Through WS0's real dispatch + Store: the decision log says auto or ask."""

    def setUp(self) -> None:
        import asyncio
        import json

        from vvhub import dispatch, laya_engine
        from vvhub.laya_engine import Engine
        from vvhub.schemas import Result
        from vvhub.skills.base import Skill
        from vvhub.store import Store

        self.asyncio, self.json, self.dispatch = asyncio, json, dispatch

        class Git(Skill):
            name, category = "git", "github"
            actions = {"status": "say the current branch", "push": "push the branch"}
            critical_actions = {"push"}
            ran: list = []

            async def run(self, plan, approval=None, dry_run=False):  # noqa: ANN001, ANN201
                self.ran.append(plan.action)
                return Result(ok=True, text=f"did {plan.action}")

        class Laya:
            def predict(self, state, questions, min_confidence=None):  # noqa: ANN001, ANN201
                req = state["request"]
                want = {"github": 0.95, "act:status": 0.9 if "branch" in req else 0.05,
                        "act:push": 0.9 if "push" in req else 0.05}
                return {"answers": {q: {"type": "noul", "noul": want.get(q, 0.02)}
                                    for q in questions}}

        self.old = laya_engine.set_engine(Engine(loader=Laya, tier="fake"))
        self.skill = Git()
        self.skill.ran = []
        self.hub = type("Hub", (), {})()
        self.hub.store, self.hub.bus, self.hub.skills = Store(":memory:"), None, {"git": self.skill}
        self.skill.bind(self.hub)

    def tearDown(self) -> None:
        from vvhub import laya_engine

        laya_engine.set_engine(self.old)

    def logged(self) -> dict:
        return self.json.loads(self.hub.store.decisions()[-1]["decision"])

    def test_small_task_runs_and_logs_auto(self) -> None:
        result = self.asyncio.run(self.dispatch.handle(self.hub, "what branch am i on"))
        self.assertTrue(result.ok)
        self.assertEqual(self.skill.ran, ["status"])
        entry = self.logged()
        self.assertEqual(entry["action"], "status")
        self.assertIn("auto", entry["reason"])
        self.assertFalse(entry["needs_approval"])

    def test_critical_task_never_runs_without_approval(self) -> None:
        import sys
        from unittest import mock

        # Whatever approvals says, a non-approved answer means nothing runs.
        denied = type("A", (), {"status": "denied"})()
        fake = type(sys)("vvhub.approvals")

        async def request(hub, plan, conversation=None):  # noqa: ANN001, ANN202
            fake.asked.append(plan.action)
            return denied

        fake.asked, fake.request = [], request
        with mock.patch.dict(sys.modules, {"vvhub.approvals": fake}):
            result = self.asyncio.run(self.dispatch.handle(self.hub, "push my changes"))
        self.assertFalse(result.ok)
        self.assertEqual(fake.asked, ["push"])
        self.assertEqual(self.skill.ran, [])
        entry = self.logged()
        self.assertTrue(entry["critical"])
        self.assertIn("ask", entry["reason"])


if __name__ == "__main__":
    unittest.main()
