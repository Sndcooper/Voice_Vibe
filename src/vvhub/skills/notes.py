"""Notes skill: Notion pages for notes, transcripts, research and reports (T10).

Built on notion-sdk-py (ramnes/notion-sdk-py, MIT) and Notion's own Markdown
API (`POST /v1/pages {markdown}`, `PATCH /v1/pages/{id}/markdown`, API version
2026-03-11) — Notion now converts Markdown to blocks itself, so no
md->blocks converter is vendored. We still chunk: at most ~12k characters per
request (Notion rejects over-large Markdown) and no line over 1900 characters
(the 2000-character rich-text limit).

Layout, found or created under one page the user shares with the
integration (default title "Voice Vibe"):
    Voice Vibe / Notes / <topic pages>
               / Transcripts / Research / Reports

The integration token lives in Windows Credential Manager (`notion_token`,
service `voicevibe`, rule 18). Set it with:
    ..\\venvs\\voicevibe\\Scripts\\python.exe -m vvhub.skills.notes setup
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import sys
from pathlib import Path
from typing import Any

from ..browser import untrusted
from ..browser.services import Services, call, field, is_llm_unavailable
from ..schemas import Plan, Result
from .base import Skill

NOTION_VERSION = "2026-03-11"
TOKEN_KEY = "notion_token"
ROOT_TITLE = "Voice Vibe"
SECTIONS = ("Notes", "Transcripts", "Research", "Reports")
MAX_CHUNK = 12000
MAX_LINE = 1900
MIN_TOPIC_SCORE = 0.5
MAX_TOPICS = 15


class NotesError(RuntimeError):
    """Something the user must fix (spoken as-is)."""


def chunk_markdown(markdown: str, max_chars: int = MAX_CHUNK, max_line: int = MAX_LINE) -> list[str]:
    """Split Markdown at blank lines into request-sized chunks; break any
    over-long line at a sentence or word boundary. Fenced code stays whole
    unless it alone exceeds the limit."""
    lines: list[str] = []
    for line in (markdown or "").replace("\r\n", "\n").split("\n"):
        while len(line) > max_line:
            cut = max(line.rfind(". ", 0, max_line), line.rfind(" ", 0, max_line))
            cut = cut + 1 if cut > max_line // 2 else max_line
            lines.append(line[:cut].rstrip())
            line = line[cut:].lstrip()
        lines.append(line)
    blocks, current, in_code = [], [], False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_code = not in_code
        current.append(line)
        if not line.strip() and not in_code:
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    chunks, buf = [], ""
    for block in blocks:
        if buf and len(buf) + len(block) + 1 > max_chars:
            chunks.append(buf.strip("\n"))
            buf = ""
        while len(block) > max_chars:
            cut = block.rfind("\n", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            chunks.append(block[:cut].strip("\n"))
            block = block[cut:]
        buf = f"{buf}\n{block}" if buf else block
    if buf.strip():
        chunks.append(buf.strip("\n"))
    return [c for c in chunks if c.strip()]


def _title_of(page: dict) -> str:
    if page.get("type") == "child_page":
        return str((page.get("child_page") or {}).get("title") or "")
    for prop in (page.get("properties") or {}).values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return "".join(t.get("plain_text") or (t.get("text") or {}).get("content", "")
                           for t in prop.get("title") or [])
    return ""


def _title_property(title: str) -> dict:
    return {"title": {"title": [{"text": {"content": title[:200]}}]}}


class NotionNotes:
    """The Notion side, shared with research (WS3) and reports (WS4)."""

    def __init__(self, client: Any = None, secrets: Any = None, cache_path: Path | None = None) -> None:
        self._client = client
        self._secrets = secrets
        self._cache_path = cache_path
        self._layout: dict[str, str] | None = None

    @property
    def secrets(self) -> Any:
        if self._secrets is None:
            from .. import secrets as module

            self._secrets = module
        return self._secrets

    @property
    def cache_path(self) -> Path:
        if self._cache_path is None:
            from .. import data_dir

            self._cache_path = data_dir() / "notion.json"
        return self._cache_path

    def configured(self) -> bool:
        return self._client is not None or bool(self.secrets.get(TOKEN_KEY))

    @property
    def client(self) -> Any:
        if self._client is None:
            token = self.secrets.get(TOKEN_KEY)
            if not token:
                raise NotesError("Notion isn't connected yet. Run the notes setup to add your Notion token.")
            from notion_client import AsyncClient

            self._client = AsyncClient(auth=token, notion_version=NOTION_VERSION)
        return self._client

    def _read_cache(self) -> dict:
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write_cache(self, data: dict) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    async def children(self, page_id: str) -> list[tuple[str, str]]:
        """(title, id) of child pages, newest first."""
        found, cursor = [], None
        for _ in range(10):
            query = {"page_size": 100, **({"start_cursor": cursor} if cursor else {})}
            resp = await self.client.request(path=f"blocks/{page_id}/children", method="GET", query=query)
            for block in resp.get("results") or []:
                if block.get("type") == "child_page":
                    found.append((_title_of(block), block["id"]))
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
        return list(reversed(found))

    async def _find_root(self) -> str:
        cache = self._read_cache()
        if cache.get("root"):
            return cache["root"]
        resp = await self.client.request(path="search", method="POST", body={
            "query": ROOT_TITLE, "filter": {"property": "object", "value": "page"}})
        for page in resp.get("results") or []:
            if _title_of(page).strip().lower() == ROOT_TITLE.lower():
                return page["id"]
        raise NotesError(f"I can't see a Notion page called '{ROOT_TITLE}'. Create it and share it with "
                         "the Voice Vibe integration (page menu, Connections).")

    async def layout(self) -> dict[str, str]:
        if self._layout:
            return self._layout
        cache = self._read_cache()
        if cache.get("root") and all(cache.get(s) for s in SECTIONS):
            self._layout = {k: cache[k] for k in ("root", *SECTIONS)}
            return self._layout
        root = await self._find_root()
        existing = {title.lower(): pid for title, pid in await self.children(root)}
        layout = {"root": root}
        for section in SECTIONS:
            layout[section] = existing.get(section.lower()) or (await self.create_page(root, section, ""))["id"]
        self._write_cache(dict(cache, **layout))
        self._layout = layout
        return layout

    async def create_page(self, parent_id: str, title: str, markdown: str) -> dict:
        chunks = chunk_markdown(markdown)
        body: dict[str, Any] = {"parent": {"page_id": parent_id}, "properties": _title_property(title)}
        if chunks:
            body["markdown"] = chunks[0]
        page = await self.client.request(path="pages", method="POST", body=body)
        for chunk in chunks[1:]:
            await self._append_chunk(page["id"], chunk)
        return {"id": page["id"], "url": page.get("url", "")}

    async def append(self, page_id: str, markdown: str) -> None:
        for chunk in chunk_markdown(markdown):
            await self._append_chunk(page_id, chunk)

    async def _append_chunk(self, page_id: str, chunk: str) -> None:
        await self.client.request(path=f"pages/{page_id}/markdown", method="PATCH", body={
            "type": "insert_content", "insert_content": {"content": chunk, "position": {"type": "end"}}})

    async def add_to_section(self, section: str, title: str, markdown: str) -> dict:
        layout = await self.layout()
        return await self.create_page(layout[section], title, markdown)


def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def screen_text(context: dict) -> tuple[str, str]:
    """(text, where) the user is pointing at: selection > caret > region OCR >
    page text. Nothing from a redacted (private) window."""
    ctx = context or {}
    if ctx.get("redacted"):
        return "", ""
    where = str((ctx.get("browser") or {}).get("title") or (ctx.get("window") or {}).get("title") or "")
    for text in (ctx.get("selection"), ctx.get("caret_text"), (ctx.get("region") or {}).get("ocr_text"),
                 (ctx.get("browser") or {}).get("dom_text")):
        if text and str(text).strip():
            return str(text).strip(), where
    return "", where


class NotesSkill(Skill):
    name = "notes"
    category = "notes"
    actions = {
        "note_this": "save what I selected, what's on screen, or what I say as a note in Notion",
        "make_notes": "write organised notes about a topic into Notion",
        "save_transcript": "save this conversation's transcript to Notion",
    }
    critical_actions: set[str] = set()

    def __init__(self, notion: NotionNotes | None = None, services: Services | None = None) -> None:
        super().__init__()
        self._notion = notion
        self._services = services

    @property
    def notion(self) -> NotionNotes:
        if self._notion is None:
            self._notion = NotionNotes()
        return self._notion

    @property
    def services(self) -> Services:
        return self._services or Services(self.hub)

    async def plan(self, decision: Any, context: dict) -> Plan:
        action = field(decision, "action", "") or "note_this"
        target = str(field(decision, "target", "") or "").strip()
        material, where = screen_text(context)
        args = {"target": target, "material": material[:20000], "where": where}
        previews = {"note_this": "Save a note to Notion", "make_notes": f"Write notes about {target or 'this'}",
                    "save_transcript": "Save this conversation to Notion"}
        return Plan(skill=self.name, action=action, args=args, preview=previews.get(action, action),
                    critical=bool(field(decision, "critical", False)))

    async def run(self, plan: Plan, approval: Any = None, dry_run: bool = False) -> Result:
        if dry_run:
            return Result(ok=True, text=f"Would {plan.preview.lower()}.", speak=False)
        if not self.notion.configured():
            return Result(ok=False, text="Notion isn't connected yet. Run the notes setup to add your token.")
        try:
            if plan.action == "note_this":
                return await self._note_this(plan.args)
            if plan.action == "make_notes":
                return await self._make_notes(plan.args)
            if plan.action == "save_transcript":
                return await self._save_transcript()
        except NotesError as exc:
            return Result(ok=False, text=str(exc))
        except Exception as exc:  # noqa: BLE001 - notion_client API/HTTP errors
            if type(exc).__name__ in {"APIResponseError", "HTTPResponseError", "RequestTimeoutError"}:
                return Result(ok=False, text=f"Notion said no: {exc}")
            raise
        return Result(ok=False, text="I can't do that with notes yet.")

    # ---------------------------------------------------------- note_this

    async def _note_this(self, args: dict) -> Result:
        spoken = re.sub(r"^(that|this)\b[:,]?\s*", "", args.get("target") or "", flags=re.I).strip()
        body = args.get("material") or spoken
        if not body:
            return Result(ok=False, text="There's nothing to note: select some text or say the note.")
        entry = f"### {_now()}\n\n{body}\n"
        if args.get("material") and spoken:
            entry = f"### {_now()} — {spoken}\n\n{body}\n"
        if args.get("where"):
            entry += f"\n*From: {args['where']}*\n"
        title, page_id = await self._pick_topic(body, hint=spoken)
        await self.notion.append(page_id, entry)
        return Result(ok=True, text=f"Noted under {title}.", data={"page_id": page_id, "topic": title})

    async def _pick_topic(self, text: str, hint: str = "") -> tuple[str, str]:
        """Laya picks the topic page among existing ones; else a new page."""
        layout = await self.notion.layout()
        topics = (await self.notion.children(layout["Notes"]))[:MAX_TOPICS]
        for title, pid in topics:
            if hint and title.strip().lower() == hint.strip().lower():
                return title, pid
        laya = self.services.get("laya")
        score_fn = getattr(laya, "score", None)
        if topics and score_fn is not None:
            state = untrusted.clean(f"{hint}\n{text}", 1500)
            best, best_score = None, 0.0
            for title, pid in topics:
                try:
                    value = float(await call(score_fn, state, f"Does this note belong on the page titled '{title}'?",
                                             "topic match"))
                except Exception:  # noqa: BLE001
                    continue
                if value > best_score:
                    best, best_score = (title, pid), value
            if best and best_score >= MIN_TOPIC_SCORE:
                return best
        title = await self._new_title(text, hint)
        page = await self.notion.create_page(layout["Notes"], title, "")
        return title, page["id"]

    async def _new_title(self, text: str, hint: str) -> str:
        if hint and len(hint.split()) <= 8:
            return hint[:1].upper() + hint[1:]
        llm = self.services.get("llm")
        if llm is not None:
            try:
                raw = await llm.complete([
                    {"role": "system", "content": "Reply with only a 2-5 word topic title. " + untrusted.DATA_ONLY},
                    {"role": "user", "content": untrusted.fence(text, "note", 2000)}], max_tokens=20)
                title = untrusted.clean(str(raw), 60).strip(" .\"'#")
                if title:
                    return title
            except Exception:  # noqa: BLE001 - fall back to the words themselves
                pass
        words = re.findall(r"\w+", text)[:5]
        return " ".join(words).capitalize() or "Notes"

    # --------------------------------------------------------- make_notes

    async def _make_notes(self, args: dict) -> Result:
        topic = re.sub(r"^(about|on)\s+", "", args.get("target") or "", flags=re.I).strip() or "this"
        material = args.get("material") or ""
        llm = self.services.get("llm")
        notes, degraded = "", False
        if llm is not None:
            prompt = f"Write concise, well-structured Markdown study notes about: {topic}."
            if material:
                prompt += " Base them on this material:\n\n" + untrusted.fence(material, args.get("where"), 12000)
            try:
                notes = str(await llm.complete([{"role": "system", "content": untrusted.DATA_ONLY},
                                                {"role": "user", "content": prompt}], max_tokens=1500))
            except Exception as exc:  # noqa: BLE001
                if not is_llm_unavailable(exc):
                    raise
                degraded = True
        else:
            degraded = True
        if not notes.strip():
            if not material:
                return Result(ok=False, text="The writing service is busy and there's nothing selected to save.")
            notes = material
        entry = f"## {topic} — {_now()}\n\n{untrusted.clean(notes)}\n"
        if args.get("where"):
            entry += f"\n*Source: {args['where']}*\n"
        title, page_id = await self._pick_topic(notes, hint=topic)
        await self.notion.append(page_id, entry)
        text = f"Notes on {topic} saved under {title}."
        if degraded:
            text += " The writing service was busy, so I saved the raw text."
        return Result(ok=True, text=text, data={"page_id": page_id, "topic": title})

    # ---------------------------------------------------- save_transcript

    async def _save_transcript(self) -> Result:
        store = self.services.get("store")
        turns_fn = getattr(store, "turns", None)
        if turns_fn is None:
            return Result(ok=False, text="I don't have this conversation's history.")
        try:
            from ..store import today_conversation

            conversation = today_conversation()
        except Exception:  # noqa: BLE001
            conversation = None
        turns = turns_fn(conversation) if conversation else []
        if not turns:
            return Result(ok=False, text="There's nothing in this conversation yet.")
        lines = []
        for turn in turns:
            ts = turn.get("ts")
            when = _dt.datetime.fromtimestamp(ts).strftime("%H:%M") if isinstance(ts, (int, float)) else ""
            who = "Me" if turn.get("role") == "user" else "Computer"
            lines.append(f"**{who}** {when}: {turn.get('text', '')}")
        title = f"Conversation {_now()}"
        page = await self.notion.add_to_section("Transcripts", title, "\n\n".join(lines))
        return Result(ok=True, text="Transcript saved to Notion.", data={"page_id": page["id"], "url": page["url"]})


def setup(argv: list[str]) -> int:
    """Store the Notion token in Credential Manager and check the layout."""
    import asyncio
    import getpass

    from .. import secrets

    token = getpass.getpass("Notion integration token (input hidden): ").strip()
    if not token:
        print("No token given; nothing changed.")
        return 1
    secrets.set(TOKEN_KEY, token)
    print("Token saved to Windows Credential Manager (service 'voicevibe').")
    try:
        layout = asyncio.run(NotionNotes().layout())
    except NotesError as exc:
        print(exc)
        return 2
    print("Notion layout ready:", ", ".join(f"{k}={v}" for k, v in layout.items()))
    return 0


SKILL = NotesSkill()

if __name__ == "__main__":
    if sys.argv[1:2] == ["setup"]:
        raise SystemExit(setup(sys.argv[2:]))
    print("usage: python -m vvhub.skills.notes setup")
