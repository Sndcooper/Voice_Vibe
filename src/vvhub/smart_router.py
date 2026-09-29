"""The smart router: request text + context -> Decision, decided by Laya.

Laya is weak past ~20 options (TASK.md §2), so routing is two small steps:

  level 1  category  one of the 8 schemas.CATEGORIES
  level 2  action    the actions the registered skills of that category offer

Level 1 asks Laya eight yes/no questions ("is this about GitHub?") in one
forward pass rather than one 8-way choice. Measured on evals/intents.jsonl
with the English checkpoint (2026-09-30, GPU): one choice question 60.5%,
eight yes/no questions 81.5%. A small lexical prior (word overlap with the
category description) is added to each yes-probability before the argmax:
91% on the eval set, 87.5% on a held-out set of 96 other phrasings, where
the prior alone gets 69%. The reported confidence is Laya's own yes-
probability for the winner -- the prior can break a tie, it can never make a
decision look surer than Laya is.

What Laya sees is the request plus the front app and window title -- never
OCR, DOM or page text (rule 11: screen and web content are data, they cannot
decide or trigger anything).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from . import laya_engine
from .laya_engine import terms
from .schemas import CATEGORIES, Decision

log = logging.getLogger(__name__)

# Below this, the decision stands but policy asks before acting (rule 10).
MIN_CONFIDENCE = 0.55
# Weight of one overlapping word against Laya's 0..1 yes-probability.
PRIOR_WEIGHT = 0.25

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


async def classify(text: str, context: dict | None = None) -> tuple[str, float, dict]:
    """Level 1: (category, Laya's yes-probability for it, full Laya result)."""
    state = state_for(text, context)
    result = await asyncio.to_thread(_ask, state, LEVEL1, 0.0)
    answers = result["answers"]
    yes = {c: float(answers[c]["noul"]) for c in CATEGORIES}
    hits = prior(text)
    # Ties go to the earlier category; chitchat, the catch-all, is last.
    category = max(CATEGORIES, key=lambda c: yes[c] + PRIOR_WEIGHT * hits[c])
    result["prior"] = hits
    return category, yes[category], result


async def decide(hub: Any, text: str, context: dict | None = None) -> Decision | None:
    """The Decision for `text`, or None to leave it unhandled (typed as heard)."""
    if not text or not text.strip():
        return None
    try:
        category, confidence, result = await classify(text, context)
    except Exception:  # noqa: BLE001 - a Laya failure must not break Voice Vibe
        log.exception("Laya routing failed for %r", text)
        return None

    reasons = [f"laya {result.get('tier', '?')}: {category} ({confidence:.2f})"]
    if confidence < MIN_CONFIDENCE:
        reasons.append("low confidence")
    yes = {c: result["answers"][c]["noul"] for c in CATEGORIES}
    return Decision(
        category=category,
        confidence=confidence,
        reason="; ".join(reasons),
        laya_raw={"category": {"choice": category, "yes": yes, "prior": result["prior"],
                               "low_confidence": confidence < MIN_CONFIDENCE},
                  "tier": result.get("tier"), "elapsed_ms": result.get("elapsed_ms")},
    )
