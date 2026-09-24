"""Open an application by name, spoken out loud.

SECURITY
--------
This is the one part of the app that turns audio into process execution, so the
rule is absolute: **a transcript is never used to build a path or a command.**

What a spoken name can do is *select* an entry from an allowlist that was built
from two trusted sources:

  1. explicit `[[apps]]` rows in config.toml, written by the user;
  2. `.lnk` shortcuts already present in this machine's Start Menu.

Launching goes through `os.startfile` on that stored path, or
`subprocess.Popen(list)` with `shell=False` when arguments are configured.
There is no shell, no string interpolation, and no fallback that tries to
execute the spoken words. A name that matches nothing is refused out loud.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

log = logging.getLogger(__name__)

# Installers scatter these through the Start Menu; they are never what someone
# means by "open <app>", and a few of them are actively destructive.
_SKIP = (
    "uninstall", "remove ", "readme", "read me", "release notes", "documentation",
    "help", "manual", "license", "changelog", "website", "web site", "homepage",
    "repair", "modify", "setup", "installer", "troubleshoot", "safe mode",
)


# Stock Windows tools that ship as system executables rather than Start Menu
# shortcuts, so the scan above never finds them. Fixed names, resolved through
# shutil.which at startup -- still an allowlist, never spoken input.
_BUILTINS = {
    "calculator": "calc.exe",
    "notepad": "notepad.exe",
    "paint": "mspaint.exe",
    "file explorer": "explorer.exe",
    "task manager": "taskmgr.exe",
    "control panel": "control.exe",
    "command prompt": "cmd.exe",
    "powershell": "powershell.exe",
    "windows terminal": "wt.exe",
    "registry editor": "regedit.exe",
    "snipping tool": "snippingtool.exe",
    "character map": "charmap.exe",
    "on screen keyboard": "osk.exe",
    "magnifier": "magnify.exe",
    "wordpad": "write.exe",
}


def _normalize(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in name.lower())
    return " ".join(cleaned.split())


@dataclass
class AppEntry:
    name: str
    path: Path
    args: list[str] = field(default_factory=list)
    source: str = "config"

    @property
    def key(self) -> str:
        return _normalize(self.name)


class Launcher:
    """Resolves a spoken app name against an allowlist and starts it."""

    def __init__(
        self,
        apps: list[dict] | None = None,
        discover: bool = True,
        threshold: float = 0.78,
    ) -> None:
        self.threshold = max(0.0, min(1.0, float(threshold)))
        self._entries: list[AppEntry] = []
        self._discovered = False
        self._discover = discover and sys.platform == "win32"
        self._lock = threading.Lock()

        for row in apps or []:
            name = str(row.get("say") or row.get("name") or "").strip()
            raw = str(row.get("path") or "").strip()
            if not name or not raw:
                continue
            path = Path(os.path.expandvars(raw)).expanduser()
            if not path.exists():
                log.warning("[[apps]] %r points at a missing path: %s", name, path)
                continue
            args = [str(a) for a in row.get("args", [])]
            self._entries.append(AppEntry(name, path, args, source="config"))

    # ---------------------------------------------------------------- indexing
    def _start_menu_roots(self) -> list[Path]:
        roots = []
        for var in ("APPDATA", "PROGRAMDATA"):
            base = os.environ.get(var)
            if base:
                roots.append(Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
        return [r for r in roots if r.is_dir()]

    def _discover_start_menu(self) -> None:
        """Index Start Menu shortcuts.

        The `.lnk` is handed to the shell as-is rather than resolved, so no COM
        dependency is needed and the launch is exactly what a double-click does.
        """
        found = 0
        for root in self._start_menu_roots():
            try:
                shortcuts = list(root.rglob("*.lnk"))
            except OSError as exc:
                log.debug("could not scan %s: %s", root, exc)
                continue
            for link in shortcuts:
                label = link.stem
                lowered = label.lower()
                if any(skip in lowered for skip in _SKIP):
                    continue
                entry = AppEntry(label, link, source="start-menu")
                if any(e.key == entry.key for e in self._entries):
                    continue
                self._entries.append(entry)
                found += 1
        log.info("Indexed %d Start Menu shortcut(s).", found)

    def _add_builtins(self) -> None:
        for label, executable in _BUILTINS.items():
            resolved = shutil.which(executable)
            if not resolved:
                continue
            entry = AppEntry(label.title(), Path(resolved), source="builtin")
            if not any(e.key == entry.key for e in self._entries):
                self._entries.append(entry)

    def ensure_index(self) -> None:
        with self._lock:
            if self._discovered:
                return
            self._discovered = True
            if self._discover:
                self._add_builtins()
                self._discover_start_menu()

    # ---------------------------------------------------------------- matching
    def resolve(self, spoken: str) -> AppEntry | None:
        """Best allowlist entry for a spoken name, or None if nothing is close."""
        wanted = _normalize(spoken)
        if not wanted:
            return None
        self.ensure_index()

        spoken_words = wanted.split()
        best: tuple[float, AppEntry] | None = None
        for entry in self._entries:
            key = entry.key
            if key == wanted:
                return entry
            score = self._score(key, wanted, spoken_words)
            # Config entries are deliberate; prefer them over a scraped shortcut.
            if entry.source == "config":
                score = min(1.0, score + 0.05)
            elif entry.source == "builtin":
                score = min(1.0, score + 0.03)
            # Prefer the shorter label when scores tie: "Chrome" over
            # "Chrome Remote Desktop" for a bare "chrome".
            if best is None or score > best[0] or (
                score == best[0] and len(key) < len(best[1].key)
            ):
                best = (score, entry)

        if best is None or best[0] < self.threshold:
            return None
        return best[1]

    @staticmethod
    def _score(key: str, wanted: str, spoken_words: list[str]) -> float:
        """How well a spoken name fits an allowlist label.

        Plain string similarity is not enough: "chrome" scores 0.63 against
        "google chrome" and would be rejected, even though it is obviously what
        was meant. Word containment is the signal that actually matters.
        """
        key_words = key.split()
        count = len(spoken_words)
        # Contiguous run of words: "chrome" in "google chrome".
        for i in range(len(key_words) - count + 1):
            if key_words[i : i + count] == spoken_words:
                return 0.95
        # Same words, different order or scattered: "code visual studio".
        if count and all(word in key_words for word in spoken_words):
            return 0.88
        # Every spoken word at least begins a label word: "vs code" -> no,
        # but "powerp" -> "powerpoint".
        if count and all(
            any(kw.startswith(word) for kw in key_words) for word in spoken_words
        ):
            return 0.84
        return SequenceMatcher(None, key, wanted).ratio()

    def names(self) -> list[str]:
        self.ensure_index()
        return sorted({e.name for e in self._entries})

    # --------------------------------------------------------------- launching
    def launch(self, entry: AppEntry) -> bool:
        """Start an allowlisted entry. Never takes a caller-supplied string."""
        try:
            if entry.args:
                subprocess.Popen(  # noqa: S603 - fixed path, shell=False, list args
                    [str(entry.path), *entry.args],
                    shell=False,
                    close_fds=True,
                )
            else:
                os.startfile(str(entry.path))  # noqa: S606 - allowlisted path only
            log.info("Launched %s (%s)", entry.name, entry.path)
            return True
        except Exception as exc:
            log.error("Could not launch %s: %s", entry.name, exc)
            return False

    def open(self, spoken: str) -> tuple[bool, str]:
        """Resolve and launch. Returns (started, message to speak back)."""
        entry = self.resolve(spoken)
        if entry is None:
            log.info("No allowlisted app matches %r; refusing to launch.", spoken)
            return False, f"I don't know an app called {spoken}."
        if not self.launch(entry):
            return False, f"I couldn't start {entry.name}."
        return True, f"Opening {entry.name}."
