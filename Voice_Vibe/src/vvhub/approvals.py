"""Approvals: ask the user before a critical action, by voice or on Telegram.

    approval = await approvals.request(hub, plan, conversation=...)   # dispatch
    approval = await approvals.request(action, preview, critical=True) # skills (§3.5)

Channel order (TASK.md §3.5, rule 17):

  voice     Voice Vibe connected -> `confirm {prompt, preview, timeout}`. Voice
            Vibe speaks the prompt and listens with its existing
            `confirm.VoiceConfirmer` (strict yes / loose no / silence = no).
            A reply with `unavailable: true` means no session is armed, and
            only then does the request move on to Telegram. A voice "no" or a
            voice timeout is final.
  telegram  bot connected -> `approval_request {approval: <record>, timeout}`,
            answered by the bot's card (buttons, or a strict yes/no text or
            voice note) with `approval_result {approved, decided_by, answer}`.
  ui        the control app (WS5), same message as the bot, if neither of
            the above is there.
  nobody    denied.

Timeout = deny (stored as "expired"). Every request and its outcome goes into
the store's approvals table.

The hub never trusts a yes it did not check itself: a typed or spoken answer
must pass the same strict rule as Voice Vibe and the bot (`vvbot.answers`
rule: every word a yes-word, any no-word = no), and then Laya is asked
whether the answer is an unambiguous yes to *this* request. Laya can only
turn a yes into a no, never the reverse (rule 10). A button press is its own
unambiguous answer. Measured with the English checkpoint: clear yeses score
0.60-0.82, no / "yes but not now" / "Thank you." 0.00-0.27 -> floor 0.4.

Voice questions go one at a time (one microphone, one confirmer); Telegram
cards can be open side by side.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from . import laya_engine, protocol
from .schemas import Approval, Plan

log = logging.getLogger(__name__)

VOICE_TIMEOUT = protocol.TIMEOUTS.get("confirm", 15.0)
TELEGRAM_TIMEOUT = protocol.TIMEOUTS.get("approval_request", 300.0)
# Speaking the question takes time too, before the answer clock starts.
VOICE_SLACK = 20.0
REPLY_SLACK = 5.0
MAX_PROMPT = 160
LAYA_FLOOR = 0.4
LAYA_QUESTION = "Is the answer an unambiguous yes?"

# Same rule as voicevibe.confirm and vvbot.answers.
YES_WORDS = frozenset({"yes", "yeah", "yep", "confirm", "confirmed", "approve", "approved"})
NO_PHRASES = ("no", "nope", "cancel", "stop", "deny", "denied", "reject", "don't", "dont",
              "do not", "never mind", "nevermind")
UNSPOKEN = frozenset({"", "button", "tap", "click"})
_SAY_NOT = re.compile(r"\b(?:yes|yeah|yep|confirm(?:ed)?|approved?)\b[!,.]?\s*", re.I)

_hub: Any = None
_pending: dict[str, Approval] = {}
_voice_lock: asyncio.Lock | None = None
_voice_loop: Any = None


def reset() -> None:
    """Forget the bound hub and open requests (tests)."""
    global _hub, _voice_lock, _voice_loop
    _hub = None
    _pending.clear()
    _voice_lock = _voice_loop = None


def bind(hub: Any) -> None:
    """Make `hub` the default for skill-style calls; expire rows left pending
    by a previous run (their asker is gone, so they were never approved)."""
    global _hub
    _hub = hub
    store = getattr(hub, "store", None)
    if store is None:
        return
    try:
        for row in store.approvals("pending"):
            if row["id"] not in _pending:
                store.update_approval(row["id"], "expired", "hub restart")
    except Exception:  # noqa: BLE001
        log.exception("Could not expire stale approvals")


def pending() -> list[Approval]:
    return list(_pending.values())


def _lock() -> asyncio.Lock:
    global _voice_lock, _voice_loop
    loop = asyncio.get_running_loop()
    if _voice_lock is None or _voice_loop is not loop:
        _voice_lock, _voice_loop = asyncio.Lock(), loop
    return _voice_lock


# ------------------------------------------------------------- answers
def _normal(text: str) -> str:
    text = (text or "").lower().replace("\u2019", "'")
    return " ".join(re.sub(r"[^a-z' ]+", " ", text).split())


def strict_yes(text: str) -> bool | None:
    """True = yes, False = no, None = anything else."""
    said = _normal(text)
    if not said:
        return None
    if any(f" {phrase} " in f" {said} " for phrase in NO_PHRASES):
        return False
    if all(word in YES_WORDS for word in said.split()):
        return True
    return None


def _laya_agrees(preview: str, answer: str) -> bool:
    try:
        p = laya_engine.yes_no({"question": preview[:400], "answer": answer[:200]}, LAYA_QUESTION)
    except laya_engine.LayaUnavailable:
        return True  # the strict rule already said yes; nothing to downgrade with
    except Exception:  # noqa: BLE001 - an unexpected failure must not approve
        log.exception("Laya check of an approval answer failed")
        return False
    log.info("Laya: answer %r -> yes %.2f", answer, p)
    return p >= LAYA_FLOOR


async def verify(approved: bool, answer: str, preview: str) -> tuple[bool, str]:
    """(approved, why). Only ever turns a yes into a no."""
    if not approved:
        return False, "said no"
    if _normal(answer) in UNSPOKEN:
        return True, "button" if answer else "confirmed"
    if strict_yes(answer) is not True:
        return False, f"not a clear yes: {answer!r}"
    if not await asyncio.to_thread(_laya_agrees, preview, answer):
        return False, f"Laya doubts {answer!r}"
    return True, "yes"


def spoken_prompt(preview: str) -> str:
    """First line of the preview, short, as a question, without yes-words (so
    an echo of the question can never be heard as its answer)."""
    text = " ".join((preview or "").split())
    text = _SAY_NOT.sub("", text).strip() or "Go ahead"
    if len(text) > MAX_PROMPT:
        text = text[: MAX_PROMPT - 1].rsplit(" ", 1)[0] + "…"
    return text.rstrip("?.!:") + "?"


# ------------------------------------------------------------- request
def _store(hub: Any) -> Any:
    return getattr(hub, "store", None)


def _record(hub: Any, approval: Approval, conversation: str | None) -> None:
    store = _store(hub)
    if store is None:
        return
    try:
        store.add_approval(approval.to_dict(), conversation)
    except Exception:  # noqa: BLE001
        log.exception("Could not store approval %s", approval.id)


def _finish(hub: Any, approval: Approval, status: str, decided_by: str, why: str) -> Approval:
    approval.status, approval.decided_by = status, decided_by
    _pending.pop(approval.id, None)
    store = _store(hub)
    if store is not None:
        try:
            store.update_approval(approval.id, status, decided_by)
        except Exception:  # noqa: BLE001
            log.exception("Could not update approval %s", approval.id)
    log.info("Approval %s %s (%s via %s): %s", approval.id, status, approval.action,
             approval.channel, why)
    return approval


def _connected(hub: Any, role: str) -> bool:
    bus = getattr(hub, "bus", None)
    try:
        return bool(bus is not None and bus.connected(role))
    except Exception:  # noqa: BLE001
        return False


async def _ask_voice(hub: Any, approval: Approval) -> dict | None:
    """confirm_result, or None when no session is armed (try the next channel)."""
    msg = protocol.message("confirm", prompt=spoken_prompt(approval.preview),
                           preview=approval.preview, timeout=VOICE_TIMEOUT,
                           approval_id=approval.id)
    async with _lock():
        reply = await hub.bus.send_to("voicevibe", msg, timeout=VOICE_TIMEOUT + VOICE_SLACK)
    if reply.get("unavailable"):
        return None
    return reply


async def _ask_card(hub: Any, role: str, approval: Approval) -> dict:
    msg = protocol.message("approval_request", approval=approval.to_dict(),
                           timeout=TELEGRAM_TIMEOUT)
    return await hub.bus.send_to(role, msg, timeout=TELEGRAM_TIMEOUT + REPLY_SLACK)


async def request(hub_or_action: Any, plan_or_preview: Any = None, *, critical: bool = True,
                  conversation: str | None = None) -> Approval:
    """Ask, wait, return the decided Approval (status approved/denied/expired).

    `critical` is accepted for §3.5; every request is asked either way -- a
    skill that asks for approval gets asked about.
    """
    if isinstance(hub_or_action, str):
        hub, action, preview = _hub, hub_or_action, str(plan_or_preview or hub_or_action)
    else:
        hub = hub_or_action
        plan: Plan = plan_or_preview
        action, preview = plan.action, plan.preview or plan.action
        if _hub is None:
            bind(hub)
    approval = Approval(action=action, preview=preview, created=time.time())
    if hub is None:
        approval.channel = "voice"
        return _finish(hub, approval, "denied", "nobody", "no hub bound")

    order = [c for c, role in (("voice", "voicevibe"), ("telegram", "bot"), ("ui", "ui"))
             if _connected(hub, role)]
    approval.channel = order[0] if order else "voice"
    _record(hub, approval, conversation)
    _pending[approval.id] = approval
    try:
        for channel in order:
            approval.channel = channel
            if channel == "voice":
                reply = await _ask_voice(hub, approval)
                if reply is None:
                    log.info("No armed session; asking on the next channel.")
                    continue
            else:
                reply = await _ask_card(hub, "bot" if channel == "telegram" else "ui", approval)
            if reply.get("type") == "error":
                return _finish(hub, approval, "denied", channel,
                               f"error: {reply.get('message', '')}")
            ok, why = await verify(reply.get("approved") is True, str(reply.get("answer") or ""),
                                   approval.preview)
            return _finish(hub, approval, "approved" if ok else "denied",
                           str(reply.get("decided_by") or channel), why)
        return _finish(hub, approval, "denied", "nobody", "no channel to ask on")
    except asyncio.TimeoutError:
        return _finish(hub, approval, "expired", approval.channel, "no answer in time")
    except Exception as exc:  # noqa: BLE001 - any failure while asking is a no
        log.exception("Approval %s failed", approval.id)
        return _finish(hub, approval, "denied", approval.channel, f"failed: {exc}")
