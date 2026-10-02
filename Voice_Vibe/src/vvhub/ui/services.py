"""Link-services cards: status from the vvhub doctor checks, fixed actions only.

A card lists the doctor checks it depends on, the keyring secret it takes (set
through POST /ui/api/secrets/<name>, never read back) and a whitelist of
actions. Actions only ever open fixed URLs / folders or start fixed commands;
nothing from the request is ever put on a command line.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Any

from .launcher import VENVS

# name -> (pattern it must match, what to tell the user when it doesn't)
SECRETS = {
    "freellmapi_key": (re.compile(r"^[A-Za-z0-9._~+/=-]{8,4096}$"), "one line, no spaces (from the FreeLLMAPI dashboard)"),
    "notion_token": (re.compile(r"^(secret_|ntn_)[A-Za-z0-9]{20,200}$"),
                     "starts with ntn_ or secret_ (Notion > Settings > Connections > Develop integrations)"),
    "telegram_bot_token": (re.compile(r"^\d{5,12}:[A-Za-z0-9_-]{30,64}$"), "looks like 123456789:AA... (from @BotFather)"),
}

CARDS: list[dict] = [
    {"id": "freellmapi", "title": "FreeLLMAPI", "checks": ["freellmapi", "freellmapi key"],
     "secret": "freellmapi_key",
     "help": "Local LLM pool on :3001. Paste the unified key from its dashboard (Keys page).",
     "actions": {"open_dashboard": ("Open dashboard", "browser", "http://localhost:3001")}},
    {"id": "edge", "title": "Edge extension (OpenCLI Browser Bridge)",
     "checks": ["opencli", "opencli edge extension"], "secret": None,
     "help": "In Edge: edge://extensions > Developer mode > Load unpacked > pick the opencli-extension folder.",
     "actions": {"open_extensions": ("Open edge://extensions", "edge", "edge://extensions/"),
                 "open_extension_folder": ("Show extension folder", "folder", str(VENVS / "node" / "opencli-extension"))}},
    {"id": "notion", "title": "Notion", "checks": ["notion token"], "secret": "notion_token",
     "help": "Create an internal integration, paste its token, make a page called 'Voice Vibe' and share it "
             "with the integration (page menu > Connections), then press Set up pages.",
     "actions": {"notion_setup": ("Set up pages", "internal", ""),
                 "open_integrations": ("Open Notion integrations", "browser",
                                       "https://www.notion.so/profile/integrations")}},
    {"id": "telegram", "title": "Telegram bot", "checks": ["telegram token"], "secret": "telegram_bot_token",
     "help": "Make a bot with @BotFather, paste its token, start the bot, then Pair and send /pair CODE to it "
             "from your phone. It then only answers your chat.",
     "actions": {"telegram_start": ("Start bot", "internal", ""),
                 "telegram_pair": ("Pair my phone", "internal", ""),
                 "telegram_unpair": ("Unpair", "internal", ""),
                 "open_botfather": ("Open @BotFather", "browser", "https://t.me/BotFather")}},
    {"id": "github", "title": "GitHub (gh CLI)", "checks": ["gh CLI"], "secret": None,
     "help": "The GitHub skill uses gh + git. Log in once; the token stays in gh's own store.",
     "actions": {"gh_login": ("Log in (opens a console)", "console", ["gh", "auth", "login", "--web"])}},
    {"id": "linkedin", "title": "LinkedIn (via OpenCLI in Edge)", "checks": ["opencli edge extension"],
     "secret": None, "help": "OpenCLI uses your logged-in Edge session. Log in to LinkedIn in Edge once.",
     "actions": {"open_linkedin": ("Log in in Edge", "edge", "https://www.linkedin.com/login")}},
    {"id": "instagram", "title": "Instagram (via OpenCLI in Edge)", "checks": ["opencli edge extension"],
     "secret": None, "help": "OpenCLI uses your logged-in Edge session. Log in to Instagram in Edge once.",
     "actions": {"open_instagram": ("Log in in Edge", "edge", "https://www.instagram.com/accounts/login/")}},
]
CARD_BY_ID = {c["id"]: c for c in CARDS}


def check_secret(name: str, value: Any) -> str | None:
    """None if fine, else a message that doesn't repeat the value."""
    rule = SECRETS.get(name)
    if rule is None:
        return "unknown secret"
    if not isinstance(value, str) or not rule[0].match(value.strip()):
        return f"That doesn't look right: {rule[1]}."
    return None


def card_status(card: dict, checks: dict[str, dict]) -> tuple[str, str]:
    """('ok' | 'user' | 'fail' | 'unknown', detail) from this card's doctor checks."""
    found = [checks[n] for n in card["checks"] if n in checks]
    if not found:
        return "unknown", "not checked yet"
    bad = [c for c in found if not c["ok"]]
    if not bad:
        return "ok", "; ".join(c["detail"] for c in found)
    status = "fail" if any(not c.get("needs_user") for c in bad) else "user"
    return status, "; ".join(f"{c['name']}: {c['detail']}" for c in bad)


def edge_path() -> str | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            path = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if path.exists():
                return str(path)
    return shutil.which("msedge")


def open_target(kind: str, target: Any) -> None:
    """Open a fixed URL / folder / console command (user clicked a card button)."""
    if kind == "browser":
        webbrowser.open(str(target))
    elif kind == "edge":
        exe = edge_path()
        if exe is None:
            raise RuntimeError("Microsoft Edge not found")
        subprocess.Popen([exe, str(target)], close_fds=True)
    elif kind == "folder":
        path = Path(str(target))
        if not path.exists():
            raise RuntimeError(f"{path} doesn't exist yet")
        os.startfile(str(path))  # type: ignore[attr-defined]  # Windows Explorer
    elif kind == "console":
        exe = shutil.which(target[0])
        if exe is None:
            raise RuntimeError(f"{target[0]} is not installed")
        subprocess.Popen([exe, *target[1:]], creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                         close_fds=True)
    else:
        raise ValueError(kind)


def gh_status(timeout: float = 15.0) -> tuple[bool, str]:
    exe = shutil.which("gh")
    if exe is None:
        return False, "gh is not installed"
    try:
        done = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace",
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return False, "gh auth status timed out"
    text = f"{done.stdout}\n{done.stderr}"
    match = re.search(r"Logged in to (\S+) (?:account|as) (\S+)", text)
    if done.returncode == 0 and match:
        return True, f"logged in to {match.group(1)} as {match.group(2).rstrip(')(')}"
    return False, "not logged in (press Log in)"
