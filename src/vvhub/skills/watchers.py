"""Watchers: poll sources for things worth reporting -> store watch_items.

GitHub (via `gh api`, argument lists only): new repos I own, PRs that involve
me, and new comments/mentions/reviews on issues and PRs (notifications). CI
runs, commit notifications and other noise are skipped (TASK.md rule 16: "not
ordinary commits"). Other streams can add watchers with the same shape: an
object with `name`, `errors` and `async poll(since, store) -> list[dict]`.

Items are written with `store.add_watch_item(source=, kind=, key=, title=,
url=, data=, ts=)` (WS0's Store, UNIQUE(source, key)); `key` is stable per event so re-polls and the
overlap window never duplicate.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .. import data_dir as hub_data_dir
from ..schemas import Plan, Result
from .base import Skill
from .github import subprocess_runner

FIRST_LOOKBACK = timedelta(hours=24)
OVERLAP = timedelta(minutes=5)
NOISE_REASONS = {"ci_activity", "security_alert", "invitation"}
NOISE_TYPES = {"Commit", "CheckSuite", "CheckRun", "Release", "RepositoryVulnerabilityAlert"}


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def html_url(api_url: str | None) -> str:
    """api.github.com/repos/o/r/pulls/7 -> github.com/o/r/pull/7."""
    if not api_url:
        return ""
    url = api_url.replace("https://api.github.com/repos/", "https://github.com/")
    return url.replace("/pulls/", "/pull/")


def _existing_keys(store: Any, since: datetime, kinds: list[str]) -> set[str]:
    try:
        items = store.list_watch_items((since - FIRST_LOOKBACK).timestamp(), kinds) or []
    except Exception:  # noqa: BLE001
        return set()
    keys = set()
    for item in items:
        key = item.get("key") if isinstance(item, dict) else getattr(item, "key", None)
        if key:
            keys.add(key)
    return keys


class GitHubWatcher:
    name = "github"
    kinds = ["github_repo", "github_pr", "github_comment"]

    def __init__(self, runner=None) -> None:
        self.runner = runner or subprocess_runner
        self.errors: list[str] = []

    async def _api(self, *args: str) -> Any:
        argv = ["gh", "api", *args]
        try:
            rc, out, err = await self.runner(argv)
        except FileNotFoundError:
            raise RuntimeError("gh is not installed") from None
        if rc != 0:
            raise RuntimeError(f"{' '.join(argv[:3])}: {(err or out).strip()[:200]}")
        return out

    async def poll(self, since: datetime, store: Any) -> list[dict]:
        self.errors = []
        try:
            login = (await self._api("user", "--jq", ".login")).strip()
        except Exception as exc:  # noqa: BLE001
            self.errors.append(str(exc))
            return []
        found: list[dict] = []
        for fetch in (self._repos, self._prs, self._comments):
            try:
                found.extend(await fetch(since, login))
            except Exception as exc:  # noqa: BLE001 -- one source failing never stops the rest
                self.errors.append(str(exc))
        seen = _existing_keys(store, since, self.kinds)
        new = []
        for item in found:
            if item["key"] in seen:
                continue
            seen.add(item["key"])
            created = parse_time(item.get("created"))
            added = store.add_watch_item(
                source=item["source"], kind=item["kind"], key=item["key"], title=item["title"],
                url=item["url"], data=dict(item["data"], created=item.get("created")),
                ts=created.timestamp() if created else None)
            if added is False:  # the store already had it (UNIQUE(source, key))
                continue
            new.append(item)
        return new

    async def _repos(self, since: datetime, login: str) -> list[dict]:
        repos = json.loads(await self._api(
            "user/repos?affiliation=owner&sort=created&direction=desc&per_page=30") or "[]")
        out = []
        for r in repos:
            created = parse_time(r.get("created_at"))
            if not created or created < since:
                continue
            out.append(dict(kind="github_repo", source="github", key=f"repo:{r.get('full_name')}",
                            title=r.get("full_name", ""), url=r.get("html_url", ""), created=r.get("created_at"),
                            data={"description": r.get("description") or "", "private": bool(r.get("private"))}))
        return out

    async def _prs(self, since: datetime, login: str) -> list[dict]:
        query = f"is:pr involves:{login} created:>={iso(since)}"
        result = json.loads(await self._api("-X", "GET", "search/issues", "-f", f"q={query}",
                                            "-f", "per_page=30") or "{}")
        out = []
        for pr in result.get("items", []):
            repo = (pr.get("repository_url") or "").rsplit("/repos/", 1)[-1]
            out.append(dict(kind="github_pr", source="github", key=f"pr:{pr.get('id')}",
                            title=f"{repo}#{pr.get('number')} {pr.get('title', '')}".strip(),
                            url=pr.get("html_url", ""), created=pr.get("created_at"),
                            data={"author": (pr.get("user") or {}).get("login", ""), "repo": repo,
                                  "state": pr.get("state", ""), "number": pr.get("number")}))
        return out

    async def _comments(self, since: datetime, login: str) -> list[dict]:
        notes = json.loads(await self._api(f"notifications?all=true&since={iso(since)}&per_page=50") or "[]")
        out = []
        for n in notes:
            subject = n.get("subject") or {}
            if n.get("reason") in NOISE_REASONS or subject.get("type") in NOISE_TYPES:
                continue
            repo = (n.get("repository") or {}).get("full_name", "")
            out.append(dict(kind="github_comment", source="github",
                            key=f"note:{n.get('id')}:{n.get('updated_at')}",
                            title=f"{repo}: {subject.get('title', '')}", url=html_url(subject.get("url")),
                            created=n.get("updated_at"),
                            data={"reason": n.get("reason", ""), "type": subject.get("type", ""), "repo": repo}))
        return out


def default_watchers() -> list:
    return [GitHubWatcher()]


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


async def poll_all(store: Any, watchers: Iterable | None = None, *, state_path: Path | None = None,
                   now: datetime | None = None) -> dict[str, int]:
    """Poll every watcher since its last successful poll; returns {name: new items or -1}."""
    now = now or datetime.now(timezone.utc)
    state_path = state_path or hub_data_dir() / "watchers.json"
    state = _load_state(state_path)
    summary: dict[str, int] = {}
    for watcher in (default_watchers() if watchers is None else watchers):
        last = parse_time(state.get(watcher.name))
        since = (last - OVERLAP) if last else now - FIRST_LOOKBACK
        try:
            new = await watcher.poll(since, store)
        except Exception:  # noqa: BLE001
            summary[watcher.name] = -1
            continue
        summary[watcher.name] = len(new)
        if not getattr(watcher, "errors", None):
            state[watcher.name] = iso(now)
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    except OSError:
        pass
    return summary


class WatchersSkill(Skill):
    """"computer check github" -> poll now and say what's new."""

    name = "watchers"
    category = "github"
    actions = {"check_now": "check GitHub for new repos, pull requests and comments now"}
    critical_actions: set[str] = set()

    def __init__(self, store: Any = None, watchers: list | None = None) -> None:
        super().__init__()
        self.store = store
        self.watchers = watchers

    async def plan(self, decision: Any, context: Any = None) -> Plan:
        return Plan(skill=self.name, action="check_now", args={}, preview="Check GitHub now", critical=False)

    async def run(self, plan: Plan, approval: Any = None, dry_run: bool = False) -> Result:
        store = self.store or getattr(self.hub, "store", None)
        if store is None:
            return Result(ok=False, text="The hub store isn't available yet.", speak=True, data={})
        if dry_run:
            return Result(ok=True, text="Would check GitHub.", speak=False, data={})
        summary = await poll_all(store, self.watchers)
        total = sum(n for n in summary.values() if n > 0)
        text = "Nothing new on GitHub." if total == 0 else f"{total} new GitHub item{'s' * (total != 1)}."
        if any(n < 0 for n in summary.values()):
            text += " Some sources failed."
        return Result(ok=True, text=text, speak=True, data=summary)


SKILL = WatchersSkill()
