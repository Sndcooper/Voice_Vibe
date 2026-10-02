"""Per-app commands: what "go up" or "new chat" means depends on the app.

A profile belongs to one process (explorer.exe, zen.exe, claude.exe) and maps
spoken phrases to action specs (see actions.py). The router consults the
front app's profile before anything else, so a profile can give a global
phrase an app-specific meaning -- "pin tab" in Zen really pins.

Phrases are templates:

    "new folder called {name}"        {name} captures words and fills specs
    "go back|back"                    | separates alternatives

    [[profiles]]
    process = "explorer.exe"
    [profiles.commands]
    "open {name}" = { click_named = { name = "{name}", action = "double_click" } }

A [[profiles]] row adds to the built-in profile for its process and replaces
built-in phrases it repeats; `builtin = false` drops the built-ins entirely.

Zen's shortcuts are user-editable, so its profile is read from Zen's own
zen-keyboard-shortcuts.json and re-read whenever that file changes.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .actions import ActionError, parse

log = logging.getLogger(__name__)

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@dataclass
class ProfileCommand:
    phrase: str
    spec: Any
    patterns: list[re.Pattern[str]]
    # The phrase with its placeholders removed. Trigger words are checked
    # against this, not the captured words: "ask how to delete a branch" is a
    # question to type, and "delete {name}" still asks because of "delete".
    literal: str


def compile_phrase(phrase: str) -> tuple[list[re.Pattern[str]], str]:
    patterns = []
    for alternative in phrase.split("|"):
        alternative = " ".join(alternative.split())
        if not alternative:
            continue
        pieces, last = [], 0
        for match in _PLACEHOLDER.finditer(alternative):
            pieces.append(re.escape(alternative[last:match.start()]))
            pieces.append(f"(?P<{match.group(1)}>.+?)")
            last = match.end()
        pieces.append(re.escape(alternative[last:]))
        patterns.append(re.compile("".join(pieces), re.IGNORECASE))
    first = phrase.split("|")[0]
    literal = " ".join(_PLACEHOLDER.sub(" ", first).split())
    return patterns, literal


def fill(spec: Any, values: dict[str, str]) -> Any:
    """`spec` with every {name} in its strings replaced by what was said."""
    if isinstance(spec, str):
        return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), spec)
    if isinstance(spec, list):
        return [fill(item, values) for item in spec]
    if isinstance(spec, dict):
        return {key: fill(value, values) for key, value in spec.items()}
    return spec


@dataclass
class Profile:
    process: str
    commands: list[ProfileCommand] = field(default_factory=list)
    # Rebuilds the commands when the source changes (Zen's shortcut file).
    refresh: Callable[[], list[ProfileCommand] | None] | None = None

    def match(self, text: str) -> tuple[ProfileCommand, dict[str, str]] | None:
        if self.refresh is not None:
            fresh = self.refresh()
            if fresh is not None:
                self.commands = fresh
        for command in self.commands:
            for pattern in command.patterns:
                m = pattern.fullmatch(text)
                if m:
                    return command, {k: v.strip() for k, v in m.groupdict().items()}
        return None


def build_commands(table: dict[str, Any], source: str) -> list[ProfileCommand]:
    """Checked ProfileCommands from a phrase -> spec table. Bad rows are skipped."""
    commands = []
    for phrase, spec in table.items():
        patterns, literal = compile_phrase(str(phrase))
        if not patterns:
            continue
        # Validate with placeholders filled by a harmless word, so a bad key
        # name or typo surfaces at load time rather than mid-command.
        names = {m.group(1) for m in _PLACEHOLDER.finditer(str(phrase))}
        try:
            parse(fill(copy.deepcopy(spec), {n: "x" for n in names}))
        except ActionError as exc:
            log.warning("%s: %r ignored: %s", source, phrase, exc)
            continue
        commands.append(ProfileCommand(str(phrase), spec, patterns, literal))
    return commands


# ------------------------------------------------------------ File Explorer
def _navigate(target: str) -> list:
    # Alt+D selects the address bar; typing replaces its text. shell: names
    # follow folder redirection (OneDrive, moved Documents) where a typed
    # path would not.
    return [{"keys": "alt+d"}, {"wait": 0.2}, {"type_text": target}, {"keys": "enter"}]


_FOLDERS = {
    "downloads": "shell:Downloads", "documents": "shell:Personal", "desktop": "shell:Desktop",
    "pictures": "shell:My Pictures", "music": "shell:My Music", "videos": "shell:My Video",
    "this pc": "shell:MyComputerFolder", "recycle bin": "shell:RecycleBinFolder",
}
_SORTS = {"date": "Date modified", "name": "Name", "size": "Size", "type": "Type"}

EXPLORER: dict[str, Any] = {
    **{f"go to {name}|open {name}|go to the {name}": _navigate(path)
       for name, path in _FOLDERS.items()},
    "go up|up one level|parent folder": {"keys": "alt+up"},
    "go back|back": {"keys": "alt+left"},
    "go forward|forward": {"keys": "alt+right"},
    "refresh": {"keys": "f5"},
    "new folder": {"keys": "ctrl+shift+n"},
    # A new folder opens with its name selected, so typing replaces it.
    "new folder called {name}|new folder named {name}": [
        {"keys": "ctrl+shift+n"}, {"wait": 0.8}, {"type_text": "{name}"}, {"keys": "enter"},
    ],
    "rename to {name}|rename it to {name}|rename this to {name}": [
        {"keys": "f2"}, {"wait": 0.3}, {"type_text": "{name}"}, {"keys": "enter"},
    ],
    "copy path|copy the path|copy as path": {"keys": "ctrl+shift+c"},
    # No shortcut for either: through the Windows 11 command bar menus.
    **{f"sort by {word}": [
        {"click_named": "Sort"}, {"wait": 0.5}, {"click_named": item},
    ] for word, item in _SORTS.items()},
    "show hidden files|hide hidden files|toggle hidden files": [
        {"click_named": "View"}, {"wait": 0.5}, {"click_named": "Show"}, {"wait": 0.5},
        {"click_named": "Hidden items"},
    ],
    # Select (not Invoke, which would open it), then Delete. "delete" is a
    # trigger word, so this is always asked first.
    "delete {name}": [
        {"click_named": {"name": "{name}", "action": "select", "types": ["ListItem"]}},
        {"wait": 0.2}, {"keys": "delete"},
    ],
    "open {name}": {"click_named": {"name": "{name}", "action": "double_click",
                                    "types": ["ListItem"]}},
}


# -------------------------------------------------------------------- Zen
# Firefox's own navigation, which Zen keeps. Not in Zen's shortcut file.
ZEN_FIXED: dict[str, Any] = {
    "go back|back": {"keys": "alt+left"},
    "go forward|forward": {"keys": "alt+right"},
    "reload|refresh|reload the page": {"keys": "ctrl+r"},
    "address bar|focus address bar": {"keys": "ctrl+l"},
    "visit {site}|go to website {site}": [
        {"keys": "ctrl+l"}, {"wait": 0.15}, {"type_text": "{site}"}, {"keys": "enter"},
    ],
    "new private window|private window": {"keys": "ctrl+shift+p"},
    "bookmark this|bookmark this page": {"keys": "ctrl+d"},
}

# Zen shortcut id -> phrases. The keys come from the user's own file.
ZEN_IDS = {
    "zen-workspace-forward": "next workspace",
    "zen-workspace-backward": "previous workspace|last workspace",
    **{f"zen-workspace-switch-{n}": f"workspace {n}|workspace {word}"
       for n, word in enumerate(("one", "two", "three", "four", "five", "six", "seven",
                                 "eight", "nine", "ten"), 1)},
    "zen-split-view-grid": "split view grid|grid view",
    "zen-split-view-vertical": "split vertically|split view vertical",
    "zen-split-view-horizontal": "split horizontally|split view horizontal",
    "zen-split-view-unsplit": "unsplit|close split view",
    "zen-new-empty-split-view": "new split view",
    "zen-compact-mode-toggle": "compact mode|toggle compact mode",
    "zen-compact-mode-show-sidebar": "show sidebar|peek sidebar",
    "zen-toggle-sidebar": "toggle sidebar|hide sidebar",
    "zen-toggle-pin-tab": "pin tab|pin this tab|unpin tab|unpin this tab",
    "zen-copy-url": "copy url|copy link|copy the address",
    "zen-copy-url-markdown": "copy markdown link",
    "zen-glance-expand": "expand glance|open glance",
    "zen-close-all-unpinned-tabs": "close unpinned tabs",
}

_KEYCODES = {
    "VK_LEFT": "left", "VK_RIGHT": "right", "VK_UP": "up", "VK_DOWN": "down",
    "VK_RETURN": "enter", "VK_ESCAPE": "esc", "VK_TAB": "tab", "VK_SPACE": "space",
    "VK_BACK": "backspace", "VK_DELETE": "delete", "VK_HOME": "home", "VK_END": "end",
    "VK_PAGE_UP": "page_up", "VK_PAGE_DOWN": "page_down", "VK_INSERT": "insert",
    **{f"VK_F{n}": f"f{n}" for n in range(1, 13)},
}


def zen_combo(entry: dict) -> str | None:
    """A Zen shortcut entry as a keys spec ("ctrl+alt+right"), or None if unbound."""
    if entry.get("disabled"):
        return None
    key = str(entry.get("key") or "").strip()
    keycode = entry.get("keycode")
    if key:
        main = key.lower()
    elif keycode in _KEYCODES:
        main = _KEYCODES[keycode]
    else:
        return None
    mods = entry.get("modifiers") or {}
    parts = []
    # "accel" is Ctrl on Windows (Cmd on macOS); both spellings mean ctrl here.
    if mods.get("accel") or mods.get("control"):
        parts.append("ctrl")
    if mods.get("alt"):
        parts.append("alt")
    if mods.get("shift"):
        parts.append("shift")
    if mods.get("meta"):
        parts.append("win")
    return "+".join([*parts, main])


def zen_shortcut_file() -> Path | None:
    """The shortcuts file of the Zen profile used most recently."""
    base = Path(os.environ.get("APPDATA", "")) / "zen" / "Profiles"
    try:
        files = list(base.glob("*/zen-keyboard-shortcuts.json"))
    except OSError:
        return None
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def zen_table(path: Path | None) -> dict[str, Any]:
    """ZEN_FIXED plus a phrase for every Zen shortcut, keys as configured.

    A shortcut the user has left unbound still gets its phrase, which says so,
    rather than falling through and being typed.
    """
    table = dict(ZEN_FIXED)
    entries: dict[str, dict] = {}
    if path is not None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            entries = {e.get("id"): e for e in data.get("shortcuts", []) if isinstance(e, dict)}
        except (OSError, ValueError) as exc:
            log.warning("Could not read Zen shortcuts from %s: %s", path, exc)
    for shortcut_id, phrases in ZEN_IDS.items():
        combo = zen_combo(entries[shortcut_id]) if shortcut_id in entries else None
        if combo:
            table[phrases] = {"keys": combo}
        else:
            what = phrases.split("|")[0]
            table[phrases] = {"say": f"{what} has no shortcut set in Zen."}
    return table


def _zen_profile() -> Profile:
    state = {"path": None, "mtime": None}

    def refresh() -> list[ProfileCommand] | None:
        path = zen_shortcut_file()
        try:
            mtime = path.stat().st_mtime if path else None
        except OSError:
            mtime = None
        if (path, mtime) == (state["path"], state["mtime"]):
            return None
        state["path"], state["mtime"] = path, mtime
        log.info("Zen shortcuts loaded from %s", path or "built-in defaults")
        return build_commands(zen_table(path), "Zen profile")

    return Profile("zen.exe", refresh=refresh)


# ------------------------------------------------------------ chat apps
# Claude desktop names its controls in UI Automation ("Copy", "Send",
# "Scroll to bottom", an edit box called "Prompt"), so most of this is
# click-by-name. New chat lives in the sidebar, which may be collapsed.
_CLAUDE_PROMPT = {"click_named": {"name": "Prompt|Reply|Message", "types": ["Edit", "Document"],
                                  "action": "focus"}}
# The Codex desktop app (process ChatGPT.exe, package OpenAI.Codex). Its
# composer is a contenteditable (OpenCLI's clis/codex/send.js takes the last
# one); UIA reports it as an Edit or Document named by its placeholder.
_CODEX_PROMPT = {"click_named": {"name": "Ask Codex|Ask for follow-up changes|Message|Prompt",
                                 "types": ["Edit", "Document"], "action": "focus", "pick": "last"}}
# Where vvhub's code skill puts a spoken prompt in each desktop app.
PROMPT_BOXES: dict[str, Any] = {"claude_app": _CLAUDE_PROMPT, "codex_app": _CODEX_PROMPT}
CLAUDE: dict[str, Any] = {
    "new chat|new conversation|new session": {"first_of": [
        {"click_named": "New chat|New session"},
        [{"click_named": "Show sidebar"}, {"wait": 0.5}, {"click_named": "New chat|New session"}],
    ]},
    "focus prompt|focus the prompt|go to the prompt": _CLAUDE_PROMPT,
    # Enter sends; one command, no separate "send" to confirm.
    "ask {question}": [_CLAUDE_PROMPT, {"wait": 0.2}, {"type_text": "{question}"},
                       {"keys": "enter"}],
    "stop generating|stop the response|stop responding": {
        "click_named": "Stop response|Stop generating|Stop"},
    "regenerate|retry|try again": {"click_named": {"name": "Retry|Regenerate|Try again",
                                                   "pick": "last"}},
    "copy last answer|copy the answer|copy the last answer": {
        "click_named": {"name": "Copy", "pick": "last"}},
    "read the answer|read the last answer|read it out": [
        {"click_named": {"name": "Copy", "pick": "last"}}, {"wait": 0.3},
        {"say_clipboard": True},
    ],
    "scroll to latest|scroll to the bottom|jump to latest": {"first_of": [
        {"click_named": "Scroll to bottom|Jump to latest"},
        {"scroll": ["down", 50]},
    ]},
}

# ChatGPT desktop publishes keyboard shortcuts (Ctrl+/ lists them), so the
# ones it has are keys and the rest click by name.
CHATGPT: dict[str, Any] = {
    "new chat|new conversation": {"keys": "ctrl+shift+o"},
    "focus prompt|focus the prompt|go to the prompt": {"keys": "shift+esc"},
    "ask {question}": [{"keys": "shift+esc"}, {"wait": 0.2}, {"type_text": "{question}"},
                       {"keys": "enter"}],
    "stop generating|stop the response|stop responding": {
        "click_named": "Stop streaming|Stop generating|Stop"},
    "regenerate|retry|try again": {"click_named": {"name": "Regenerate|Try again|Retry",
                                                   "pick": "last"}},
    "copy last answer|copy the answer|copy the last answer": {"keys": "ctrl+shift+c"},
    "read the answer|read the last answer|read it out": [
        {"keys": "ctrl+shift+c"}, {"wait": 0.3}, {"say_clipboard": True},
    ],
    "scroll to latest|scroll to the bottom|jump to latest": {"first_of": [
        {"click_named": "Scroll to bottom|Jump to latest"},
        {"scroll": ["down", 50]},
    ]},
}


def builtin_profiles() -> dict[str, Profile]:
    return {
        "explorer.exe": Profile("explorer.exe", build_commands(EXPLORER, "Explorer profile")),
        "zen.exe": _zen_profile(),
        "claude.exe": Profile("claude.exe", build_commands(CLAUDE, "Claude profile")),
        "chatgpt.exe": Profile("chatgpt.exe", build_commands(CHATGPT, "ChatGPT profile")),
    }


def load_profiles(rows: list[dict] | None = None,
                  builtins: dict[str, Profile] | None = None) -> dict[str, Profile]:
    """Built-in profiles with [[profiles]] rows applied, by lowercase process."""
    profiles = builtin_profiles() if builtins is None else builtins
    for row in rows or []:
        process = str(row.get("process", "")).strip().lower()
        table = row.get("commands") or {}
        if not process or not isinstance(table, dict):
            log.warning("[[profiles]] row needs a process and a commands table: %r", row)
            continue
        user = build_commands(table, f"[[profiles]] {process}")
        existing = profiles.get(process)
        if existing is None or row.get("builtin", True) is False:
            profiles[process] = Profile(process, user)
            continue
        # User phrases go first, so they win wherever a phrase matches both.
        base = existing
        overridden = {c.phrase for c in user}

        def merged(base=base, user=user, overridden=overridden) -> list[ProfileCommand] | None:
            fresh = base.refresh() if base.refresh else None
            if fresh is not None:
                base.commands = fresh
            return user + [c for c in base.commands if c.phrase not in overridden]

        profiles[process] = Profile(process, merged() or [], refresh=merged)
    return profiles
