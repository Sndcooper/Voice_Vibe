"""Reports (vvhub.skills.reports): 08:00 / 20:00 digest of rule 16.

What matters: every rule-16 section comes from the store (new repos, PRs,
comments, posts, research, Laya's auto-decisions, pending approvals), ordinary
commits never appear, empty sections are omitted, scraped titles can't inject
HTML or javascript: links, and each channel (HTML file, Notion via WS3's
notes skill, Telegram notify, spoken-on-next-arm) degrades on its own. Real
in-memory Store, fake bus and notes skill; nothing leaves the machine.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vvhub.skills import reports  # noqa: E402
from vvhub.store import Store  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
SLOT = datetime(2026, 9, 30, 20, 0, tzinfo=IST)
SINCE = datetime(2026, 9, 30, 8, 0, tzinfo=IST)
T = SINCE.timestamp() + 3600  # inside the window
OLD = SINCE.timestamp() - 3600  # before it


def run(coro):
    return asyncio.run(coro)


def seeded_store():
    s = Store(":memory:")
    s.add_watch_item("github", "github_repo", "repo:me/new", "me/new", "https://github.com/me/new", {}, ts=T)
    s.add_watch_item("github", "github_pr", "pr:1", "me/new#7 Add parser", "https://github.com/me/new/pull/7",
                     {"author": "bob"}, ts=T)
    s.add_watch_item("github", "github_comment", "note:1", "me/new: Add parser", "https://github.com/me/new/pull/7",
                     {"reason": "comment"}, ts=T)
    s.add_watch_item("instagram", "instagram_comment", "ig:1", "@amy on your reel", "https://instagram.com/p/x", {},
                     ts=T)
    s.add_watch_item("linkedin", "linkedin_post", "li:1", "Posted: Voice Vibe update", "https://linkedin.com/x", {},
                     ts=T)
    s.add_watch_item("github", "github_commit", "c:1", "Bump deps", "https://github.com/me/new/commit/1", {}, ts=T)
    s.add_watch_item("github", "github_pr", "pr:old", "me/old#1 Old", "https://github.com/me/old/pull/1", {}, ts=OLD)
    s.add_decision("open notepad", {"category": "app", "action": "open", "target": "notepad",
                                    "confidence": 0.93, "critical": False, "needs_approval": False}, ts=T)
    s.add_decision("push it", {"category": "github", "action": "push", "confidence": 0.9,
                               "critical": True, "needs_approval": True}, ts=T)
    s.add_decision("hello", {"category": "chitchat", "action": "", "confidence": 0.8}, ts=T)
    s.add_approval({"id": "a1", "action": "push", "preview": "Push feature/x to GitHub", "channel": "telegram",
                    "status": "pending", "created": T})
    s.add_approval({"id": "a2", "action": "post", "preview": "Post to LinkedIn", "status": "approved", "created": T})
    job = s.add_job("research")
    s.update_job(job, status="done", result={"title": "Laya fine-tuning", "url": "https://notion.so/x"})
    s._run("UPDATE jobs SET updated = ? WHERE id = ?", (T, job))  # store stamps real time; pin it in the window
    return s


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.store = seeded_store()
        self.report = reports.collect(self.store, SINCE.timestamp(), SLOT.timestamp() + 7200, slot=SLOT)

    def titles(self, key):
        return [i["title"] for i in self.report.sections.get(key, [])]

    def test_sections(self):
        self.assertEqual(self.titles("repos"), ["me/new"])
        self.assertEqual(self.titles("prs"), ["me/new#7 Add parser"])
        self.assertEqual(sorted(self.titles("comments")), ["@amy on your reel", "me/new: Add parser"])
        self.assertEqual(self.titles("posts"), ["Posted: Voice Vibe update"])
        self.assertEqual(self.titles("research"), ["Laya fine-tuning"])
        self.assertEqual(self.titles("approvals"), ["Push feature/x to GitHub"])

    def test_no_commits_or_old_items(self):
        everything = " ".join(i["title"] for items in self.report.sections.values() for i in items)
        self.assertNotIn("Bump deps", everything)
        self.assertNotIn("me/old", everything)

    def test_auto_decisions_only(self):
        items = self.report.sections["decisions"]
        self.assertEqual(len(items), 1)
        self.assertIn("open notepad", items[0]["title"])
        self.assertIn("93%", items[0]["detail"])

    def test_title(self):
        self.assertEqual(self.report.title, "Evening report · Wed 30 Sep 2026")
        morning = reports.collect(self.store, 0, 1, slot=SLOT.replace(hour=8))
        self.assertTrue(morning.title.startswith("Morning report"))

    def test_empty_store(self):
        empty = reports.collect(Store(":memory:"), SINCE.timestamp(), SLOT.timestamp(), slot=SLOT)
        self.assertEqual(empty.sections, {})
        self.assertEqual(empty.total, 0)
        self.assertIn("nothing new", reports.spoken_summary(empty).lower())


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.report = reports.collect(seeded_store(), SINCE.timestamp(), SLOT.timestamp() + 7200, slot=SLOT)

    def test_spoken_summary(self):
        text = reports.spoken_summary(self.report)
        self.assertTrue(text.startswith("Evening report"))
        for part in ("1 new repo", "1 pull request", "2 new comments", "1 post", "1 research",
                     "1 approval waiting"):
            self.assertIn(part, text)
        self.assertNotIn("http", text)
        self.assertLess(len(text.split()), 60)

    def test_telegram_text(self):
        text = reports.telegram_text(self.report)
        self.assertIn("Pull requests", text)
        self.assertIn("me/new#7 Add parser", text)
        self.assertLessEqual(len(text), 4000)

    def test_html_escapes_and_blocks_js_links(self):
        s = Store(":memory:")
        s.add_watch_item("instagram", "instagram_comment", "x", "<script>alert(1)</script>",
                         "javascript:alert(1)", {}, ts=T)
        rep = reports.collect(s, SINCE.timestamp(), SLOT.timestamp(), slot=SLOT)
        page = reports.render_html(rep)
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("javascript:", page)

    def test_html_has_sections_and_links(self):
        page = reports.render_html(self.report)
        self.assertIn('<h2 id="s-prs">Pull requests</h2>', page)
        self.assertIn('href="https://github.com/me/new/pull/7"', page)
        self.assertIn('rel="noopener noreferrer"', page)
        self.assertIn('lang="en"', page)

    def test_markdown(self):
        md = reports.render_markdown(self.report)
        self.assertIn("## Pull requests", md)
        self.assertIn("[me/new#7 Add parser](https://github.com/me/new/pull/7)", md)

    def test_markdown_escapes_brackets(self):
        s = Store(":memory:")
        s.add_watch_item("github", "github_pr", "k", "Fix [x](evil) thing", "https://github.com/a/b/pull/1", {}, ts=T)
        md = reports.render_markdown(reports.collect(s, SINCE.timestamp(), SLOT.timestamp(), slot=SLOT))
        self.assertIn(r"Fix \[x\]\(evil\) thing", md)


class FakeBus:
    def __init__(self, connected=True):
        self._connected = connected
        self.notified = []

    def connected(self, role):
        return self._connected

    async def notify(self, role, msg):
        self.notified.append((role, msg))
        return self._connected


class FakeNotes:
    name = "notes"

    def __init__(self, fail=False):
        self.saved = []
        self.fail = fail

    async def save_report(self, title, markdown):
        if self.fail:
            raise RuntimeError("Notion 401")
        self.saved.append((title, markdown))
        return "https://notion.so/report-1"


class DeliverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def hub(self, bus=None, notes=None):
        return SimpleNamespace(store=seeded_store(), bus=bus, skills={"notes": notes} if notes else {})

    def test_all_channels(self):
        bus, notes = FakeBus(), FakeNotes()
        rep = run(reports.make_report(self.hub(bus, notes), slot=SLOT, since=SINCE.timestamp(),
                                      now=SLOT.timestamp(), out_dir=self.dir))
        html = self.dir / "2026-09-30-2000.html"
        self.assertTrue(html.exists())
        self.assertEqual(rep.delivery["html"], str(html))
        self.assertEqual(rep.delivery["notion"], "https://notion.so/report-1")
        self.assertEqual(notes.saved[0][0], rep.title)
        self.assertEqual(rep.delivery["telegram"], "sent")
        role, msg = bus.notified[0]
        self.assertEqual((role, msg["type"]), ("bot", "notify"))
        self.assertIn("Pull requests", msg["text"])
        self.assertEqual(reports.take_spoken(self.dir), reports.spoken_summary(rep))
        self.assertIsNone(reports.take_spoken(self.dir))  # spoken once

    def test_channels_degrade_independently(self):
        rep = run(reports.make_report(self.hub(FakeBus(connected=False), FakeNotes(fail=True)), slot=SLOT,
                                      since=SINCE.timestamp(), now=SLOT.timestamp(), out_dir=self.dir))
        self.assertTrue(Path(rep.delivery["html"]).exists())
        self.assertIn("401", rep.delivery["notion"])
        self.assertEqual(rep.delivery["telegram"], "bot not connected")

    def test_no_notes_skill_no_bus(self):
        rep = run(reports.make_report(self.hub(), slot=SLOT, since=SINCE.timestamp(), now=SLOT.timestamp(),
                                      out_dir=self.dir))
        self.assertEqual(rep.delivery["notion"], "notes skill not available")
        self.assertEqual(rep.delivery["telegram"], "bot not connected")

    def test_ws3_notes_add_to_section(self):
        class Notion:
            def __init__(self):
                self.calls = []

            async def add_to_section(self, section, title, markdown):
                self.calls.append((section, title, markdown))
                return {"id": "p1", "url": "https://notion.so/p1"}

        notes = SimpleNamespace(name="notes", notion=Notion(), actions={})
        rep = run(reports.make_report(self.hub(notes=notes), slot=SLOT, since=SINCE.timestamp(),
                                      now=SLOT.timestamp(), out_dir=self.dir))
        self.assertEqual(rep.delivery["notion"], "https://notion.so/p1")
        section, title, md = notes.notion.calls[0]
        self.assertEqual((section, title), ("Reports", rep.title))
        self.assertIn("## Pull requests", md)

    def test_ws3_bare_kinds_are_reported(self):
        s = Store(":memory:")
        s.add_watch_item("linkedin", "post", "l1", "Posted: hello", "https://linkedin.com/p", {}, ts=T)
        s.add_watch_item("instagram", "comment", "i1", "@amy: nice", "https://instagram.com/p", {}, ts=T)
        s.add_watch_item("research", "research", "r1", "Laya ONNX", "https://notion.so/r", {}, ts=T)
        rep = reports.collect(s, SINCE.timestamp(), SLOT.timestamp(), slot=SLOT)
        self.assertEqual({k: len(v) for k, v in rep.sections.items()},
                         {"posts": 1, "comments": 1, "research": 1})

    def test_notes_skill_without_save_report_uses_run(self):
        from vvhub.schemas import Result

        class RunOnlyNotes:
            name = "notes"
            actions = {"save_report": "x"}

            def __init__(self):
                self.plans = []

            async def run(self, plan, approval=None, dry_run=False):
                self.plans.append(plan)
                return Result(ok=True, text="saved", data={"url": "https://notion.so/r"})

        notes = RunOnlyNotes()
        rep = run(reports.make_report(self.hub(notes=notes), slot=SLOT, since=SINCE.timestamp(),
                                      now=SLOT.timestamp(), out_dir=self.dir))
        self.assertEqual(notes.plans[0].action, "save_report")
        self.assertIn("## Pull requests", notes.plans[0].args["markdown"])
        self.assertEqual(rep.delivery["notion"], "https://notion.so/r")


class SkillTests(unittest.TestCase):
    def test_shape_and_phrases(self):
        skill = reports.SKILL
        self.assertEqual(skill.name, "reports")
        self.assertEqual(set(skill.actions), {"read_report", "report_now"})
        self.assertEqual(skill.critical_actions, set())
        self.assertEqual(skill.phrases.get("read my report"), "read_report")

    def test_read_report_speaks_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = reports.ReportsSkill(out_dir=Path(tmp))
            plan = run(skill.plan(SimpleNamespace(action="read_report", target=""), {}))
            self.assertIn("no report", run(skill.run(plan)).text.lower())
            reports.save_spoken(Path(tmp), "Evening report: 2 new comments.")
            result = run(skill.run(plan))
            self.assertEqual(result.text, "Evening report: 2 new comments.")
            self.assertTrue(result.speak)
            # Reading it again still works (it's the latest), but take_spoken is now empty.
            self.assertIsNone(reports.take_spoken(Path(tmp)))
            self.assertEqual(run(skill.run(plan)).text, "Evening report: 2 new comments.")


if __name__ == "__main__":
    unittest.main()
