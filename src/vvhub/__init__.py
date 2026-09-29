"""vvhub: the local automation hub behind Voice Vibe's "computer ..." commands.

A separate process from Voice Vibe. It decides (Laya), asks for approval when an
action is critical, and runs skills built on third-party tools. See TASK.md in
the workspace root for the rules and the interface contract.
"""

from __future__ import annotations

import os
from pathlib import Path

__version__ = "0.1.0"

HOST = "127.0.0.1"
PORT = 53874  # Airoot's overlay owns 53873.


def data_dir() -> Path:
    """Same per-user folder Voice Vibe uses. VVHUB_HOME overrides it (tests)."""
    override = os.environ.get("VVHUB_HOME")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "VoiceVibe"
