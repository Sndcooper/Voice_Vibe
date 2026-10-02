"""Social skill: LinkedIn / Instagram through OpenCLI in the user's Edge (T15).

Reads use OpenCLI built-ins (`linkedin timeline`, `linkedin inbox`) and our
plugin (`voicevibe instagram-notifications`). Writes:

- `linkedin_post` -> our plugin `voicevibe linkedin-post --send`
- `instagram_post` -> OpenCLI's built-in `instagram post --media`

Every write follows the same gate, in order, and stops at the first "no":
1. the FreeLLMAPI draft (or the user's exact words) passes local hard checks
   (length, emails/phones/keys, injection phrasing) — the safety floor,
   because Laya can be confident while wrong;
2. Laya validates the draft (`yes_no`); Laya missing = no post (rule 9);
3. an approval (rule 10) — and for posts, one decided by the user at the
   laptop (voice/ui). A Telegram "yes" is not enough to publish, so nothing
   is ever posted while the user is away (user instruction 2026-09-30);
4. one OpenCLI call. A failed or unconfirmed step is reported and never
   retried automatically ("stop and ask").
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any

from ..browser import OpenCLI, OpenCLIError, untrusted
from ..browser.services import Services, approved, call, channel_of, field, is_llm_unavailable
from ..schemas import Plan, Result
from .base import Skill

PRESENT_CHANNELS = {"voice", "ui"}
LIMITS = {"linkedin_post": 3000, "instagram_post": 2200}
MIN_LAYA = 0.6
MEDIA_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".mp4")

_VERBATIM = re.compile(r"^\s*(exactly|saying|verbatim)\s*[:,]?\s*", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\s-]?){10,13}(?!\d)")
_SECRET = re.compile(r"(?i)\b(password|passwd|api[_ -]?key|secret|token|otp)\b\s*[:=]|\b(sk|ghp|gho|xox[bp])[-_][A-Za-z0-9]{16,}")
_MEDIA_PATH = re.compile(r"[A-Za-z]:\\[^\"<>|?*\n]+?\.(?:jpe?g|png|webp|mp4)\b", re.I)

DRAFT_SYSTEM = {
    "linkedin_post": ("You write LinkedIn posts in the user's own first-person voice. Output only the post "
                      "text: no preamble, no quotes, at most three hashtags, under 1200 characters. Never "
                      "include email addresses, phone numbers or private details."),
    "instagram_post": ("You write short Instagram captions in the user's own voice. Output only the caption: "
                       "no preamble, no quotes, at most five hashtags, under 400 characters."),
}
SITE = {"linkedin_post": "LinkedIn", "instagram_post": "Instagram"}


def hard_check(text: str, limit: int) -> str | None:
    """Local safety floor for anything we publish. Returns a reason or None."""
    if not text.strip():
        return "the draft is empty"
    if len(text) > limit:
        return f"the draft is {len(text)} characters, over the {limit} limit"
    if _SECRET.search(text):
        return "the draft looks like it contains a password or key"
    if _EMAIL.search(text) or _PHONE.search(text):
        return "the draft contains an email address or phone number"
    if untrusted.suspicious(text):
        return "the draft contains instruction-like text"
    return None


def find_media(target: str, context: dict) -> list[str]:
    paths = [m.group(0).strip() for m in _MEDIA_PATH.finditer(target or "")]
    selection = str((context or {}).get("selection") or "").strip().strip('"')
    if not paths and selection.lower().endswith(MEDIA_EXTS):
        paths = [selection]
    return [p for p in paths if os.path.isfile(p)]


class SocialSkill(Skill):
    name = "social"
    category = "social"
    actions = {
        "linkedin_post": "write and publish a LinkedIn post about something (always asks first)",
        "instagram_post": "publish a photo or video to Instagram with a caption (always asks first)",
        "linkedin_feed": "read the latest posts in my LinkedIn feed",
        "linkedin_messages": "check my LinkedIn messages and unread conversations",
        "instagram_notifications": "check my Instagram notifications (likes, comments, follows)",
    }
    critical_actions = {"linkedin_post", "instagram_post"}

    def __init__(self, cli: OpenCLI | None = None, services: Services | None = None,
                 present_channels: set[str] | None = None) -> None:
        super().__init__()
        self._cli = cli
        self._services = services
        self.present_channels = present_channels or PRESENT_CHANNELS

    @property
    def cli(self) -> OpenCLI:
        if self._cli is None:
            self._cli = OpenCLI()
        return self._cli

    @property
    def services(self) -> Services:
        return self._services or Services(self.hub)

    # ------------------------------------------------------------ planning

    async def plan(self, decision: Any, context: dict) -> Plan:
        action = field(decision, "action", "") or ""
        target = str(field(decision, "target", "") or "").strip()
        critical = bool(field(decision, "critical", False)) or action in self.critical_actions
        if action not in LIMITS:
            return Plan(skill=self.name, action=action, args={"target": target},
                        preview=self.actions.get(action, action), critical=critical)
        args: dict[str, Any] = {"topic": target}
        if action == "instagram_post":
            args["media"] = find_media(target, context)
            if not args["media"]:
                return self._say("I need the photo first: select the image file in Explorer and ask again.")
        text, error = await self._draft(action, target, context)
        if error:
            return self._say(error)
        problem = hard_check(text, LIMITS[action]) or await self._laya_check(action, target, text)
        if problem:
            return self._say(f"I won't post that: {problem}. Say it differently or tell me the exact words.")
        args["text"] = text
        media = f" with {len(args.get('media', []))} file(s)" if action == "instagram_post" else ""
        preview = f"Post to {SITE[action]}{media}:\n{text}"
        return Plan(skill=self.name, action=action, args=args, preview=preview, critical=True)

    def _say(self, text: str) -> Plan:
        """A plan that only tells the user why nothing will be posted. Its
        action is deliberately not a post, so nobody is asked to approve it."""
        return Plan(skill=self.name, action="say", args={"error": text}, preview=text)

    async def _draft(self, action: str, topic: str, context: dict) -> tuple[str, str | None]:
        if _VERBATIM.match(topic):
            return _VERBATIM.sub("", topic, count=1).strip().strip('"'), None
        if not topic:
            return "", f"What should the {SITE[action]} post be about?"
        llm = self.services.get("llm")
        if llm is None:
            return "", "The writing service isn't set up, so tell me the exact words: 'post exactly …'."
        user = f"Write it about: {topic}"
        material = str((context or {}).get("selection") or "").strip()
        if material:
            user += "\n\nBackground the user has selected (use facts only):\n" + untrusted.fence(material, "selection", 4000)
        messages = [{"role": "system", "content": DRAFT_SYSTEM[action] + " " + untrusted.DATA_ONLY},
                    {"role": "user", "content": user}]
        try:
            text = await llm.complete(messages, max_tokens=600)
        except Exception as exc:  # noqa: BLE001
            if is_llm_unavailable(exc):
                return "", "The writing service is out of free quota; tell me the exact words: 'post exactly …'."
            raise
        return untrusted.clean(str(text or "")).strip('"'), None

    async def _laya_check(self, action: str, topic: str, text: str) -> str | None:
        laya = self.services.get("laya")
        fn = getattr(laya, "yes_no", None)
        if fn is None:
            return "the local checker (Laya) isn't running"
        state = f"Topic the user asked for: {topic}\n\nDraft {SITE[action]} post:\n{text}"
        instruction = (f"Is this draft a suitable public {SITE[action]} post about the requested topic, "
                       "written as the user, with no private or sensitive information?")
        try:
            score = float(await call(fn, state, instruction))
        except Exception:  # noqa: BLE001
            return "the local checker (Laya) failed"
        return None if score >= MIN_LAYA else "the local checker wasn't confident it's appropriate"

    # ------------------------------------------------------------- running

    async def run(self, plan: Plan, approval: Any = None, dry_run: bool = False) -> Result:
        args = plan.args or {}
        if args.get("error"):
            return Result(ok=False, text=args["error"])
        if plan.action in LIMITS:
            return await self._publish(plan, approval, dry_run)
        if dry_run:
            return Result(ok=True, text=f"Would {plan.preview}.", speak=False)
        try:
            if plan.action == "linkedin_feed":
                return self._say_feed(await self.cli.run("linkedin", "timeline", flags={"limit": 5}))
            if plan.action == "linkedin_messages":
                return self._say_inbox(await self.cli.run("linkedin", "inbox", flags={"limit": 10}))
            if plan.action == "instagram_notifications":
                rows = await self.cli.run("voicevibe", "instagram-notifications", flags={"limit": 20})
                return self._say_instagram(rows)
        except OpenCLIError as exc:
            if exc.kind == "empty":
                return Result(ok=True, text="Nothing new there.")
            return Result(ok=False, text=f"I couldn't check that: {exc.spoken}.")
        return Result(ok=False, text="I can't do that on social media yet.")

    async def _publish(self, plan: Plan, approval: Any, dry_run: bool) -> Result:
        args = plan.args
        site = SITE[plan.action]
        if dry_run:
            return Result(ok=True, text=f"Would ask you, then {plan.preview}", speak=False,
                          data={"text": args["text"]})
        if approval is None:
            # Only when the hub didn't gate it already. A denied/expired
            # approval that was passed in is final: never ask again.
            approvals = self.services.get("approvals")
            if approvals is None or not hasattr(approvals, "request"):
                return Result(ok=False, text="Approvals aren't available, so I won't post.")
            approval = await approvals.request(plan.action, plan.preview, critical=True)
        if not approved(approval):
            return Result(ok=False, text=f"Okay, I won't post to {site}.")
        if channel_of(approval) not in self.present_channels:
            return Result(ok=False, text=f"Posting to {site} needs you at the laptop; ask me again there.")
        try:
            if plan.action == "linkedin_post":
                rows = await self.cli.run("voicevibe", "linkedin-post", flags={"send": True},
                                          positionals=(args["text"],), timeout=180)
            else:
                rows = await self.cli.run("instagram", "post", flags={"media": ",".join(args["media"])},
                                          positionals=(args["text"],), timeout=360)
        except OpenCLIError as exc:
            if exc.kind == "timeout":
                text = (f"{site} didn't confirm the post in time. It may already be live, so I'm not "
                        "retrying. Check your profile and tell me what to do.")
            else:
                text = f"The {site} post stopped: {exc.spoken}. I didn't retry. Check Edge, then tell me what to do."
            return Result(ok=False, text=text, data={"error": str(exc), "kind": exc.kind})
        row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
        url = str(row.get("url") or "")
        self._record(plan.action, args["text"], url)
        return Result(ok=True, text=f"Posted to {site}.", data={"url": url, "text": args["text"]})

    def _record(self, action: str, text: str, url: str) -> None:
        store = self.services.get("store")
        add = getattr(store, "add_watch_item", None)
        if add is None:
            return
        source = "linkedin" if action == "linkedin_post" else "instagram"
        try:
            key = url or f"{action}:{hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]}"
            add(source=source, kind="post", key=key, title=text[:120], url=url,
                data={"by": "voicevibe"})
        except Exception:  # noqa: BLE001 - reporting must never undo a successful post
            pass

    # --------------------------------------------------------- read replies

    @staticmethod
    def _say_feed(rows: Any) -> Result:
        rows = rows if isinstance(rows, list) else []
        if not rows:
            return Result(ok=True, text="Your LinkedIn feed is empty right now.")
        bits = [f"{r.get('author') or 'Someone'}: {untrusted.clean(str(r.get('text') or ''), 140)}" for r in rows[:3]]
        return Result(ok=True, text="Top of your LinkedIn feed. " + " … ".join(bits), data={"rows": rows})

    @staticmethod
    def _say_inbox(rows: Any) -> Result:
        rows = rows if isinstance(rows, list) else []
        unread = [r for r in rows if r.get("unread")]
        if not unread:
            return Result(ok=True, text="No unread LinkedIn messages.", data={"rows": rows})
        names = ", ".join(str(r.get("person_name") or "someone") for r in unread[:5])
        return Result(ok=True, text=f"{len(unread)} unread LinkedIn conversation(s): {names}.", data={"rows": rows})

    def _say_instagram(self, rows: Any) -> Result:
        rows = rows if isinstance(rows, list) else []
        fresh = [r for r in rows if r.get("unread")]
        store = self.services.get("store")
        add = getattr(store, "add_watch_item", None)
        for r in rows:
            if add is not None and "comment" in str(r.get("text", "")).lower():
                try:
                    add(source="instagram", kind="comment", key=str(r.get("key") or r.get("text")),
                        title=untrusted.clean(str(r.get("text") or ""), 200), data={"user": r.get("user")})
                except Exception:  # noqa: BLE001
                    pass
        if not fresh:
            return Result(ok=True, text="No new Instagram notifications.", data={"rows": rows})
        bits = [untrusted.clean(str(r.get("text") or ""), 100) for r in fresh[:3]]
        return Result(ok=True, text=f"{len(fresh)} new on Instagram. " + " … ".join(bits), data={"rows": rows})


SKILL = SocialSkill()
