"""Where the app's log goes once there is no console to print to.

The app normally runs under pythonw.exe, so the rotating log file is the
record of what it heard and did.
"""

from __future__ import annotations

import logging
import os
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
    handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(name)s  %(message)s"))
    handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    logging.getLogger().addHandler(handler)
    return path
