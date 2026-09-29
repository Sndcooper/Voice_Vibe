"""Watchers (vvhub.skills.watchers): GitHub new repos / PRs / comments.

What matters: one `gh api` call per kind, argument lists only, items land in
the store as watch_items exactly once (re-polls and overlapping windows don't
duplicate), ordinary commits/CI noise are skipped, and a failing source never
stops the others. No network: a fake runner replays canned JSON.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vvhub.skills import watchers  # noqa: E402

SINCE = datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc)


class FakeStore:
    """Mirrors vvhub.store.Store's watch-item API (UNIQUE(source, key))."""

    def __init__(self):
        self.items: list[dict] = []

    def add_watch_item(self, source, kind, key, title="", url="", data=None, ts=None):
        if any(i["source"] == source and i["key"] == key for i in self.items):
            return False
        self.items.append(dict(source=source, kind=kind, key=key, title=title, url=url,
                               data=data or {}, ts=ts))
        return True

    def list_watch_items(self, since=0.0, kinds=None):
        assert isinstance(since, float), since
        return [i for i in self.items if kinds is None or i["kind"] in kinds]


REPOS = [
    {"full_name": "me/new-one", "html_url": "https://github.com/me/new-one",
     "created_at": "2026-09-30T01:00:00Z", "description": "fresh", "private": True},
    {"full_name": "me/old", "html_url": "https://github.com/me/old",
     "created_at": "2026-01-01T00:00:00Z", "description": "", "private": False},
]
PRS = {"items": [
    {"id": 11, "number": 7, "title": "Add parser", "html_url": "https://github.com/me/new-one/pull/7",
     "created_at": "2026-09-30T02:00:00Z", "user": {"login": "bob"},
     "repository_url": "https://api.github.com/repos/me/new-one", "state": "open"},
]}
NOTES = [
    {"id": "100", "reason": "author", "updated_at": "2026-09-30T02:30:00Z",
     "subject": {"title": "Add parser", "type": "PullRequest",
                 "url": "https://api.github.com/repos/me/new-one/pulls/7"},
     "repository": {"full_name": "me/new-one"}},
    {"id": "101", "reason": "ci_activity", "updated_at": "2026-09-30T02:31:00Z",
     "subject": {"title": "CI failed", "type": "CheckSuite", "url": None},
     "repository": {"full_name": "me/new-one"}},
    {"id": "102", "reason": "subscribed", "updated_at": "2026-09-30T02:32:00Z",
     "subject": {"title": "Bump deps", "type": "Commit", "url": "https://api.github.com/repos/x/y/commits/abc"},
     "repository": {"full_name": "x/y"}},
    {"id": "103", "reason": "mention", "updated_at": "2026-09-30T02:40:00Z",
     "subject": {"title": "Crash on start", "type": "Issue",
                 "url": "https://api.github.com/repos/me/old/issues/3"},
     "repository": {"full_name": "me/old"}},
]


class FakeRunner:
    def __init__(self, fail: set[str] | None = None):
        self.calls: list[list[str]] = []
        self.fail = fail or set()

    async def __call__(self, argv, cwd=None):
        assert isinstance(argv, list)
        self.calls.append(list(argv))
        joined = " ".join(argv)
        for key in self.fail:
            if key in joined:
                return 1, "", f"HTTP 502 for {key}"
        if argv[:3] == ["gh", "api", "user"]:
            return 0, "me\n", ""
        if "user/repos" in joined:
            return 0, json.dumps(REPOS), ""
        if "search/issues" in joined:
            return 0, json.dumps(PRS), ""
        if "notifications" in joined:
            return 0, json.dumps(NOTES), ""
        return 0, "", ""


def run(coro):
    return asyncio.run(coro)


class GitHubWatcherTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.runner = FakeRunner()
        self.watcher = watchers.GitHubWatcher(runner=self.runner)

    def poll(self, since=SINCE):
        return run(self.watcher.poll(since, self.store))

    def test_collects_repos_prs_comments(self):
        new = self.poll()
        kinds = sorted(i["kind"] for i in new)
        self.assertEqual(kinds, ["github_comment", "github_comment", "github_pr", "github_repo"])
        repo = next(i for i in new if i["kind"] == "github_repo")
        self.assertEqual(repo["title"], "me/new-one")
        self.assertEqual(repo["url"], "https://github.com/me/new-one")
        self.assertEqual(repo["source"], "github")
        pr = next(i for i in new if i["kind"] == "github_pr")
        self.assertIn("Add parser", pr["title"])
        self.assertEqual(pr["data"]["author"], "bob")
        comment = next(i for i in new if i["kind"] == "github_comment" and i["data"]["reason"] == "mention")
        self.assertEqual(comment["url"], "https://github.com/me/old/issues/3")
        self.assertEqual(len(self.store.items), 4)

    def test_skips_old_repos_commits_and_ci(self):
        new = self.poll()
        self.assertEqual([i["title"] for i in new if i["kind"] == "github_repo"], ["me/new-one"])
        titles = " ".join(i["title"] for i in new)
        self.assertNotIn("CI failed", titles)
        self.assertNotIn("Bump deps", titles)

    def test_no_duplicates_on_repoll(self):
        self.poll()
        again = self.poll()
        self.assertEqual(again, [])
        self.assertEqual(len(self.store.items), 4)

    def test_arg_lists_and_since_in_queries(self):
        self.poll()
        for argv in self.runner.calls:
            self.assertEqual(argv[:2], ["gh", "api"])
        joined = [" ".join(a) for a in self.runner.calls]
        self.assertTrue(any("created:>=2026-09-29T20:00:00Z" in j for j in joined))
        self.assertTrue(any("since=2026-09-29T20:00:00Z" in j for j in joined))
        self.assertTrue(any("involves:me" in j for j in joined))

    def test_one_failing_source_does_not_stop_others(self):
        watcher = watchers.GitHubWatcher(runner=FakeRunner(fail={"notifications"}))
        new = run(watcher.poll(SINCE, self.store))
        self.assertEqual(sorted(i["kind"] for i in new), ["github_pr", "github_repo"])
        self.assertTrue(watcher.errors)

    def test_login_failure_returns_nothing(self):
        watcher = watchers.GitHubWatcher(runner=FakeRunner(fail={"api user"}))
        self.assertEqual(run(watcher.poll(SINCE, self.store)), [])
        self.assertTrue(watcher.errors)

    def test_gh_missing(self):
        async def missing(argv, cwd=None):
            raise FileNotFoundError("gh")

        watcher = watchers.GitHubWatcher(runner=missing)
        self.assertEqual(run(watcher.poll(SINCE, self.store)), [])

    def test_real_store_dedupes(self):
        try:
            from vvhub.store import Store
        except ImportError:
            self.skipTest("vvhub.store not present")
        store = Store(":memory:")
        try:
            self.assertEqual(len(run(self.watcher.poll(SINCE, store))), 4)
            # A fresh watcher (no in-memory state) still doesn't duplicate.
            fresh = watchers.GitHubWatcher(runner=FakeRunner())
            self.assertEqual(run(fresh.poll(SINCE, store)), [])
            rows = store.list_watch_items(0.0, ["github_pr"])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["url"], "https://github.com/me/new-one/pull/7")
        finally:
            store.close()


class PollAllTests(unittest.TestCase):
    def test_state_file_tracks_last_poll(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "watchers.json"
            store = FakeStore()
            now = datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc)
            w = watchers.GitHubWatcher(runner=FakeRunner())
            summary = run(watchers.poll_all(store, [w], state_path=state, now=now))
            self.assertEqual(summary["github"], 4)
            saved = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(saved["github"], "2026-09-30T08:00:00Z")

            # Next poll starts from the saved time (minus a small overlap).
            seen = {}

            class Spy:
                name = "github"
                errors: list = []

                async def poll(self, since, store):
                    seen["since"] = since
                    return []

            run(watchers.poll_all(store, [Spy()], state_path=state, now=now + timedelta(hours=1)))
            self.assertLessEqual(seen["since"], now)
            self.assertGreater(seen["since"], now - timedelta(hours=1))

    def test_first_poll_looks_back_a_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            seen = {}

            class Spy:
                name = "x"
                errors: list = []

                async def poll(self, since, store):
                    seen["since"] = since
                    return []

            now = datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc)
            run(watchers.poll_all(FakeStore(), [Spy()], state_path=Path(tmp) / "s.json", now=now))
            self.assertEqual(seen["since"], now - timedelta(hours=24))

    def test_crashing_watcher_isolated(self):
        class Boom:
            name = "boom"
            errors: list = []

            async def poll(self, since, store):
                raise RuntimeError("nope")

        with tempfile.TemporaryDirectory() as tmp:
            store = FakeStore()
            summary = run(watchers.poll_all(store, [Boom(), watchers.GitHubWatcher(runner=FakeRunner())],
                                            state_path=Path(tmp) / "s.json"))
            self.assertEqual(summary["boom"], -1)
            self.assertEqual(summary["github"], 4)


if __name__ == "__main__":
    unittest.main()
