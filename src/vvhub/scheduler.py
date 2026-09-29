"""Scheduler: 08:00 / 20:00 reports and watcher polls, with missed-run catch-up.

Built on APScheduler 3 (`AsyncIOScheduler`, cron + interval triggers) running
inside the hub's event loop; if APScheduler is missing, a plain asyncio loop
does the same job (rule 19). Catch-up is ours, because APScheduler's memory
job store forgets everything when the hub stops: the last reported slot is
kept in `reports\\scheduler.json`, and whenever the hub starts or the periodic
tick runs, a slot that has passed without a report produces ONE report that
covers everything since the last one (a laptop asleep for three days gets one
report, not six).

Hub wiring (WS0): `ReportScheduler(hub).start()` in the server lifespan,
`.shutdown()` on exit. CLI: `python -m vvhub.scheduler report --now`
(and `python -m vvhub report --now` once WS0 routes it here).
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

from .skills import reports

log = logging.getLogger(__name__)

SLOT_HOURS = (8, 20)
TICK_MINUTES = 15
FIRST_WINDOW = timedelta(hours=12)
MISFIRE_GRACE = 3600


def _slots_around(now: datetime) -> list[datetime]:
    days = (now.date() - timedelta(days=1), now.date(), now.date() + timedelta(days=1))
    return [datetime(d.year, d.month, d.day, h, tzinfo=now.tzinfo) for d in days for h in SLOT_HOURS]


def last_slot(now: datetime) -> datetime:
    """The most recent report time at or before `now`."""
    return max(s for s in _slots_around(now) if s <= now)


def next_slot(now: datetime) -> datetime:
    """The first report time strictly after `now`."""
    return min(s for s in _slots_around(now) if s > now)


def previous_slot(slot: datetime) -> datetime:
    return last_slot(slot - timedelta(seconds=1))


def _local_now() -> datetime:
    return datetime.now().astimezone()


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def default_poll(hub: Any) -> None:
    from .skills.watchers import poll_all

    await poll_all(hub.store)


class ReportScheduler:
    def __init__(self, hub: Any, make_report: Callable[..., Awaitable[Any]] | None = None,
                 poll: Callable[[Any], Any] | None = None, clock: Callable[[], datetime] = _local_now,
                 state_path: Path | None = None, catch_up_on_start: bool = True) -> None:
        self.hub = hub
        self.make_report = make_report or reports.make_report
        self.poll = poll or default_poll
        self.clock = clock
        self.state_path = Path(state_path) if state_path else reports.reports_dir() / "scheduler.json"
        self.catch_up_on_start = catch_up_on_start
        self._aps: Any = None
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    # ---- state ---------------------------------------------------------------------
    def _load(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")

    def last_reported(self) -> datetime | None:
        raw = self._load().get("last_slot")
        try:
            return datetime.fromisoformat(raw) if raw else None
        except ValueError:
            return None

    # ---- jobs ----------------------------------------------------------------------
    async def _safe_poll(self) -> None:
        try:
            await _maybe_await(self.poll(self.hub))
        except Exception as exc:  # noqa: BLE001 - stale data beats no report
            log.warning("watcher poll failed: %s", exc)

    async def catch_up(self) -> bool:
        """Report the latest passed slot if it hasn't been reported. True if a report was made."""
        async with self._lock:
            now = self.clock()
            slot = last_slot(now)
            done = self.last_reported()
            if done is not None and done >= slot:
                return False
            since = (done or slot - FIRST_WINDOW).timestamp()
            await self._safe_poll()
            try:
                await self.make_report(self.hub, slot, since, now.timestamp())
            except Exception:  # noqa: BLE001 - leave the slot open so the next tick retries
                log.exception("report for %s failed", slot)
                return False
            state = self._load()
            state.update(last_slot=slot.isoformat(), last_run=now.isoformat())
            self._save(state)
            return True

    async def fire(self) -> None:
        """The 08:00 / 20:00 job."""
        await self.catch_up()

    async def tick(self) -> None:
        """Every TICK_MINUTES: fresh watch items, and any report a sleep made us miss."""
        await self._safe_poll()
        await self.catch_up()

    # ---- lifecycle -----------------------------------------------------------------
    def start(self, use_apscheduler: bool = True) -> None:
        """Call from inside the hub's running event loop."""
        aps = None
        if use_apscheduler:
            try:
                from apscheduler.schedulers.asyncio import AsyncIOScheduler
                from apscheduler.triggers.cron import CronTrigger
                from apscheduler.triggers.interval import IntervalTrigger

                aps = AsyncIOScheduler(timezone=self.clock().tzinfo)
                hours = ",".join(str(h) for h in SLOT_HOURS)
                aps.add_job(self.fire, CronTrigger(hour=hours, minute=0, timezone=self.clock().tzinfo),
                            id="report", coalesce=True, max_instances=1, misfire_grace_time=MISFIRE_GRACE)
                aps.add_job(self.tick, IntervalTrigger(minutes=TICK_MINUTES), id="tick", coalesce=True,
                            max_instances=1)
                aps.start()
            except ImportError:
                log.warning("APScheduler not installed; using the built-in report loop")
                aps = None
        self._aps = aps
        if aps is None:
            self._task = asyncio.create_task(self._loop())
        elif self.catch_up_on_start:
            self._task = asyncio.create_task(self.catch_up())

    async def _loop(self) -> None:
        if self.catch_up_on_start:
            await self.catch_up()
        while True:
            now = self.clock()
            wait = min((next_slot(now) - now).total_seconds(), TICK_MINUTES * 60)
            await asyncio.sleep(max(wait, 1.0))
            await self.tick()

    def shutdown(self) -> None:
        if self._aps is not None:
            self._aps.shutdown(wait=False)
            self._aps = None
        if self._task is not None:
            self._task.cancel()
            self._task = None


async def report_now(hub: Any, out_dir: Path | None = None, telegram: bool = True,
                     clock: Callable[[], datetime] = _local_now) -> Any:
    """An on-demand report since the last scheduled one; doesn't consume a slot."""
    out_dir = Path(out_dir) if out_dir else reports.reports_dir()
    now = clock()
    done = ReportScheduler(hub, state_path=out_dir / "scheduler.json").last_reported()
    since = (done or now - FIRST_WINDOW).timestamp()
    return await reports.make_report(hub, now, since, now.timestamp(), out_dir=out_dir, telegram=telegram)


def main(argv: list[str] | None = None, out: Callable[[str], None] = print) -> int:
    parser = argparse.ArgumentParser(prog="python -m vvhub.scheduler")
    sub = parser.add_subparsers(dest="command", required=True)
    rep = sub.add_parser("report", help="make a report")
    rep.add_argument("--now", action="store_true", required=True, help="report everything new right now")
    rep.add_argument("--no-poll", action="store_true", help="don't ask GitHub etc. for new items first")
    rep.add_argument("--html-only", action="store_true", help="skip Notion (HTML file only)")
    args = parser.parse_args(argv)

    from . import data_dir
    from .store import Store

    store = Store(data_dir() / "hub.db")
    try:
        skills: dict = {}
        if not args.html_only:
            from .skills import discover

            skills = discover()
        # No bus: the CLI runs outside the hub, so nothing is sent to Telegram.
        hub = SimpleNamespace(store=store, bus=None, skills=skills)
        if not args.no_poll:
            asyncio.run(default_poll(hub))
        started = time.monotonic()
        report = asyncio.run(report_now(hub, out_dir=data_dir() / "reports", telegram=False))
        out(f"{report.title}: {report.total} items in {time.monotonic() - started:.1f}s")
        out(reports.spoken_summary(report))
        for channel, status in report.delivery.items():
            out(f"  {channel}: {status}")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
