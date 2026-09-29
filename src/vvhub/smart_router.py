"""The smart router: request text + context -> Decision, decided by Laya.

Laya is weak past ~20 options (TASK.md §2), so routing is two small steps:

  level 1  category  one of the 8 schemas.CATEGORIES, plus a risk question
  level 2  action    the actions the registered skills of that category offer,
           target    and, if the skill offers them, which window / tool

Both levels ask yes/no (`noul`) questions -- one per option, all in one
forward pass -- rather than one n-way `choice`. Measured with the English
checkpoint on evals/intents.jsonl (2026-09-30, GPU):

  level 1   choice 60.5%   noul 81.5%   noul + lexical prior 91.4%
            (held-out 96 phrasings: noul 76%, prior alone 69%, both 87.5%)
  level 2   choice 27/38   noul 33/38   noul + lexical prior 35/38

The lexical prior is word overlap with the option's name and description,
weighted PRIOR_WEIGHT per word.

Confidence is the margin between the winner's combined score and the
runner-up's, not Laya's raw yes-probability: the shipped checkpoint is not
calibrated (its temperatures are rejected at load) and the raw value asked
on 44 of 71 safe requests at 0.55. Over the eval + held-out set (177
requests) a margin of MIN_CONFIDENCE = 0.3 lets 66% act as the user with 4
of those 117 wrong, and sends 15 of the 19 routing errors to a question.
Critical actions ask whatever the confidence (the hard floor for Laya being
"confident while wrong"). The keyword tier is always low confidence.

Before returning, `policy.preflight` marks whether the hub may act as the
user or must ask (critical action, low confidence, risk), so the decision the
store logs says which it was and why (TASK.md rule 10).

What Laya sees is the request plus the front app and window title -- never
OCR, DOM or page text (rule 11: screen and web content are data, they cannot
decide or trigger anything).

Skills may offer targets through two optional methods (duck-typed; not part
of §3.6 yet):

    target_options(decision, context) -> {label: description}   <= 20 shown
    default_target(context) -> label                             when unnamed
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from . import laya_engine, policy
from .laya_engine import terms
from .schemas import CATEGORIES, Decision, is_critical

log = logging.getLogger(__name__)

# Below this, the decision stands but policy asks before acting (rule 10).
MIN_CONFIDENCE = policy.MIN_CONFIDENCE
# Below this, no action of the category fits: the request is not handled.
ACTION_FLOOR = 0.2
# A category with a single action needs a clear yes for it.
SINGLE_ACTION_YES = 0.5
# The keyword tier guesses; everything it decides is asked about.
KEYWORD_CONFIDENCE = 0.1
# A target Laya picks unnamed (a probability over the options, not a margin).
TARGET_CONFIDENCE = 0.6
# Weight of one overlapping word against Laya's 0..1 yes-probability.
PRIOR_WEIGHT = 0.25
MAX_TARGETS = 20  # Laya's comfortable option count

# Laya's questions, one per category, asked together.
CATEGORY_QUESTIONS: dict[str, str] = {
    "screen": "Is the user asking about something currently shown on their screen "
              "(explain, read or summarize this)?",
    "research": "Does the user want the web searched to research or look up a topic?",
    "notes": "Does the user want a note written or saved in Notion?",
    "social": "Is this about Instagram or LinkedIn posts, comments or messages?",
    "github": "Is this about git or GitHub (repositories, branches, commits, pushes, "
              "pull requests)?",
    "code": "Does the user want an AI coding assistant like Claude, Codex or Kiro to write "
            "or change code?",
    "app": "Does the user want to switch to a window or app, or change the microphone or "
           "a setting?",
    "chitchat": "Is this just small talk, a greeting, or thanks?",
}
RISK_QUESTION = ("Would doing this publish, post, send, message, reply, delete, pay, push code "
                 "or create something public on the user's behalf?")
# The lexical prior's vocabulary per category (and the keyword tier's only signal).
CATEGORY_CRITERIA: dict[str, str] = {
    "screen": "about what is on the screen right now: explain this, what is this, read this "
              "error, summarize this page or window, focus on my cursor, unfocus",
    "research": "look something up on the web: research a topic, find articles, search online, "
                "compare products, latest news, deep dive",
    "notes": "write things down in Notion: take a note, note this, make notes about a topic, "
             "save this transcript, add to my notes page",
    "social": "Instagram or LinkedIn: write or publish a post, check notifications, read "
              "comments, reply to comments, social media messages",
    "github": "GitHub and git: create a repository, push code, open a pull request, commit, "
              "branches, issues, list my repos",
    "code": "send a coding prompt to an AI coding tool: ask Claude, Codex, Kiro or the VS Code "
            "terminal to write, fix, refactor, test or review code",
    "app": "control this computer and Voice Vibe: switch or focus a window, change microphone, "
           "save this conversation, hub status",
    "chitchat": "small talk or a general question needing no tool: greetings, thanks, jokes, "
                "how are you, what time is it",
}
assert tuple(CATEGORY_QUESTIONS) == tuple(CATEGORY_CRITERIA) == CATEGORIES
_VOCAB = {c: terms(f"{c} {d}") for c, d in CATEGORY_CRITERIA.items()}

LEVEL1 = {c: {"type": "noul", "instructions": q} for c, q in CATEGORY_QUESTIONS.items()}
LEVEL1["risk"] = {"type": "noul", "instructions": RISK_QUESTION}


def state_for(text: str, context: dict | None) -> dict:
    """What Laya reads: the request and where the user is. Nothing scraped."""
    context = context or {}
    window = context.get("window") or {}
    state = {"request": text.strip()}
    if window.get("process"):
        state["app"] = str(window["process"])[:60]
    if window.get("title"):
        state["window"] = str(window["title"])[:120]
    return state


def prior(text: str) -> dict[str, int]:
    said = terms(text)
    return {c: len(said & vocab) for c, vocab in _VOCAB.items()}


def _ask(state: dict, questions: dict, min_confidence: float | None = None) -> dict:
    return laya_engine.decide(state, questions, min_confidence=min_confidence)


def _margin(scores: dict[str, float], best: str) -> float:
    others = [v for k, v in scores.items() if k != best]
    return max(0.0, min(1.0, scores[best] - max(others))) if others else 1.0


async def classify(text: str, context: dict | None = None) -> tuple[str, float, dict]:
    """Level 1: (category, confidence margin, full Laya result)."""
    state = state_for(text, context)
    result = await asyncio.to_thread(_ask, state, LEVEL1, 0.0)
    answers = result["answers"]
    yes = {c: float(answers[c]["noul"]) for c in CATEGORIES}
    hits = prior(text)
    combined = {c: yes[c] + PRIOR_WEIGHT * hits[c] for c in CATEGORIES}
    # Ties go to the earlier category; chitchat, the catch-all, is last.
    category = max(CATEGORIES, key=lambda c: combined[c])
    result["prior"] = hits
    return category, _margin(combined, category), result


# ------------------------------------------------------------- level 2
def category_actions(skills: dict, category: str) -> dict[str, tuple[Any, str]]:
    """action -> (skill, description) for every skill in `category`. First wins."""
    out: dict[str, tuple[Any, str]] = {}
    for skill in (skills or {}).values():
        if getattr(skill, "category", None) != category:
            continue
        for action, description in (getattr(skill, "actions", None) or {}).items():
            out.setdefault(action, (skill, str(description)))
    return out


async def choose_action(text: str, context: dict | None,
                        actions: dict[str, tuple[Any, str]]) -> tuple[str, float, dict]:
    """Level 2: (action or "", confidence margin, Laya's yes per action)."""
    if not actions:
        return "", 0.0, {}
    questions = {f"act:{a}": {"type": "noul", "instructions": f"Does the user want to {d}?"}
                 for a, (_s, d) in actions.items()}
    result = await asyncio.to_thread(_ask, state_for(text, context), questions, 0.0)
    yes = {a: float(result["answers"][f"act:{a}"]["noul"]) for a in actions}
    said = terms(text)
    combined = {a: yes[a] + PRIOR_WEIGHT * len(said & terms(f"{a.replace('_', ' ')} {d}"))
                for a, (_s, d) in actions.items()}
    best = max(actions, key=lambda a: combined[a])
    if len(actions) == 1:
        # The runner-up is "none of these".
        if yes[best] < SINGLE_ACTION_YES:
            return "", 0.0, yes
        return best, yes[best] - SINGLE_ACTION_YES + MIN_CONFIDENCE, yes
    if yes[best] < ACTION_FLOOR:
        return "", 0.0, yes
    return best, _margin(combined, best), yes


# -------------------------------------------------------------- targets
_POLITE = re.compile(r"^(?:(?:please|computer|hey|ok|okay|can you|could you|would you|will you)"
                     r"[\s,]+)+", re.I)
_NAMED = re.compile(r"\b(?:called|named|titled)\s+(.+)$", re.I)
_SAYING = re.compile(r"\b(?:saying|that says|which says)\s+(.+)$", re.I)
_ABOUT = re.compile(r"\babout\s+(.+)$", re.I)
_LEADING = {
    "research": r"(?:research|look\s+up|look\s+into|find(?:\s+out)?(?:\s+about)?|find\s+me|"
                r"search(?:\s+online|\s+the\s+web)?(?:\s+for)?|do\s+a\s+deep\s+dive\s+on|"
                r"dig\s+into|compare)\s+",
    "notes": r"(?:take\s+a\s+note|make\s+a\s+note|note(?:\s+down)?|jot\s+down|write\s+down|"
             r"remember|add)\s+(?:that\s+)?",
    "app": r"(?:switch\s+to|go\s+to|bring\s+up|open|show\s+me|focus(?:\s+on)?)\s+"
           r"(?:the\s+|my\s+)?",
}
_TRAILING_NOTES = re.compile(r"\s+(?:to|in|into|under)\s+(?:my\s+)?(?:notes?|notion)(?:\s+page)?$",
                             re.I)


def argument(text: str, category: str) -> str:
    """The free-text part of a request, for skills that take one as `target`.

    "create a repo called voice tools" -> "voice tools"; "research X" -> X;
    "post this on linkedin saying hi" -> "exactly: hi" (the social skill's
    verbatim form). "" when the request has no argument ("push my changes").
    """
    said = _POLITE.sub("", text.strip()).strip().rstrip(".?!")
    if category == "social":
        m = _SAYING.search(said)
        if m:
            return "exactly: " + m.group(1).strip()
    m = _NAMED.search(said)
    if m:
        return m.group(1).strip()
    if category in ("research", "notes", "social"):
        m = _ABOUT.search(said)
        if m and category != "research":
            return m.group(1).strip()
    leading = _LEADING.get(category)
    if leading:
        m = re.match(leading, said, re.I)
        if m:
            rest = said[m.end():]
            if category == "notes":
                rest = _TRAILING_NOTES.sub("", rest)
            return rest.strip()
    return ""


def named_option(text: str, options: dict[str, str]) -> str | None:
    """The one option the request names by a word only that option has."""
    said = terms(text)
    words = {label: terms(f"{label.replace('_', ' ')} {desc}") for label, desc in options.items()}
    counts: dict[str, int] = {}
    for vocab in words.values():
        for w in vocab:
            counts[w] = counts.get(w, 0) + 1
    hits = {label: len({w for w in said & vocab if counts[w] == 1}) for label, vocab in words.items()}
    best = max(hits.values(), default=0)
    winners = [label for label, n in hits.items() if n == best]
    return winners[0] if best > 0 and len(winners) == 1 else None


async def choose_target(text: str, context: dict | None, skill: Any,
                        decision: Decision) -> tuple[str, str]:
    """(target label or "", how it was chosen)."""
    getter = getattr(skill, "target_options", None)
    if not callable(getter):
        return "", ""
    try:
        options = dict(list((getter(decision, context or {}) or {}).items())[:MAX_TARGETS])
    except Exception:  # noqa: BLE001 - a skill's lookup must not break routing
        log.exception("target_options failed for %s", getattr(skill, "name", skill))
        options = {}
    default = getattr(skill, "default_target", None)
    fallback = str(default(context or {}) or "") if callable(default) else ""
    if not options:
        return fallback, "default" if fallback else ""
    named = named_option(text, options)
    if named:
        return named, "named"
    if len(options) > 1:
        q = {"target": {"type": "choice", "instructions": "Which one does the user mean?",
                        "criteria": {k: (v or None) for k, v in options.items()}}}
        result = await asyncio.to_thread(_ask, state_for(text, context), q, TARGET_CONFIDENCE)
        answer = result["answers"]["target"]
        if not answer.get("low_confidence") and \
                float(answer.get("answer_confidence", 0)) >= TARGET_CONFIDENCE:
            return answer["choice"], f"laya {float(answer['answer_confidence']):.2f}"
    if fallback:
        return fallback, "default"
    if len(options) == 1:
        return next(iter(options)), "only one"
    return "", ""


# ------------------------------------------------------------- decide
async def decide(hub: Any, text: str, context: dict | None = None) -> Decision | None:
    """The Decision for `text`, or None to leave it unhandled (typed as heard)."""
    if not text or not text.strip():
        return None
    try:
        category, confidence, result = await classify(text, context)
        risk = float(result["answers"]["risk"]["noul"])
        actions = category_actions(getattr(hub, "skills", None) or {}, category)
        action, action_yes, action_scores = await choose_action(text, context, actions)
    except Exception:  # noqa: BLE001 - a Laya failure must not break Voice Vibe
        log.exception("Laya routing failed for %r", text)
        return None

    skill = actions[action][0] if action else None
    level1 = confidence
    # Level 2 is right 35/38 even when its margin is thin (several actions of
    # one skill all sound plausible to Laya), so only level 1's margin gates
    # "act or ask"; level 2 only has to clear its floor. A wrong action inside
    # the right category is a small miss, and critical ones ask regardless.
    if result.get("tier") == "keywords":
        confidence = min(confidence, KEYWORD_CONFIDENCE)
    decision = Decision(category=category, action=action, confidence=confidence, risk=risk)
    target, how = "", ""
    if skill is not None:
        try:
            target, how = await choose_target(text, context, skill, decision)
        except Exception:  # noqa: BLE001
            log.exception("target choice failed for %r", text)
    decision.target = target or argument(text, category)

    ask = policy.preflight(text, decision, skill)
    decision.critical = bool(action) and (is_critical(action)
                                          or action in getattr(skill, "critical_actions", ())) \
        or any(r.startswith("risk") for r in ask)
    decision.needs_approval = bool(ask)
    summary = f"laya {result.get('tier', '?')}: {category} {level1:.2f}"
    if action:
        summary += f" / {action} {action_yes:.2f}"
    decision.reason = f"{summary}; " + (f"ask: {'; '.join(ask)}" if ask else "auto: act as you")
    decision.laya_raw = {
        "request": text.strip(),
        "category": {"choice": category, "yes": {c: result["answers"][c]["noul"]
                                                 for c in CATEGORIES},
                     "prior": result["prior"], "low_confidence": level1 < MIN_CONFIDENCE},
        "risk": risk,
        "action": {"choice": action, "yes": action_scores},
        "target": {"choice": target, "how": how},
        "argument": argument(text, category),
        "tier": result.get("tier"),
        "elapsed_ms": result.get("elapsed_ms"),
    }
    return decision
