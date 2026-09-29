"""Scheduler (vvhub.scheduler): 08:00 / 20:00 reports, watcher polls, catch-up.

What matters: slot arithmetic across midnight, one catch-up report for any
number of missed slots (laptop asleep / hub off), no duplicate report for a
slot already done, the report window starts where the last one ended, and
`report --now` works without the hub running. APScheduler is only exercised
for job registration; no real waiting.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vvhub import scheduler  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))


def at(day, hour, minute=0):
    return datetime(2026, 9, day, hour, minute, tzinfo=IST)


def run(coro):
    return asyncio.run(coro)


class SlotTests(unittest.TestCase):
    def test_last_slot(self):
        self.assertEqual(scheduler.last_slot(at(30, 7, 59)), at(29, 20))
        self.assertEqual(scheduler.last_slot(at(30, 8, 0)), at(30, 8))
        self.assertEqual(scheduler.last_slot(at(30, 19, 0)), at(30, 8))
        self.assertEqual(scheduler.last_slot(at(30, 23, 0)), at(30, 20))

    def test_next_slot(self):
        self.assertEqual(scheduler.next_slot(at(30, 7, 0)), at(30, 8))
        self.assertEqual(scheduler.next_slot(at(30, 8, 0)), at(30, 20))
        self.assertEqual(scheduler.next_slot(at(30, 21, 0)).day, 1)

    def test_previous_slot(self):
        self.assertEqual(scheduler.previous_slot(at(30, 8)), at(29, 20))
        self.assertEqual(scheduler.previous_slot(at(30, 20)), at(30, 8))


class Recorder:
    def __init__(self):
        self.calls = []

    async def __call__(self, hub, slot, since, now):
        self.calls.append((slot, since, now))
        return SimpleNamespace(total=0, delivery={})


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class CatchUpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "scheduler.json"

    def tearDown(self):
        self.tmp.cleanup()

    def sched(self, now, polls=None):
        self.rec = Recorder()
        self.clock = Clock(now)

        async def poll(hub):
            (polls if polls is not None else []).append(1)

        return scheduler.ReportScheduler(SimpleNamespace(), make_report=self.rec, poll=poll,
                                         clock=self.clock, state_path=self.state)

    def test_first_start_reports_last_slot_once(self):
        s = self.sched(at(30, 9, 30))
        self.assertTrue(run(s.catch_up()))
        slot, since, now = self.rec.calls[0]
        self.assertEqual(slot, at(30, 8))
        self.assertEqual(since, (at(30, 8) - timedelta(hours=12)).timestamp())
        self.assertFalse(run(s.catch_up()))
        self.assertEqual(len(self.rec.calls), 1)

    def test_many_missed_slots_one_report_covering_all(self):
        self.state.write_text(json.dumps({"last_slot": at(27, 20).isoformat()}), encoding="utf-8")
        s = self.sched(at(30, 21, 0))
        run(s.catch_up())
        self.assertEqual(len(self.rec.calls), 1)
        slot, since, _ = self.rec.calls[0]
        self.assertEqual(slot, at(30, 20))
        self.assertEqual(since, at(27, 20).timestamp())

    def test_scheduled_fire_then_no_catch_up(self):
        s = self.sched(at(30, 20, 0))
        polls = []
        s.poll = lambda hub: _append(polls)
        run(s.fire())
        self.assertEqual(self.rec.calls[0][0], at(30, 20))
        self.assertEqual(polls, [1])  # fresh watcher data before the report
        self.clock.now = at(30, 20, 30)
        self.assertFalse(run(s.catch_up()))

    def test_failed_report_is_retried(self):
        s = self.sched(at(30, 9))

        async def boom(hub, slot, since, now):
            raise RuntimeError("disk full")

        s.make_report = boom
        self.assertFalse(run(s.catch_up()))
        s.make_report = self.rec
        self.assertTrue(run(s.catch_up()))

    def test_poll_failure_does_not_block_report(self):
        s = self.sched(at(30, 9))

        async def bad_poll(hub):
            raise RuntimeError("gh down")

        s.poll = bad_poll
        self.assertTrue(run(s.catch_up()))

    def test_tick_polls_and_catches_up(self):
        polls = []
        s = self.sched(at(30, 9), polls)
        run(s.tick())
        self.assertEqual(polls, [1, 1])  # tick poll + pre-report poll
        self.assertEqual(len(self.rec.calls), 1)


async def _append(lst):
    lst.append(1)


class StartTests(unittest.TestCase):
    def test_start_registers_jobs(self):
        try:
            import apscheduler  # noqa: F401
        except ImportError:
            self.skipTest("APScheduler not installed")

        async def scenario():
            with tempfile.TemporaryDirectory() as tmp:
                s = scheduler.ReportScheduler(SimpleNamespace(), make_report=Recorder(), poll=lambda h: _append([]),
                                              state_path=Path(tmp) / "s.json", catch_up_on_start=False)
                s.start()
                ids = sorted(job.id for job in s._aps.get_jobs())
                s.shutdown()
                return ids

        self.assertEqual(run(scenario()), ["report", "tick"])

    def test_fallback_without_apscheduler(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as tmp:
                s = scheduler.ReportScheduler(SimpleNamespace(), make_report=Recorder(), poll=lambda h: _append([]),
                                              state_path=Path(tmp) / "s.json", catch_up_on_start=False)
                s.start(use_apscheduler=False)
                running = s._task is not None and not s._task.done()
                s.shutdown()
                await asyncio.sleep(0)
                return running

        self.assertTrue(run(scenario()))


class CliTests(unittest.TestCase):
    def test_report_now_writes_html(self):
        import os

        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("VVHUB_HOME")
            os.environ["VVHUB_HOME"] = tmp
            try:
                out = []
                code = scheduler.main(["report", "--now", "--no-poll", "--html-only"], out=out.append)
            finally:
                if old is None:
                    os.environ.pop("VVHUB_HOME", None)
                else:
                    os.environ["VVHUB_HOME"] = old
            self.assertEqual(code, 0)
            htmls = list((Path(tmp) / "reports").glob("*.html"))
            self.assertEqual(len(htmls), 1)
            joined = "\n".join(out)
            self.assertIn(str(htmls[0]), joined)
            self.assertIn("nothing new", joined.lower())
            # --now doesn't consume a scheduled slot.
            self.assertFalse((Path(tmp) / "reports" / "scheduler.json").exists())


if __name__ == "__main__":
    unittest.main()
