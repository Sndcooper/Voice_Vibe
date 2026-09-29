"""From request text to a Result: the pipeline the other streams plug into.

    1. exact skill phrases ("ping hub")          -> that skill
    2. vvhub.smart_router.decide(hub, text, ctx) -> Decision   (WS2)
    3. skill.plan(decision, ctx)                 -> Plan
    4. vvhub.policy.needs_approval(decision, plan) (WS2), never below the floor
    5. vvhub.approvals.request(hub, plan)          (WS2) when needed
    6. skill.run(plan, approval)

Missing WS2 modules degrade safely: no smart router means "not handled"
(Voice Vibe types the text, rule 8); a critical plan with no approvals module
is refused, never run (rule 10).
"""

from __future__ import annotations

import importlib
import logging
import re
from typing import Any

from .schemas import Decision, Plan, Result, is_critical

log = logging.getLogger(__name__)

NOT_HANDLED = Result(ok=False, text="", speak=False, data={"handled": False})


def _optional(name: str) -> Any:
    try:
        return importlib.import_module(f"vvhub.{name}")
    except ImportError as exc:
        if exc.name and exc.name.startswith(f"vvhub.{name}"):
            return None
        raise


def normalize(text: str) -> str:
    text = re.sub(r"[^\w\s']", " ", text.lower())
    return " ".join(text.split())


def match_phrase(skills: dict, text: str) -> tuple[Any, str] | None:
    said = normalize(text)
    for skill in skills.values():
        for phrase, action in skill.phrases.items():
            if said == normalize(phrase):
                return skill, action
    return None


async def handle(hub: Any, text: str, context: dict | None = None,
                 conversation: str | None = None, source: str = "voice") -> Result:
    context = context or {}
    hub.store.add_turn("user", text, conversation, {"source": source})
    result = await _decide_and_run(hub, text, context, conversation)
    if result.data.get("handled", True):
        hub.store.add_turn("hub", result.text, conversation, {"ok": result.ok})
    return result


async def _decide_and_run(hub: Any, text: str, context: dict, conversation: str | None) -> Result:
    exact = match_phrase(hub.skills, text)
    if exact:
        skill, action = exact
        decision = Decision(category=skill.category, action=action, confidence=1.0,
                            reason="exact phrase")
    else:
        router = _optional("smart_router")
        if router is None:
            return NOT_HANDLED
        decision = await router.decide(hub, text, context)
        if decision is None:
            return NOT_HANDLED
        skill = _skill_for(hub.skills, decision)
        if skill is None:
            return NOT_HANDLED

    hub.store.add_decision(text, decision.to_dict(), conversation)
    plan: Plan = await skill.plan(decision, context)

    needs = plan.critical or decision.critical or is_critical(plan.action)
    policy = _optional("policy")
    if policy is not None:
        # Policy may add a requirement, never remove the floor.
        needs = needs or bool(policy.needs_approval(decision, plan))
    elif decision.needs_approval:
        needs = True

    approval = None
    if needs:
        approvals = _optional("approvals")
        if approvals is None:
            return Result(ok=False, text="That needs your approval, and approvals are not set up yet.")
        approval = await approvals.request(hub, plan, conversation=conversation)
        if getattr(approval, "status", None) != "approved":
            return Result(ok=False, text="Cancelled.")

    try:
        return await skill.run(plan, approval=approval)
    except Exception as exc:  # noqa: BLE001 - a skill bug must not kill the hub
        log.exception("Skill %s failed on %s", skill.name, plan.action)
        return Result(ok=False, text=f"{skill.name} failed: {exc}")


def _skill_for(skills: dict, decision: Decision) -> Any:
    for skill in skills.values():
        if decision.action in skill.actions and skill.category == decision.category:
            return skill
    for skill in skills.values():
        if decision.action in skill.actions:
            return skill
    return None
