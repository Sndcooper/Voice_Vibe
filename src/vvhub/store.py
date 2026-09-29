"""The hub's SQLite store (TASK.md §3.7) and 2-day retention (rule 15).

One connection per Store, guarded by a lock, WAL mode so the control app can
read while the hub writes. Everything conversational goes after
RETENTION_SECONDS unless its conversation is saved. Watch items (new PRs,
comments...) keep WATCH_SECONDS because the reports need a week of them.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

RETENTION_SECONDS = 2 * 86400
WATCH_SECONDS = 30 * 86400

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations(
    id TEXT PRIMARY KEY, started REAL NOT NULL, saved INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS turns(
    id INTEGER PRIMARY KEY AUTOINCREMENT, conversation TEXT NOT NULL,
    ts REAL NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS turns_conv ON turns(conversation, ts);
CREATE TABLE IF NOT EXISTS decisions(
    id INTEGER PRIMARY KEY AUTOINCREMENT, conversation TEXT NOT NULL,
    ts REAL NOT NULL, request TEXT NOT NULL, decision TEXT NOT NULL,
    corrected TEXT);
CREATE TABLE IF NOT EXISTS approvals(
    id TEXT PRIMARY KEY, conversation TEXT NOT NULL, created REAL NOT NULL,
    action TEXT NOT NULL, preview TEXT NOT NULL, channel TEXT NOT NULL,
    status TEXT NOT NULL, decided_by TEXT NOT NULL DEFAULT '', decided REAL);
CREATE TABLE IF NOT EXISTS jobs(
    id TEXT PRIMARY KEY, conversation TEXT NOT NULL, created REAL NOT NULL,
    updated REAL NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
    progress TEXT NOT NULL DEFAULT '', result TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS watch_items(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, source TEXT NOT NULL,
    kind TEXT NOT NULL, key TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '', data TEXT NOT NULL DEFAULT '{}',
    notified INTEGER NOT NULL DEFAULT 0, UNIQUE(source, key));
"""


def today_conversation(now: float | None = None) -> str:
    """Default conversation id: one per local day, like Voice Vibe's history."""
    return datetime.fromtimestamp(now or time.time()).strftime("%Y-%m-%d")


class Store:
    def __init__(self, path: str | Path = ":memory:") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            if path != ":memory:":
                self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _run(self, sql: str, args: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._db.execute(sql, tuple(args))
            self._db.commit()
            return cur

    def _rows(self, sql: str, args: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, tuple(args)).fetchall()]

    # conversations -------------------------------------------------------
    def ensure_conversation(self, conversation: str, ts: float | None = None) -> None:
        self._run(
            "INSERT OR IGNORE INTO conversations(id, started) VALUES(?, ?)",
            (conversation, ts or time.time()),
        )

    def save_conversation(self, conversation: str, title: str = "") -> None:
        """Keep forever (rule 15)."""
        self.ensure_conversation(conversation)
        self._run(
            "UPDATE conversations SET saved = 1, title = CASE WHEN ? = '' THEN title ELSE ? END"
            " WHERE id = ?",
            (title, title, conversation),
        )

    def is_saved(self, conversation: str) -> bool:
        rows = self._rows("SELECT saved FROM conversations WHERE id = ?", (conversation,))
        return bool(rows and rows[0]["saved"])

    def add_turn(self, role: str, text: str, conversation: str | None = None,
                 data: dict | None = None, ts: float | None = None) -> int:
        ts = ts or time.time()
        conversation = conversation or today_conversation(ts)
        self.ensure_conversation(conversation, ts)
        cur = self._run(
            "INSERT INTO turns(conversation, ts, role, text, data) VALUES(?, ?, ?, ?, ?)",
            (conversation, ts, role, text, json.dumps(data or {})),
        )
        return int(cur.lastrowid)

    def turns(self, conversation: str) -> list[dict]:
        return self._rows(
            "SELECT * FROM turns WHERE conversation = ? ORDER BY ts, id", (conversation,)
        )

    # decisions -----------------------------------------------------------
    def add_decision(self, request: str, decision: dict, conversation: str | None = None,
                     ts: float | None = None) -> int:
        ts = ts or time.time()
        conversation = conversation or today_conversation(ts)
        self.ensure_conversation(conversation, ts)
        cur = self._run(
            "INSERT INTO decisions(conversation, ts, request, decision) VALUES(?, ?, ?, ?)",
            (conversation, ts, request, json.dumps(decision)),
        )
        return int(cur.lastrowid)

    def correct_decision(self, decision_id: int, corrected: dict) -> None:
        self._run("UPDATE decisions SET corrected = ? WHERE id = ?",
                  (json.dumps(corrected), decision_id))

    def decisions(self, since: float = 0.0) -> list[dict]:
        return self._rows("SELECT * FROM decisions WHERE ts >= ? ORDER BY ts", (since,))

    # approvals -----------------------------------------------------------
    def add_approval(self, approval: dict, conversation: str | None = None) -> str:
        created = approval.get("created") or time.time()
        conversation = conversation or today_conversation(created)
        self.ensure_conversation(conversation, created)
        self._run(
            "INSERT INTO approvals(id, conversation, created, action, preview, channel, status,"
            " decided_by) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (approval["id"], conversation, created, approval["action"],
             approval.get("preview", ""), approval.get("channel", "voice"),
             approval.get("status", "pending"), approval.get("decided_by", "")),
        )
        return approval["id"]

    def update_approval(self, approval_id: str, status: str, decided_by: str = "") -> None:
        self._run(
            "UPDATE approvals SET status = ?, decided_by = ?, decided = ? WHERE id = ?",
            (status, decided_by, time.time(), approval_id),
        )

    def approvals(self, status: str | None = None) -> list[dict]:
        if status:
            return self._rows("SELECT * FROM approvals WHERE status = ? ORDER BY created",
                              (status,))
        return self._rows("SELECT * FROM approvals ORDER BY created")

    # jobs ----------------------------------------------------------------
    def add_job(self, kind: str, conversation: str | None = None, status: str = "queued") -> str:
        now = time.time()
        conversation = conversation or today_conversation(now)
        self.ensure_conversation(conversation, now)
        job_id = uuid.uuid4().hex[:12]
        self._run(
            "INSERT INTO jobs(id, conversation, created, updated, kind, status)"
            " VALUES(?, ?, ?, ?, ?, ?)",
            (job_id, conversation, now, now, kind, status),
        )
        return job_id

    def update_job(self, job_id: str, status: str | None = None, progress: str | None = None,
                   result: dict | None = None) -> None:
        sets, args = ["updated = ?"], [time.time()]
        if status is not None:
            sets.append("status = ?")
            args.append(status)
        if progress is not None:
            sets.append("progress = ?")
            args.append(progress)
        if result is not None:
            sets.append("result = ?")
            args.append(json.dumps(result))
        self._run(f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", (*args, job_id))

    def jobs(self, status: str | None = None) -> list[dict]:
        if status:
            return self._rows("SELECT * FROM jobs WHERE status = ? ORDER BY created", (status,))
        return self._rows("SELECT * FROM jobs ORDER BY created")

    # watch items ---------------------------------------------------------
    def add_watch_item(self, source: str, kind: str, key: str, title: str = "",
                       url: str = "", data: dict | None = None, ts: float | None = None) -> bool:
        """Record something new (a PR, a comment...). False if already known."""
        cur = self._run(
            "INSERT OR IGNORE INTO watch_items(ts, source, kind, key, title, url, data)"
            " VALUES(?, ?, ?, ?, ?, ?, ?)",
            (ts or time.time(), source, kind, key, title, url, json.dumps(data or {})),
        )
        return cur.rowcount == 1

    def list_watch_items(self, since: float = 0.0, kinds: Iterable[str] | None = None) -> list[dict]:
        rows = self._rows("SELECT * FROM watch_items WHERE ts >= ? ORDER BY ts", (since,))
        if kinds is not None:
            wanted = set(kinds)
            rows = [r for r in rows if r["kind"] in wanted]
        return rows

    def mark_notified(self, item_ids: Iterable[int]) -> None:
        for item_id in item_ids:
            self._run("UPDATE watch_items SET notified = 1 WHERE id = ?", (item_id,))

    # retention -----------------------------------------------------------
    def purge(self, now: float | None = None) -> dict[str, int]:
        """Delete unsaved conversation data older than 2 days (rule 15)."""
        now = now or time.time()
        cutoff = now - RETENTION_SECONDS
        unsaved = "conversation IN (SELECT id FROM conversations WHERE saved = 0)"
        counts = {
            "turns": self._run(f"DELETE FROM turns WHERE ts < ? AND {unsaved}", (cutoff,)).rowcount,
            "decisions": self._run(
                f"DELETE FROM decisions WHERE ts < ? AND {unsaved}", (cutoff,)).rowcount,
            "approvals": self._run(
                f"DELETE FROM approvals WHERE created < ? AND status != 'pending' AND {unsaved}",
                (cutoff,)).rowcount,
            "jobs": self._run(
                f"DELETE FROM jobs WHERE updated < ? AND status IN ('done', 'failed', 'cancelled')"
                f" AND {unsaved}", (cutoff,)).rowcount,
            "watch_items": self._run(
                "DELETE FROM watch_items WHERE ts < ?", (now - WATCH_SECONDS,)).rowcount,
        }
        counts["conversations"] = self._run(
            "DELETE FROM conversations WHERE saved = 0 AND started < ?"
            " AND id NOT IN (SELECT conversation FROM turns)"
            " AND id NOT IN (SELECT conversation FROM decisions)"
            " AND id NOT IN (SELECT conversation FROM approvals)"
            " AND id NOT IN (SELECT conversation FROM jobs)",
            (cutoff,),
        ).rowcount
        return counts
