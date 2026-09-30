"""What the user is working on, for the broker: coding sessions + git, read locally.

Claude Code and Codex already log every session as JSONL:
- Claude Code: ~/.claude/projects/<folder>/<session>.jsonl, records with
  `type` user/assistant, `cwd`, `gitBranch`, `message.content` (text or
  blocks), plus a `custom-title` record;
- Codex: ~/.codex/sessions/YYYY/MM/DD/*.jsonl, `session_meta.payload.cwd`
  and `response_item` messages with input_text / output_text blocks.
The newest sessions (active in the last 12 h) give the project folder,
branch, title and the last few prompts and replies: what you did, what the
agent said it would do next. Tool output and side chains are skipped. Git
adds the branch, how many files changed and the last commit subjects
(argument lists, 2 s limit, read-only). Text is capped and cached for 20 s.
The broker sends it to Gemini fenced as untrusted data; VVHUB_BROKER_WORKLOG=0
leaves it out.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

MAX_AGE = 12 * 3600
TAIL_BYTES = 768 * 1024
TURNS = 4
CACHE_SECONDS = 20.0

_lock = threading.Lock()
_cache: dict[str, tuple[float, str]] = {}


@dataclass
class Session:
    agent: str
    path: Path
    mtime: float
    cwd: str = ""
    branch: str = ""
    title: str = ""
    turns: list[tuple[str, str]] = field(default_factory=list)


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _tail_records(path: Path) -> list[dict]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - TAIL_BYTES))
            raw = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = raw.splitlines()
    if size > TAIL_BYTES:
        lines = lines[1:]
    out = []
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _texts(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text", "")) for b in content
                         if isinstance(b, dict) and b.get("type") in ("text", "input_text", "output_text"))
    return ""


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


def _claude(path: Path, mtime: float) -> Session:
    s = Session("Claude Code", path, mtime)
    turns: list[tuple[str, str]] = []
    for rec in _tail_records(path):
        kind = rec.get("type")
        if kind == "custom-title" and rec.get("customTitle"):
            s.title = str(rec["customTitle"])
        if kind not in ("user", "assistant") or rec.get("isSidechain"):
            continue
        s.cwd = str(rec.get("cwd") or s.cwd)
        s.branch = str(rec.get("gitBranch") or s.branch)
        text = _texts((rec.get("message") or {}).get("content"))
        if text.strip():
            turns.append(("you" if kind == "user" else "agent", _clip(text, 300 if kind == "user" else 500)))
    s.turns = turns[-TURNS:]
    return s


def _codex(path: Path, mtime: float) -> Session:
    s = Session("Codex", path, mtime)
    turns: list[tuple[str, str]] = []
    for rec in _tail_records(path):
        payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
        if rec.get("type") == "session_meta":
            s.cwd = str(payload.get("cwd") or s.cwd)
        elif rec.get("type") == "turn_context" and payload.get("cwd"):
            s.cwd = str(payload["cwd"])
        elif rec.get("type") == "response_item" and payload.get("type") == "message":
            role = payload.get("role")
            text = _texts(payload.get("content"))
            if role in ("user", "assistant") and text.strip() and not text.lstrip().startswith("<"):
                turns.append(("you" if role == "user" else "agent", _clip(text, 300 if role == "user" else 500)))
    s.turns = turns[-TURNS:]
    return s


def latest_sessions(home: Path | None = None, limit: int = 2, max_age: float = MAX_AGE) -> list[Session]:
    home = Path(home) if home else Path.home()
    now = time.time()
    found: list[tuple[float, str, Path]] = []
    for agent, root in (("claude", home / ".claude" / "projects"), ("codex", home / ".codex" / "sessions")):
        if not root.is_dir():
            continue
        for path in root.rglob("*.jsonl"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if now - mtime <= max_age:
                found.append((mtime, agent, path))
    sessions = []
    for mtime, agent, path in sorted(found, reverse=True)[:limit]:
        s = _claude(path, mtime) if agent == "claude" else _codex(path, mtime)
        if s.turns or s.cwd:
            sessions.append(s)
    return sessions


def _run_git(argv: list[str], cwd: str, timeout: float) -> str:
    done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, encoding="utf-8",
                          errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return done.stdout if done.returncode == 0 else ""


def git_state(cwd: str, git: Callable[[list[str], str, float], str] = _run_git) -> str:
    if not cwd or not Path(cwd).is_dir():
        return ""
    try:
        branch = git(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd, 2.0).strip()
        if not branch:
            return ""
        changed = len([ln for ln in git(["git", "status", "--porcelain"], cwd, 2.0).splitlines() if ln.strip()])
        commits = [c for c in git(["git", "log", "-3", "--format=%s"], cwd, 2.0).splitlines() if c.strip()]
    except Exception:  # noqa: BLE001 - no git / not a repo / slow disk: skip
        return ""
    line = f"git: branch {branch}, {changed} changed file{'s' * (changed != 1)}"
    if commits:
        line += "; recent commits: " + " | ".join(_clip(c, 80) for c in commits)
    return line


def work_context(home: Path | None = None, git: Callable[[list[str], str, float], str] = _run_git,
                 limit: int = 4000) -> str:
    key = str(home or "")
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
    blocks = []
    for s in latest_sessions(home):
        age = int((time.time() - s.mtime) / 60)
        head = f"{s.agent} session" + (f" \"{s.title}\"" if s.title else "") + \
            (f" in {s.cwd}" if s.cwd else "") + (f" (branch {s.branch})" if s.branch else "") + \
            f", active {age} min ago"
        lines = [head]
        state = git_state(s.cwd, git)
        if state:
            lines.append(state)
        lines += [f"{who}: {text}" for who, text in s.turns]
        blocks.append("\n".join(lines))
    text = "\n\n".join(blocks)
    if len(text) > limit:
        text = text[:limit - 2].rsplit(" ", 1)[0] + " …"
    with _lock:
        _cache[key] = (time.monotonic(), text)
    return text


def enabled() -> bool:
    return os.environ.get("VVHUB_BROKER_WORKLOG", "1").strip() not in ("0", "false", "off")
