"""When the hub acts as the user, and when it asks first (TASK.md rule 10).

`dispatch` asks `needs_approval(decision, plan)` after the skill has planned,
and ORs the answer with its own floor (plan/decision critical, or a critical
word in the action name). So this module can only ever add a question:

  floor       critical action name, Plan.critical, Decision.critical,
              Decision.needs_approval (set by the router's preflight)
  confidence  Laya's confidence below the router's threshold -> ask
  risk        Laya's yes-probability that the request publishes, sends,
              deletes, pays or pushes something, at or above RISK_ASK -> ask;
              a critical word in the spoken request lowers the bar to
              RISK_WITH_WORD (a word alone is not enough: "how did my last
              post do" reads, it does not post)
  forwarded   free text the plan hands to another agent (a prompt for Claude
              Code, a message body) that names a critical act -> ask, since
              that agent may carry it out

Everything that is not asked about is an "auto" decision: the hub acted as
the user. `preflight` runs in the router before the plan exists, so the
decision the store logs already says which it was and why.
"""

from __future__ import annotations

import re
from typing import Any

from .schemas import Decision, Plan, is_critical

MIN_CONFIDENCE = 0.3  # same threshold as smart_router (a score margin, not a probability)
RISK_ASK = 0.9
RISK_WITH_WORD = 0.5

# Spoken forms of the critical list (rule 10), matched as whole words.
CRITICAL_PHRASES = {
    "post": r"post|publish|publishing|posting",
    "send": r"send|sending",
    "message": r"message|dm|text\s+him|text\s+her",
    "reply": r"reply|respond",
    "comment": r"comment",
    "delete": r"delete|remove|erase|wipe",
    "pay": r"pay|buy|purchase|order",
    "push": r"push|force[-\s]push",
    "merge": r"merge",
    "pull request": r"pull\s+request|\bpr\b",
    "create repo": r"(?:create|make|new)\s+(?:a\s+)?(?:new\s+)?(?:\w+\s+)?(?:repo|repository)",
}
_PHRASES = {name: re.compile(rf"\b(?:{pattern})\b", re.I) for name, pattern in CRITICAL_PHRASES.items()}

# Plan args that are handed on, verbatim, to something that can act.
FORWARDED_ARGS = ("prompt", "message", "body")
# Plans that only speak; asking before saying "I can't do that" is noise.
SPEAK_ONLY = frozenset({"say"})


def critical_words(text: str) -> list[str]:
    """Which critical acts `text` names, e.g. ["delete", "post"]."""
    return [name for name, pattern in _PHRASES.items() if pattern.search(text or "")]


def preflight(text: str, decision: Decision, skill: Any = None) -> list[str]:
    """Reasons to ask, known before the skill plans. Empty = act as the user."""
    out = []
    action = decision.action or ""
    if action and (is_critical(action) or action in getattr(skill, "critical_actions", ())):
        out.append(f"critical action {action}")
    if decision.confidence < MIN_CONFIDENCE:
        out.append(f"low confidence {decision.confidence:.2f}")
    if decision.risk >= RISK_ASK:
        out.append(f"risk {decision.risk:.2f}")
    else:
        words = critical_words(text)
        if words and decision.risk >= RISK_WITH_WORD:
            out.append(f"risk {decision.risk:.2f} and said {', '.join(words)}")
    return out


def reasons(decision: Decision, plan: Plan) -> list[str]:
    """Every reason to ask about `plan`. Empty = act as the user."""
    if plan.action in SPEAK_ONLY and not plan.critical:
        return []
    out = []
    if plan.critical or is_critical(plan.action):
        out.append(f"critical action {plan.action}")
    if decision.critical:
        out.append("critical decision")
    if decision.needs_approval:
        out.append(decision.reason or "router asked")
    if decision.confidence < MIN_CONFIDENCE:
        out.append(f"low confidence {decision.confidence:.2f}")
    if decision.risk >= RISK_ASK:
        out.append(f"risk {decision.risk:.2f}")
    for key in FORWARDED_ARGS:
        value = plan.args.get(key) if isinstance(plan.args, dict) else None
        if isinstance(value, str):
            words = critical_words(value)
            if words:
                out.append(f"forwarded {key} says {', '.join(words)}")
    return out


def needs_approval(decision: Decision, plan: Plan) -> bool:
    return bool(reasons(decision, plan))
