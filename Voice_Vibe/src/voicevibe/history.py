"""Where the app's output goes once there is no console to print to.

Running in the background means log records and transcripts have to land
somewhere durable. Two sinks, deliberately separate:

  log      rotating text, for debugging ("why did the mic fail?")
  history  one JSON object per turn, for reading back what was said
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

log = logging.getLogger(__name__)


def data_dir() -> Path:
    """Per-user writable location. Never the install directory, which may be
    read-only or inside Program Files."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "VoiceVibe"


def attach_file_log(verbose: bool = False, max_bytes: int = 1_000_000) -> Path | None:
    """Add a rotating file handler to the root logger."""
    directory = data_dir() / "logs"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("Could not create the log directory: %s", exc)
        return None

    path = directory / "voicevibe.log"
    handler = RotatingFileHandler(
        path, maxBytes=max_bytes, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-7s %(name)s  %(message)s")
    )
    handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    logging.getLogger().addHandler(handler)
    return path


class History:
    """Append-only record of turns, one JSONL file per day.

    Kept `keep_days` (default 2) and then deleted, unless saved: `save()`
    copies the kept days into `history/saved/`, which pruning never touches.

    Writes are best effort: a full disk or a locked file must never take down
    dictation, so every failure is logged once and swallowed.
    """

    def __init__(self, enabled: bool = True, keep_days: int = 2,
                 directory: Path | None = None) -> None:
        self.enabled = enabled
        self.keep_days = keep_days
        self.directory = directory or data_dir() / "history"
        self._lock = threading.Lock()
        self._warned = False
        self._recent: list[dict] = []

        if not self.enabled:
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("History disabled, could not create %s: %s", self.directory, exc)
            self.enabled = False
            return
        self._prune()

    @property
    def saved_directory(self) -> Path:
        return self.directory / "saved"

    def _path(self) -> Path:
        return self.directory / f"{datetime.now():%Y-%m-%d}.jsonl"

    def _prune(self, now: float | None = None) -> None:
        if self.keep_days <= 0:
            return
        cutoff = (now or datetime.now().timestamp()) - self.keep_days * 86400
        try:
            # Top level only: saved/ is kept forever.
            for entry in self.directory.glob("*.jsonl"):
                if entry.stat().st_mtime < cutoff:
                    entry.unlink()
        except OSError:
            pass

    def save(self) -> int:
        """Keep the current conversation forever. Returns the turns saved.

        The "conversation" is everything still kept (the last `keep_days`).
        Saving twice does not duplicate turns: each day's saved file is
        rewritten from the union of what was saved and what is kept now.
        """
        if not self.enabled:
            return 0
        saved = 0
        with self._lock:
            try:
                self.saved_directory.mkdir(parents=True, exist_ok=True)
                for day in sorted(self.directory.glob("*.jsonl")):
                    target = self.saved_directory / day.name
                    lines: list[str] = []
                    seen: set[str] = set()
                    for source in (target, day):
                        if not source.exists():
                            continue
                        for line in source.read_text(encoding="utf-8").splitlines():
                            if line.strip() and line not in seen:
                                seen.add(line)
                                lines.append(line)
                    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    saved += len(lines)
            except OSError as exc:
                log.warning("Could not save the conversation: %s", exc)
        return saved

    def add(self, **fields: object) -> dict:
        """Record one turn. Returns the record so callers can show it."""
        record = {"ts": datetime.now().isoformat(timespec="seconds"), **fields}
        with self._lock:
            self._recent.append(record)
            del self._recent[:-50]
            if not self.enabled:
                return record
            try:
                with self._path().open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError as exc:
                if not self._warned:
                    log.warning("Could not write history: %s", exc)
                    self._warned = True
        return record

    def recent(self, limit: int = 10) -> list[dict]:
        with self._lock:
            return self._recent[-limit:]


# "computer save this conversation" and close variants. Exact match after the
# prefix, so a dictated sentence that mentions saving is never swallowed.
SAVE_PHRASES = frozenset({
    "save this conversation", "save the conversation", "save conversation",
    "save this chat", "save the chat", "keep this conversation",
})


def is_save_command(command: str) -> bool:
    words = "".join(c if c.isalnum() or c.isspace() else " " for c in command.lower())
    return " ".join(words.split()) in SAVE_PHRASES
