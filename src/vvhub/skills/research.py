"""Research skill: search, read, filter with Laya, digest, save (T11).

Glue over existing tools:
- search: OpenCLI's built-in `duckduckgo search` (public, runs in Edge);
  URLs the user names are read directly;
- read: trafilatura (adbar/trafilatura, Apache-2.0) first — local, no
  cloud; then Agent-Reach's Jina Reader channel (Panniantong/Agent-Reach,
  MIT); then OpenCLI `web read` for JS-heavy pages rendered in Edge.
  Agent-Reach's `normalize_public_http_url` guards every URL (no
  localhost/private IPs/credentials — scraped links can't reach the LAN);
- relevance: Laya `score` on each result and each page (rule 9);
- digest: FreeLLMAPI text only; sources are fenced as untrusted data;
- output: Notion "Research" page + a local Markdown copy, a watch item for
  the 08:00/20:00 reports, and a spoken summary.

Prompt-injection safety (rule 11): nothing a page or the LLM says can cause
an action. The job has no access to approvals, posting or messaging; it only
reads, writes text files/Notion pages the user asked for, and speaks.

Runs as a background job so the 20 s request timeout never bites; "computer
what did you find" speaks the latest summary.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..browser import OpenCLI, OpenCLIError, untrusted
from ..browser.services import Services, call, field, is_llm_unavailable
from ..schemas import Plan, Result
from .base import Skill

log = logging.getLogger(__name__)

MAX_RESULTS = 8
MAX_SOURCES = 4
MIN_RESULT_SCORE = 0.3
MIN_PAGE_SCORE = 0.4
PAGE_CHARS = 12000
MIN_USEFUL = 400
_URL = re.compile(r"https?://[^\s<>\"']+")

Reader = Callable[[str], Awaitable[str]]


def public_url(url: str) -> str:
    """Agent-Reach's SSRF guard; raises ValueError for non-public targets."""
    try:
        from agent_reach.utils.url import normalize_public_http_url
    except Exception:  # noqa: BLE001 - Agent-Reach missing: stricter local check
        from ..browser import BrowserError, safe_url

        try:
            url = safe_url(url)
        except BrowserError as exc:
            raise ValueError(str(exc)) from None
        host = re.sub(r"^https?://", "", url).split("/")[0].split(":")[0].lower()
        if host in ("localhost",) or re.fullmatch(r"[\d.]+", host) or "." not in host:
            raise ValueError("only public HTTP(S) URLs are allowed")
        return url
    return normalize_public_http_url(url)


async def trafilatura_read(url: str) -> str:
    import trafilatura

    def _go() -> str:
        html = trafilatura.fetch_url(url)
        if not html:
            return ""
        return trafilatura.extract(html, url=url, include_comments=False, include_links=False,
                                   output_format="markdown") or ""

    return await asyncio.to_thread(_go)


async def jina_read(url: str) -> str:
    from agent_reach.channels.web import WebChannel

    return await asyncio.to_thread(WebChannel().read, url)


class Fetcher:
    """Reads one URL: trafilatura -> Jina (Agent-Reach) -> OpenCLI web read."""

    def __init__(self, cli: OpenCLI | None = None, local: Reader | None = None,
                 jina: Reader | None = None) -> None:
        self.cli = cli or OpenCLI()
        self.readers: list[tuple[str, Reader]] = [
            ("trafilatura", local or trafilatura_read),
            ("jina", jina or jina_read),
            ("opencli", self._opencli_read),
        ]

    async def _opencli_read(self, url: str) -> str:
        out = await self.cli.run("web", "read", flags={"url": url, "stdout": True, "download-images": "false"},
                                 fmt=None, timeout=90)
        return out if isinstance(out, str) else str(out or "")

    async def read(self, url: str) -> tuple[str, str]:
        url = public_url(url)
        best, backend = "", ""
        for name, reader in self.readers:
            try:
                text = (await reader(url) or "").strip()
            except (OpenCLIError, Exception) as exc:  # noqa: BLE001 - any reader may fail; try the next
                log.debug("%s failed on %s: %s", name, url, exc)
                continue
            if len(text) > len(best):
                best, backend = text, name
            if len(best) >= MIN_USEFUL:
                break
        return best[:PAGE_CHARS], backend


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "research"


def split_summary(digest: str) -> tuple[str, str]:
    """'SUMMARY: ...' first line -> (spoken summary, rest)."""
    lines = digest.strip().splitlines()
    if lines and lines[0].upper().startswith("SUMMARY:"):
        return lines[0].split(":", 1)[1].strip(), "\n".join(lines[1:]).strip()
    first = re.split(r"(?<=[.!?])\s+", re.sub(r"[#*_>`-]", "", digest).strip())
    return " ".join(first[:2])[:400], digest.strip()


class ResearchSkill(Skill):
    name = "research"
    category = "research"
    actions = {
        "research": "research a topic on the web in the background and save a digest to Notion",
        "research_status": "tell me what the last research found",
    }
    critical_actions: set[str] = set()

    def __init__(self, cli: OpenCLI | None = None, fetcher: Fetcher | None = None,
                 services: Services | None = None, notion: Any = None, out_dir: Path | None = None) -> None:
        super().__init__()
        self._cli = cli
        self._fetcher = fetcher
        self._services = services
        self._notion = notion
        self._out_dir = out_dir
        self.tasks: set[asyncio.Task] = set()
        self.last: dict | None = None

    @property
    def cli(self) -> OpenCLI:
        if self._cli is None:
            self._cli = OpenCLI()
        return self._cli

    @property
    def fetcher(self) -> Fetcher:
        if self._fetcher is None:
            self._fetcher = Fetcher(cli=self.cli)
        return self._fetcher

    @property
    def services(self) -> Services:
        return self._services or Services(self.hub)

    @property
    def notion(self) -> Any:
        if self._notion is None:
            from .notes import NotionNotes

            self._notion = NotionNotes()
        return self._notion

    @property
    def out_dir(self) -> Path:
        if self._out_dir is None:
            from .. import data_dir

            self._out_dir = data_dir() / "research"
        return self._out_dir

    async def plan(self, decision: Any, context: dict) -> Plan:
        action = field(decision, "action", "") or "research"
        topic = re.sub(r"^(research|look up|find out about|about)\s+", "",
                       str(field(decision, "target", "") or "").strip(), flags=re.I)
        return Plan(skill=self.name, action=action, args={"topic": topic},
                    preview=f"Research {topic}" if action == "research" else "Say the last research summary",
                    critical=bool(field(decision, "critical", False)))

    async def run(self, plan: Plan, approval: Any = None, dry_run: bool = False) -> Result:
        if plan.action == "research_status":
            if self.tasks and not self.last:
                return Result(ok=True, text="Still researching; I'll tell you when it's done.")
            if not self.last:
                return Result(ok=True, text="I haven't researched anything yet.")
            return Result(ok=True, text=self.last["summary"], data=self.last)
        topic = plan.args.get("topic") or ""
        if not topic:
            return Result(ok=False, text="What should I research?")
        if dry_run:
            return Result(ok=True, text=f"Would research {topic}.", speak=False)
        store = self.services.get("store")
        job_id = None
        if store is not None and hasattr(store, "add_job"):
            try:
                job_id = store.add_job("research")
            except Exception:  # noqa: BLE001
                job_id = None
        task = asyncio.create_task(self._job(topic, job_id))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return Result(ok=True, text=f"Researching {topic}. I'll tell you when it's done.", data={"job": job_id})

    async def wait(self) -> None:
        while self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)

    # ------------------------------------------------------------ the job

    async def _job(self, topic: str, job_id: str | None) -> dict:
        store = self.services.get("store")

        def progress(status: str | None = None, note: str | None = None, result: dict | None = None) -> None:
            if job_id and store is not None:
                try:
                    store.update_job(job_id, status=status, progress=note, result=result)
                except Exception:  # noqa: BLE001
                    pass

        progress("running", "searching")
        try:
            outcome = await self.research(topic, progress=lambda note: progress(note=note))
        except Exception as exc:  # noqa: BLE001 - a background job must report, not vanish
            log.exception("research failed")
            outcome = {"ok": False, "topic": topic, "summary": f"Research on {topic} failed: {exc}"}
        progress("done" if outcome.get("ok") else "failed", "finished",
                 {k: outcome.get(k) for k in ("summary", "path", "notion_url", "sources")})
        self.last = outcome
        await self._notify(outcome)
        return outcome

    async def research(self, topic: str, progress: Callable[[str], None] = lambda _n: None) -> dict:
        laya = self.services.get("laya")
        score_fn = getattr(laya, "score", None)
        results = await self._candidates(topic)
        if not results:
            return {"ok": False, "topic": topic,
                    "summary": f"I couldn't find anything to read about {topic}. Is Edge's OpenCLI extension on?"}
        results = await self._filter(score_fn, topic, results, lambda r: f"{r['title']}\n{r.get('snippet', '')}",
                                     MIN_RESULT_SCORE, MAX_SOURCES + 1)
        progress(f"reading {len(results)} pages")
        sem = asyncio.Semaphore(3)

        async def _read(r: dict) -> dict:
            async with sem:
                try:
                    text, backend = await self.fetcher.read(r["url"])
                except ValueError:
                    text, backend = "", ""
            return dict(r, text=text, backend=backend)

        pages = [p for p in await asyncio.gather(*(_read(r) for r in results)) if p["text"]]
        pages = await self._filter(score_fn, topic, pages, lambda p: f"{p['title']}\n{p['text'][:1500]}",
                                   MIN_PAGE_SCORE, MAX_SOURCES)
        if not pages:
            return {"ok": False, "topic": topic, "summary": f"The pages I found about {topic} weren't relevant."}
        progress("writing digest")
        summary, digest, degraded = await self._digest(topic, pages)
        flagged = [i + 1 for i, p in enumerate(pages) if untrusted.suspicious(p["text"])]
        md = self._markdown(topic, digest, pages, flagged)
        path = self._save_local(topic, md)
        notion_url = await self._save_notion(topic, md)
        self._watch(topic, path, notion_url)
        spoken = summary
        if degraded:
            spoken += " The text service was busy, so I saved extracts instead of a digest."
        if flagged:
            spoken += " Some sources contained instructions aimed at AI tools; I ignored them."
        return {"ok": True, "topic": topic, "summary": spoken, "path": str(path), "notion_url": notion_url,
                "sources": [{"title": p["title"], "url": p["url"]} for p in pages], "flagged": flagged}

    async def _candidates(self, topic: str) -> list[dict]:
        urls = _URL.findall(topic)
        if urls:
            return [{"title": u, "url": u, "snippet": ""} for u in urls[:MAX_RESULTS]]
        try:
            rows = await self.cli.run("duckduckgo", "search", positionals=(topic,),
                                      flags={"limit": MAX_RESULTS}, timeout=60)
        except OpenCLIError as exc:
            log.info("search failed: %s", exc)
            return []
        out = []
        for row in rows if isinstance(rows, list) else []:
            url = str(row.get("url") or "")
            if url.startswith("http") and row.get("resultType", "web") in ("web", "", None):
                out.append({"title": untrusted.clean(str(row.get("title") or url), 200), "url": url,
                            "snippet": untrusted.clean(str(row.get("snippet") or ""), 400)})
        return out

    @staticmethod
    async def _filter(score_fn: Any, topic: str, items: list[dict], text_of: Callable[[dict], str],
                      threshold: float, keep: int) -> list[dict]:
        """Laya relevance filter; without Laya keep the search order (degraded)."""
        if score_fn is None:
            return items[:keep]
        scored = []
        for item in items:
            try:
                value = float(await call(score_fn, untrusted.clean(text_of(item), 2000),
                                         f"How relevant is this to the research question: {topic}?",
                                         "relevance"))
            except Exception:  # noqa: BLE001
                value = 0.0
            if value >= threshold:
                scored.append((value, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _v, item in scored[:keep]]

    async def _digest(self, topic: str, pages: list[dict]) -> tuple[str, str, bool]:
        llm = self.services.get("llm")
        sources = "\n\n".join(f"[{i + 1}] {p['title']} ({p['url']})\n" + untrusted.fence(p["text"], p["url"], 6000)
                              for i, p in enumerate(pages))
        prompt = (f"Research question: {topic}\n\nWrite the first line as 'SUMMARY: ' followed by two short "
                  "sentences to be read aloud. Then a Markdown digest: key findings as bullet points, each "
                  "citing sources like [1]; note disagreements; end with open questions.\n\n" + sources)
        if llm is not None:
            try:
                raw = await llm.complete([{"role": "system", "content": untrusted.DATA_ONLY},
                                          {"role": "user", "content": prompt}], max_tokens=1200)
                summary, digest = split_summary(untrusted.clean(str(raw)))
                if digest or summary:
                    return summary, digest, False
            except Exception as exc:  # noqa: BLE001
                if not is_llm_unavailable(exc):
                    raise
        extracts = []
        for i, p in enumerate(pages):
            first = " ".join(re.split(r"(?<=[.!?])\s+", untrusted.clean(p["text"], 1500))[:3])
            extracts.append(f"- [{i + 1}] {first}")
        return f"I found {len(pages)} sources on {topic}.", "\n".join(extracts), True

    @staticmethod
    def _markdown(topic: str, digest: str, pages: list[dict], flagged: list[int]) -> str:
        when = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        parts = [f"# Research: {topic}", f"*{when} · {len(pages)} sources*", "", digest, "", "## Sources"]
        parts += [f"{i + 1}. [{p['title']}]({p['url']}) — via {p.get('backend') or 'web'}"
                  for i, p in enumerate(pages)]
        if flagged:
            parts += ["", "> Warning: source(s) " + ", ".join(map(str, flagged))
                      + " contained instructions aimed at AI tools. They were treated as data and ignored."]
        return "\n".join(parts) + "\n"

    def _save_local(self, topic: str, md: str) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"{_dt.datetime.now():%Y%m%d-%H%M%S}-{_slug(topic)}.md"
        path.write_text(md, encoding="utf-8")
        return path

    async def _save_notion(self, topic: str, md: str) -> str:
        try:
            if not self.notion.configured():
                return ""
            page = await self.notion.add_to_section("Research", f"Research: {topic}"[:180], md)
            return str(page.get("url") or "")
        except Exception as exc:  # noqa: BLE001 - the local copy is already saved
            log.warning("Notion save failed: %s", exc)
            return ""

    def _watch(self, topic: str, path: Path, notion_url: str) -> None:
        store = self.services.get("store")
        add = getattr(store, "add_watch_item", None)
        if add is None:
            return
        try:
            add(source="research", kind="research", key=str(path), title=topic, url=notion_url,
                data={"path": str(path)})
        except Exception:  # noqa: BLE001
            pass

    async def _notify(self, outcome: dict) -> None:
        bus = getattr(self.hub, "bus", None) if self.hub is not None else None
        if bus is None:
            return
        try:
            from .. import protocol

            msg = protocol.message("notify", title=f"Research: {outcome.get('topic', '')}",
                                   text=outcome.get("summary", ""), level="info" if outcome.get("ok") else "warn")
            for role in ("bot", "ui"):
                await bus.notify(role, dict(msg, id=protocol.new_id()))
        except Exception:  # noqa: BLE001
            log.debug("notify failed", exc_info=True)


SKILL = ResearchSkill()
