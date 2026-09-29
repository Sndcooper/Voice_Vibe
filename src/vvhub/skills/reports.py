"""Twice-daily reports (TASK.md rule 16): HTML + Notion + Telegram + spoken.

Structure follows OpenJarvis `agents/morning_digest.py` (Apache-2.0,
open-jarvis/OpenJarvis @ 5e5f5ef): collect already-stored data per configured
section, omit empty sections silently, then deliver one artifact per channel.
Unlike morning_digest there is no LLM step: the summary is built from counts
and titles, so it can only state facts from the data (and rule 9 keeps the LLM
away from anything that isn't drafting).

Sections: new repos, pull requests, new comments (GitHub / Instagram /
LinkedIn watch items), posts, research, Laya auto-decisions, pending
approvals. Ordinary commits are never reported.

Channels, each independent (rule 19):
- HTML (Jinja2, autoescaped, http(s) links only) -> %LOCALAPPDATA%\\VoiceVibe\\reports\\
- Notion through WS3's notes skill: `await notes.save_report(title, markdown)`
  (or its `run()` with action "save_report") -> page URL
- Telegram: `notify` to the bot
- spoken: stored, and read out by `take_spoken()` on the next arm / "read my report"
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import data_dir, protocol
from ..schemas import Plan, Result
from .base import Skill

log = logging.getLogger(__name__)

SECTIONS = (
    ("repos", "New repos"),
    ("prs", "Pull requests"),
    ("comments", "New comments"),
    ("posts", "Posts"),
    ("research", "Research"),
    ("decisions", "Laya auto-decisions"),
    ("approvals", "Pending approvals"),
)
TITLES = dict(SECTIONS)
MAX_ITEMS = 50

# (section, spoken singular, spoken plural)
_SPOKEN = {
    "repos": ("1 new repo", "{n} new repos"),
    "prs": ("1 pull request", "{n} pull requests"),
    "comments": ("1 new comment", "{n} new comments"),
    "posts": ("1 post", "{n} posts"),
    "research": ("1 research digest", "{n} research digests"),
    "decisions": ("1 thing I did for you", "{n} things I did for you"),
    "approvals": ("1 approval waiting", "{n} approvals waiting"),
}


def reports_dir() -> Path:
    return data_dir() / "reports"


def section_for(kind: str) -> str | None:
    """Watch-item kind -> report section; None = not reported (e.g. commits)."""
    k = (kind or "").lower()
    if "commit" in k:
        return None
    if k.endswith("_repo"):
        return "repos"
    if k.endswith("_pr") or k.endswith("_pull_request"):
        return "prs"
    if k.endswith(("_comment", "_mention", "_reply", "_review")):
        return "comments"
    if k.endswith("_post"):
        return "posts"
    if k.startswith("research"):
        return "research"
    return None


def safe_url(url: Any) -> str:
    url = str(url or "").strip()
    return url if re.match(r"^https?://", url, re.IGNORECASE) else ""


def _json(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


@dataclass
class Report:
    slot: datetime
    since: float
    until: float
    sections: dict[str, list[dict]] = field(default_factory=dict)
    delivery: dict[str, str] = field(default_factory=dict)

    @property
    def title(self) -> str:
        part = "Morning" if self.slot.hour < 14 else "Evening"
        return f"{part} report · {self.slot.strftime('%a %d %b %Y')}"

    @property
    def total(self) -> int:
        return sum(len(v) for v in self.sections.values())

    @property
    def stem(self) -> str:
        return self.slot.strftime("%Y-%m-%d-%H%M")


def _item(title: str, url: str = "", detail: str = "", ts: float = 0.0) -> dict:
    return {"title": str(title or "(untitled)")[:300], "url": safe_url(url), "detail": str(detail or "")[:300],
            "ts": ts}


def collect(store: Any, since: float, until: float, slot: datetime | None = None) -> Report:
    slot = slot or datetime.fromtimestamp(until).astimezone()
    report = Report(slot=slot, since=since, until=until)
    out: dict[str, list[dict]] = {key: [] for key, _ in SECTIONS}

    for row in store.list_watch_items(since):
        if row["ts"] > until:
            continue
        section = section_for(row["kind"])
        if section is None:
            continue
        data = _json(row.get("data"))
        detail = row.get("source", "")
        if data.get("author"):
            detail += f" · by {data['author']}"
        out[section].append(_item(row.get("title"), row.get("url"), detail, row["ts"]))

    for job in store.jobs():
        if job.get("kind") != "research" or job.get("status") not in ("done", "ok", "finished"):
            continue
        if not since <= job.get("updated", 0) <= until:
            continue
        result = _json(job.get("result"))
        out["research"].append(_item(result.get("title") or job.get("progress") or "Research",
                                     result.get("url"), "research", job["updated"]))

    for row in store.decisions(since):
        if row["ts"] > until:
            continue
        d = _json(row.get("decision"))
        if d.get("needs_approval") or d.get("critical") or d.get("category") in (None, "", "chitchat"):
            continue
        what = " ".join(p for p in (d.get("category"), d.get("action"), d.get("target")) if p)
        conf = d.get("confidence")
        detail = what + (f" · {round(float(conf) * 100)}% sure" if isinstance(conf, (int, float)) else "")
        out["decisions"].append(_item(f"\u201c{row.get('request', '')}\u201d", "", detail, row["ts"]))

    for row in store.approvals("pending"):
        out["approvals"].append(_item(row.get("preview") or row.get("action"), "",
                                      f"{row.get('action', '')} · via {row.get('channel', '')}",
                                      row.get("created", 0)))

    report.sections = {k: v[:MAX_ITEMS] for k, v in out.items() if v}
    return report


# ---- renderers ------------------------------------------------------------------
def spoken_summary(report: Report) -> str:
    head = report.title.split(" · ")[0]
    if not report.sections:
        return f"{head}: nothing new."
    parts = []
    for key, _ in SECTIONS:
        n = len(report.sections.get(key, []))
        if n:
            one, many = _SPOKEN[key]
            parts.append(one if n == 1 else many.format(n=n))
    text = ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]
    return f"{head}: {text}."


def telegram_text(report: Report, per_section: int = 5) -> str:
    lines = [f"📋 {report.title}", ""]
    if not report.sections:
        lines.append("Nothing new.")
    for key, label in SECTIONS:
        items = report.sections.get(key)
        if not items:
            continue
        lines.append(f"{label} ({len(items)})")
        for item in items[:per_section]:
            lines.append(f"• {item['title']}" + (f"\n  {item['url']}" if item["url"] else ""))
        if len(items) > per_section:
            lines.append(f"  …and {len(items) - per_section} more")
        lines.append("")
    if report.delivery.get("html"):
        lines.append(f"Full report on the PC: {Path(report.delivery['html']).name}")
    return "\n".join(lines).strip()[:4000]


_MD_SPECIAL = re.compile(r"([\\`*_\[\]()])")  # link/emphasis syntax; '#' only matters at line start


def _md(text: str) -> str:
    return _MD_SPECIAL.sub(r"\\\1", text)


def render_markdown(report: Report) -> str:
    lines = [f"# {report.title}", ""]
    if not report.sections:
        lines.append("Nothing new.")
    for key, label in SECTIONS:
        items = report.sections.get(key)
        if not items:
            continue
        lines += [f"## {label}", ""]
        for item in items:
            title = _md(item["title"])
            entry = f"[{title}]({item['url']})" if item["url"] else title
            lines.append(f"- {entry}" + (f" — {_md(item['detail'])}" if item["detail"] else ""))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ report.title }}</title>
<style>
 body { font: 16px/1.5 system-ui, "Segoe UI", sans-serif; max-width: 46rem; margin: 2rem auto; padding: 0 1rem;
        color: #1b1b1b; background: #fff; }
 h1 { font-size: 1.6rem; } h2 { font-size: 1.2rem; margin-top: 2rem; border-bottom: 1px solid #ccc; }
 li { margin: .4rem 0; } .detail { color: #555; font-size: .9rem; } a { color: #0b57d0; }
 a:focus { outline: 3px solid #0b57d0; outline-offset: 2px; }
 footer { margin-top: 3rem; color: #555; font-size: .85rem; }
 @media (prefers-color-scheme: dark) { body { background: #121212; color: #e8e8e8; }
   .detail, footer { color: #b0b0b0; } a { color: #8ab4f8; } a:focus { outline-color: #8ab4f8; } }
</style>
</head>
<body>
<main>
<h1>{{ report.title }}</h1>
<p>{{ summary }}</p>
{% for key, label in sections %}{% set items = report.sections.get(key) %}{% if items %}
<section aria-labelledby="s-{{ key }}">
<h2 id="s-{{ key }}">{{ label }}</h2>
<ul>
{% for item in items %}  <li>{% if item.url %}<a href="{{ item.url }}" rel="noopener noreferrer">{{ item.title }}</a>{% else %}{{ item.title }}{% endif %}{% if item.detail %} <span class="detail">— {{ item.detail }}</span>{% endif %}</li>
{% endfor %}</ul>
</section>
{% endif %}{% endfor %}
</main>
<footer>Covers {{ since }} to {{ until }}. Generated by Voice Vibe hub.</footer>
</body>
</html>
"""


def render_html(report: Report) -> str:
    from jinja2 import Environment

    env = Environment(autoescape=True)
    return env.from_string(_TEMPLATE).render(
        report=report, sections=SECTIONS, summary=spoken_summary(report),
        since=datetime.fromtimestamp(report.since).astimezone().strftime("%d %b %H:%M"),
        until=datetime.fromtimestamp(report.until).astimezone().strftime("%d %b %H:%M"))


# ---- spoken-on-next-arm state ----------------------------------------------------
def _speech_path(out_dir: Path) -> Path:
    return Path(out_dir) / "spoken.json"


def save_spoken(out_dir: Path, text: str) -> None:
    path = _speech_path(out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"latest": text, "unspoken": text, "ts": time.time()}), encoding="utf-8")


def _read_speech(out_dir: Path) -> dict:
    try:
        return json.loads(_speech_path(out_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def take_spoken(out_dir: Path | None = None) -> str | None:
    """The newest report's summary if it hasn't been spoken yet (then marks it spoken).

    For Voice Vibe's next arm: WS0's hub calls this when a session arms and
    speaks the result."""
    out_dir = Path(out_dir) if out_dir else reports_dir()
    state = _read_speech(out_dir)
    text = state.get("unspoken")
    if not text:
        return None
    state["unspoken"] = None
    _speech_path(out_dir).write_text(json.dumps(state), encoding="utf-8")
    return text


def latest_spoken(out_dir: Path | None = None) -> str | None:
    return _read_speech(Path(out_dir) if out_dir else reports_dir()).get("latest")


# ---- delivery -----------------------------------------------------------------------
async def _to_notion(hub: Any, report: Report) -> str:
    notes = (getattr(hub, "skills", None) or {}).get("notes")
    if notes is None:
        return "notes skill not available"
    markdown = render_markdown(report)
    try:
        if hasattr(notes, "save_report"):
            url = await notes.save_report(report.title, markdown)
            return str(url or "saved")
        if "save_report" in getattr(notes, "actions", {}):
            plan = Plan(skill="notes", action="save_report", args={"title": report.title, "markdown": markdown},
                        preview=f"Save {report.title} to Notion")
            result = await notes.run(plan)
            if not result.ok:
                return f"failed: {result.text}"
            return str(result.data.get("url") or "saved")
    except Exception as exc:  # noqa: BLE001
        log.warning("report to Notion failed: %s", exc)
        return f"failed: {exc}"
    return "notes skill has no save_report"


async def _to_telegram(hub: Any, report: Report) -> str:
    bus = getattr(hub, "bus", None)
    if bus is None or not bus.connected("bot"):
        return "bot not connected"
    try:
        sent = await bus.notify("bot", protocol.message("notify", title=report.title, text=telegram_text(report),
                                                        level="info"))
    except Exception as exc:  # noqa: BLE001
        return f"failed: {exc}"
    return "sent" if sent else "bot not connected"


async def make_report(hub: Any, slot: datetime, since: float, now: float | None = None,
                      out_dir: Path | None = None, telegram: bool = True) -> Report:
    now = now or time.time()
    out_dir = Path(out_dir) if out_dir else reports_dir()
    report = collect(hub.store, since, now, slot=slot)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        path = out_dir / f"{report.stem}.html"
        path.write_text(render_html(report), encoding="utf-8")
        report.delivery["html"] = str(path)
    except Exception as exc:  # noqa: BLE001
        log.warning("HTML report failed: %s", exc)
        report.delivery["html"] = f"failed: {exc}"
    report.delivery["notion"] = await _to_notion(hub, report)
    report.delivery["telegram"] = await _to_telegram(hub, report) if telegram else "skipped"
    save_spoken(out_dir, spoken_summary(report))
    log.info("%s: %d items, %s", report.title, report.total, report.delivery)
    return report


class ReportsSkill(Skill):
    name = "reports"
    category = "notes"
    actions = {
        "read_report": "read out the latest morning/evening report",
        "report_now": "make a report of everything new right now",
    }
    critical_actions: set[str] = set()
    phrases = {"read my report": "read_report", "what did i miss": "read_report",
               "report now": "report_now", "make a report": "report_now"}

    def __init__(self, out_dir: Path | None = None) -> None:
        super().__init__()
        self.out_dir = out_dir

    async def plan(self, decision: Any, context: Any = None) -> Plan:
        action = getattr(decision, "action", None) or (decision.get("action") if isinstance(decision, dict) else "")
        action = action if action in self.actions else "read_report"
        return Plan(skill=self.name, action=action, args={}, preview=self.actions[action], critical=False)

    async def run(self, plan: Plan, approval: Any = None, dry_run: bool = False) -> Result:
        out_dir = self.out_dir or reports_dir()
        if plan.action == "report_now":
            if dry_run:
                return Result(ok=True, text="Would make a report now.", speak=False)
            if self.hub is None:
                return Result(ok=False, text="The hub isn't running.", speak=True)
            from ..scheduler import report_now

            report = await report_now(self.hub, out_dir=out_dir)
            take_spoken(out_dir)  # being spoken right now
            return Result(ok=True, text=spoken_summary(report), speak=True, data=dict(report.delivery))
        text = latest_spoken(out_dir)
        if not text:
            return Result(ok=True, text="There's no report yet.", speak=True)
        take_spoken(out_dir)
        return Result(ok=True, text=text, speak=True)


SKILL = ReportsSkill()
