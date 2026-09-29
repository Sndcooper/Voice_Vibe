"""The privacy guard: windows the hub, OCR and the vision model never see.

TASK.md rule 12: password managers, banking and windows the user has marked
are skipped. A blocked window still tells the hub *that* something is there
(its process name, so "switch to" keeps working), but no title, caret text,
selection, pointer element, OCR, crop or page text leaves Voice Vibe, and the
bundle says `redacted: true`.

Stricter only: `[screen].privacy_deny_processes` / `privacy_deny_titles` in
config.toml add entries; nothing in config can remove a built-in one, and
"computer you can look again" only lifts a mark the user set.

Title rules are whole-word, case-insensitive regular expressions, so
"Bankside Studio" and "Pay attention to this bug" pass while "HDFC Bank" and
"PayPal" do not.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from typing import Any, Iterable

log = logging.getLogger(__name__)

PASSWORD_PROCESSES = frozenset({
    "keepass.exe", "keepassxc.exe", "1password.exe", "bitwarden.exe", "dashlane.exe",
    "keeper.exe", "keeperpasswordmanager.exe", "lastpass.exe", "enpass.exe", "roboform.exe",
    "nordpass.exe", "protonpass.exe", "credentialuibroker.exe", "consent.exe",
})
PASSWORD_TITLES = (
    r"1password", r"bitwarden", r"keepass(?:xc)?", r"lastpass", r"dashlane", r"nordpass",
    r"proton pass", r"enpass", r"roboform", r"keeper(?: security| vault)",
    r"windows security", r"credential manager", r"password manager", r"passwords?(?: -| —|$)",
    r"one-time (?:password|code)", r"\botp\b", r"2fa", r"authenticator",
)
BANK_TITLES = (
    r"[\w&]+ bank\b", r"\bbank of\b", r"net ?banking", r"internet banking", r"online banking",
    r"personal banking", r"\bbanking\b", r"paypal", r"paytm", r"phonepe", r"google pay",
    r"\bg ?pay\b", r"\bbhim\b", r"\bupi\b", r"razorpay", r"stripe checkout",
    r"payment(?:s)? gateway", r"credit card", r"debit card", r"\bcvv\b", r"zerodha",
    r"groww", r"upstox", r"angel one", r"coinbase", r"binance", r"wazirx", r"wise\.com",
    r"revolut", r"\bhdfc\b", r"\bicici\b", r"\bsbi\b", r"\bkotak\b", r"\byes bank\b",
)
PRIVATE_TITLES = (r"\[?inprivate\]?", r"private browsing", r"incognito")
_BUILTIN_TITLES = [(re.compile(rf"(?i)(?<![\w])(?:{p})(?![\w])"), why)
                   for group, why in ((PASSWORD_TITLES, "password manager"),
                                      (BANK_TITLES, "banking or payments"),
                                      (PRIVATE_TITLES, "private browsing"))
                   for p in group]


@dataclass(frozen=True)
class Verdict:
    blocked: bool
    reason: str = ""

    def __bool__(self) -> bool:  # truthy = blocked
        return self.blocked


ALLOWED = Verdict(False)


def _strings(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(v).strip() for v in value if isinstance(v, str) and v.strip()]


def _process(window: dict) -> str:
    return str(window.get("process") or window.get("process_name") or "").strip().lower()


class PrivacyGuard:
    def __init__(self, cfg: dict | None = None) -> None:
        cfg = cfg or {}
        self.processes = PASSWORD_PROCESSES | {p.lower() for p in _strings(
            cfg.get("deny_processes", cfg.get("privacy_deny_processes")))}
        self.titles = list(_BUILTIN_TITLES) + [
            (re.compile(rf"(?i)(?<![\w]){re.escape(t)}(?![\w])"), "your deny list")
            for t in _strings(cfg.get("deny_titles", cfg.get("privacy_deny_titles")))]
        self._marked: dict[int, str] = {}
        self._lock = threading.Lock()

    def check(self, window: dict | None) -> Verdict:
        if not window:
            return ALLOWED
        process = _process(window)
        if process in PASSWORD_PROCESSES:
            return Verdict(True, "password manager")
        if process in self.processes:
            return Verdict(True, "your deny list")
        hwnd = window.get("hwnd")
        with self._lock:
            if hwnd and int(hwnd) in self._marked:
                return Verdict(True, "you marked this window private")
        title = str(window.get("title") or "")
        for pattern, why in self.titles:
            if pattern.search(title):
                return Verdict(True, why)
        return ALLOWED

    def check_any(self, windows: Iterable[dict | None]) -> Verdict:
        for window in windows:
            verdict = self.check(window)
            if verdict.blocked:
                return verdict
        return ALLOWED

    def mark(self, window: dict) -> bool:
        hwnd = window.get("hwnd") if window else None
        if not hwnd:
            return False
        with self._lock:
            self._marked[int(hwnd)] = str(window.get("title") or "")
        log.info("Marked private: %s", window.get("title") or hwnd)
        return True

    def unmark(self, window: dict) -> bool:
        """Lift a user mark. Built-in and config rules still apply."""
        hwnd = window.get("hwnd") if window else None
        with self._lock:
            return self._marked.pop(int(hwnd), None) is not None if hwnd else False

    def marked(self) -> list[int]:
        with self._lock:
            return list(self._marked)
