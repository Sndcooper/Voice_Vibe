"""voicevibe.privacy: what the hub and the vision model must never see.

Pure logic over window dicts; nothing is read from the real desktop.
"""

from __future__ import annotations

import unittest

import stubs

stubs.install()

from voicevibe.privacy import PrivacyGuard  # noqa: E402


def win(title: str, process: str, hwnd: int = 1) -> dict:
    return {"hwnd": hwnd, "title": title, "process": process}


class BuiltinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = PrivacyGuard()

    def test_password_managers(self) -> None:
        for process in ("KeePassXC.exe", "KeePass.exe", "1Password.exe", "Bitwarden.exe",
                        "Dashlane.exe", "Keeper.exe", "LastPass.exe", "Enpass.exe"):
            self.assertTrue(self.guard.check(win("Vault", process)).blocked, process)

    def test_password_manager_web_pages_and_credential_prompts(self) -> None:
        for title in ("Bitwarden Web vault - Microsoft Edge", "Windows Security",
                      "Credential Manager", "1Password — Zen Browser"):
            self.assertTrue(self.guard.check(win(title, "msedge.exe")).blocked, title)

    def test_banking_and_payments(self) -> None:
        for title in ("HDFC Bank NetBanking - Microsoft Edge", "ICICI Bank - Internet Banking",
                      "State Bank of India - Personal Banking", "PayPal: Summary",
                      "Paytm - Wallet", "PhonePe", "Google Pay", "Razorpay Checkout",
                      "Axis Bank - Login", "Kotak Mahindra Bank", "Zerodha Kite",
                      "Groww - Stocks"):
            self.assertTrue(self.guard.check(win(title, "msedge.exe")).blocked, title)

    def test_private_browsing(self) -> None:
        self.assertTrue(self.guard.check(win("[InPrivate] New tab - Microsoft Edge",
                                             "msedge.exe")).blocked)
        self.assertTrue(self.guard.check(win("Private Browsing — Zen Browser", "zen.exe")).blocked)

    def test_ordinary_windows_pass(self) -> None:
        for title, process in (("main.py - uBipedal - Visual Studio Code", "Code.exe"),
                               ("Claude", "claude.exe"), ("Spotify Premium", "Spotify.exe"),
                               ("Bankside Studio portfolio - Microsoft Edge", "msedge.exe"),
                               ("Pay attention to this bug · Issue #3", "msedge.exe"),
                               ("checkout.py - shop - Visual Studio Code", "Code.exe"),
                               ("x axis labels - matplotlib docs", "msedge.exe")):
            verdict = self.guard.check(win(title, process))
            self.assertFalse(verdict.blocked, (title, verdict.reason))

    def test_reason_names_the_rule(self) -> None:
        self.assertIn("password", self.guard.check(win("x", "KeePassXC.exe")).reason)
        self.assertIn("bank", self.guard.check(win("HDFC Bank", "msedge.exe")).reason)

    def test_empty_window_is_not_blocked(self) -> None:
        self.assertFalse(self.guard.check(None).blocked)
        self.assertFalse(self.guard.check({}).blocked)


class ConfigTests(unittest.TestCase):
    def test_shipped_config_keys_are_read(self) -> None:
        from voicevibe.config import load_config

        screen = load_config().screen
        self.assertEqual(screen["region_size"], [800, 500])
        guard = PrivacyGuard(dict(screen, privacy_deny_titles=["salary"]))
        self.assertTrue(guard.check(win("Salary.xlsx - Excel", "EXCEL.EXE")).blocked)
    def test_config_adds_entries(self) -> None:
        guard = PrivacyGuard({"deny_processes": ["Signal.exe"], "deny_titles": ["salary"]})
        self.assertTrue(guard.check(win("Chat", "signal.exe")).blocked)
        self.assertTrue(guard.check(win("Salary slips.xlsx - Excel", "EXCEL.EXE")).blocked)

    def test_config_cannot_loosen_builtins(self) -> None:
        guard = PrivacyGuard({"deny_processes": [], "deny_titles": [], "builtin": False,
                              "allow_processes": ["KeePassXC.exe"]})
        self.assertTrue(guard.check(win("Vault", "KeePassXC.exe")).blocked)
        self.assertTrue(guard.check(win("HDFC Bank", "msedge.exe")).blocked)

    def test_bad_config_values_are_ignored(self) -> None:
        guard = PrivacyGuard({"deny_processes": "notalist", "deny_titles": [None, 3, "ok"]})
        self.assertTrue(guard.check(win("ok then", "x.exe")).blocked)
        self.assertFalse(guard.check(win("fine", "x.exe")).blocked)


class MarkTests(unittest.TestCase):
    def test_user_marked_window_is_blocked_until_unmarked(self) -> None:
        guard = PrivacyGuard()
        w = win("Diary.docx - Word", "WINWORD.EXE", hwnd=77)
        self.assertFalse(guard.check(w).blocked)
        guard.mark(w)
        self.assertTrue(guard.check(w).blocked)
        self.assertIn("marked", guard.check(w).reason)
        # Same window, new title (another document): still the marked window.
        self.assertTrue(guard.check(win("Other.docx - Word", "WINWORD.EXE", hwnd=77)).blocked)
        self.assertTrue(guard.unmark(w))
        self.assertFalse(guard.check(w).blocked)

    def test_unmark_cannot_unblock_a_builtin(self) -> None:
        guard = PrivacyGuard()
        w = win("Vault", "KeePassXC.exe", hwnd=5)
        guard.mark(w)
        guard.unmark(w)
        self.assertTrue(guard.check(w).blocked)

    def test_any_of_several_windows(self) -> None:
        guard = PrivacyGuard()
        verdict = guard.check_any([win("Code", "Code.exe", 1), win("Vault", "KeePass.exe", 2)])
        self.assertTrue(verdict.blocked)


if __name__ == "__main__":
    unittest.main()
