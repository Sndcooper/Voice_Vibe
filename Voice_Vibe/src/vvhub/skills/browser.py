"""Browser skill: open a site in Edge/Zen, summarize the page on screen.

Glue over `vvhub.browser` (OpenCLI for Edge, Windows-MCP for Zen). The page
text is untrusted: it only ever reaches the LLM fenced (rule 11), and the
summary is spoken, never acted on.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote_plus

from ..browser import Browsers, BrowserError, detect, safe_url, untrusted
from ..browser.services import Services, field, is_llm_unavailable
from ..schemas import Plan, Result
from .base import Skill

SITES = {
    "linkedin": "https://www.linkedin.com/",
    "instagram": "https://www.instagram.com/",
    "github": "https://github.com/",
    "notion": "https://www.notion.so/",
    "youtube": "https://www.youtube.com/",
    "gmail": "https://mail.google.com/",
    "google": "https://www.google.com/",
    "chatgpt": "https://chatgpt.com/",
    "claude": "https://claude.ai/",
}

_BROWSER_WORDS = re.compile(r"\s*\b(in|on|with|using)\s+(zen|edge|microsoft edge)\b\s*", re.I)


def resolve_target(target: str) -> str:
    """Spoken site -> URL: known names, then anything URL-shaped, else a search."""
    text = _BROWSER_WORDS.sub(" ", target or "").strip().strip(".")
    key = re.sub(r"^(the\s+)?", "", text.lower()).replace(" dot com", ".com").strip()
    key = re.sub(r"\s+(website|site|page)$", "", key)
    if key in SITES:
        return SITES[key]
    try:
        return safe_url(key.replace(" ", ""))
    except BrowserError:
        return "https://duckduckgo.com/?q=" + quote_plus(text)


class BrowserSkill(Skill):
    name = "browser"
    category = "app"
    actions = {
        "open_website": "open a website or web address in the user's browser (Edge or Zen)",
        "summarize_page": "read the web page open in the browser and summarize it aloud",
    }
    critical_actions: set[str] = set()

    def __init__(self, browsers: Browsers | None = None, services: Services | None = None) -> None:
        super().__init__()
        self._browsers = browsers
        self._services = services

    @property
    def browsers(self) -> Browsers:
        if self._browsers is None:
            self._browsers = Browsers()
        return self._browsers

    @property
    def services(self) -> Services:
        return self._services or Services(self.hub)

    async def plan(self, decision: Any, context: dict) -> Plan:
        action = field(decision, "action", "") or "summarize_page"
        target = str(field(decision, "target", "") or "")
        browser = detect(context, target, self.browsers.last)
        args: dict[str, Any] = {"browser": browser, "context": context or {}}
        if action == "open_website":
            args["url"] = resolve_target(target)
            preview = f"Open {args['url']} in {browser.title()}"
        else:
            preview = f"Summarize the page in {browser.title()}"
        return Plan(skill=self.name, action=action, args=args, preview=preview,
                    critical=bool(field(decision, "critical", False)))

    async def run(self, plan: Plan, approval: Any = None, dry_run: bool = False) -> Result:
        args = plan.args
        browser = self.browsers.zen if args.get("browser") == "zen" else self.browsers.edge
        self.browsers.last = browser.name
        if dry_run:
            return Result(ok=True, text=f"Would {plan.preview[0].lower()}{plan.preview[1:]}.", speak=False)
        try:
            if plan.action == "open_website":
                await browser.open(args["url"])
                return Result(ok=True, text=f"Opening it in {browser.name.title()}.", data={"url": args["url"]})
            if plan.action == "summarize_page":
                return await self._summarize(browser, args.get("context") or {})
        except BrowserError as exc:
            return Result(ok=False, text=exc.spoken)
        return Result(ok=False, text="I can't do that in the browser yet.")

    async def _summarize(self, browser: Any, context: dict) -> Result:
        if context.get("redacted"):
            return Result(ok=False, text="That window is private, so I won't read it.")
        if browser.name == "zen":
            page = await browser.read_current(max_chars=20000, context=context)
        else:
            page = await browser.read_current(max_chars=20000)
        if not page.get("text", "").strip():
            return Result(ok=False, text="The page looks empty to me.")
        llm = self.services.get("llm")
        if llm is None:
            return Result(ok=False, text="The text service isn't set up yet.")
        messages = [
            {"role": "system", "content": untrusted.DATA_ONLY},
            {"role": "user", "content": "Summarize this web page in at most three short spoken sentences.\n\n"
                                        + untrusted.fence(page["text"], page.get("url") or page.get("title"))},
        ]
        try:
            summary = untrusted.clean(await llm.complete(messages, max_tokens=300), 1200)
        except Exception as exc:  # noqa: BLE001
            if is_llm_unavailable(exc):
                return Result(ok=False, text="The text service is busy right now (the free pool is exhausted).")
            raise
        if untrusted.suspicious(page["text"]):
            summary += " Note: the page contains suspicious instructions; I ignored them."
        return Result(ok=True, text=summary, data={"url": page.get("url"), "title": page.get("title")})


SKILL = BrowserSkill()
