"""Pair the bot with exactly one Telegram chat (the user's), then lock.

Pattern from NousResearch/hermes-agent gateway/pairing.py (MIT): one-time
8-character codes from an unambiguous 32-letter alphabet via `secrets`,
1-hour expiry, lockout after 5 wrong codes, codes never logged. Differences:
the code is created on the PC (`python -m vvbot pair`) and typed into
Telegram as `/pair CODE`, never sent by the bot; only its SHA-256 is stored;
and there is a single owner (rule 17), kept in keyring as `telegram_chat_id`.
Only a private chat with that user is ever authorized.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets as _random
import time
from pathlib import Path
from typing import Any, Callable

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
CODE_TTL_SECONDS = 3600
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 3600
OWNER_KEY = "telegram_chat_id"


def _hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


class Pairing:
    def __init__(self, secrets: Any = None, state_path: Path | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        if secrets is None:
            from vvhub import secrets as hub_secrets

            secrets = hub_secrets
        if state_path is None:
            from vvhub import data_dir

            state_path = data_dir() / "bot_pairing.json"
        self.secrets = secrets
        self.state_path = Path(state_path)
        self.clock = clock

    # ---- secrets (dict in tests, vvhub.secrets module in production) ----
    def _get(self, key: str) -> str | None:
        return self.secrets.get(key)

    def _set(self, key: str, value: str) -> None:
        if isinstance(self.secrets, dict):
            self.secrets[key] = value
        else:
            self.secrets.set(key, value)

    def _delete(self, key: str) -> None:
        if isinstance(self.secrets, dict):
            self.secrets.pop(key, None)
        else:
            self.secrets.delete(key)

    # ---- state file: {"hash", "expires", "failures", "locked_until"} ----
    def _load(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state), encoding="utf-8")

    # ---- API -------------------------------------------------------------
    @property
    def owner(self) -> int | None:
        raw = self._get(OWNER_KEY)
        try:
            return int(raw) if raw else None
        except ValueError:
            return None

    def authorized(self, chat_id: int, user_id: int, chat_type: str) -> bool:
        owner = self.owner
        return owner is not None and chat_type == "private" and chat_id == owner and user_id == owner

    def new_code(self) -> str:
        """A fresh one-time code (replaces any earlier one). Show it on the PC only."""
        code = "".join(_random.choice(ALPHABET) for _ in range(CODE_LENGTH))
        state = self._load()
        state.update(hash=_hash(code), expires=self.clock() + CODE_TTL_SECONDS)
        self._save(state)
        return code

    def try_pair(self, chat_id: int, user_id: int, code: str, chat_type: str) -> tuple[bool, str]:
        now = self.clock()
        if chat_type != "private" or chat_id != user_id:
            return False, "Pair from a private chat with the bot."
        owner = self.owner
        if owner is not None:
            if owner == chat_id:
                return True, "Already paired."
            return False, "This bot is already paired."
        state = self._load()
        if state.get("locked_until", 0) > now:
            return False, "Too many wrong codes; pairing is locked for a while."
        stored, expires = state.get("hash"), state.get("expires", 0)
        if stored and expires > now and hmac.compare_digest(stored, _hash(code or "")):
            self._set(OWNER_KEY, str(chat_id))
            self._save({})
            return True, "Paired. This bot now only answers this chat."
        failures = state.get("failures", 0) + 1
        state["failures"] = failures
        if failures >= MAX_FAILED_ATTEMPTS:
            state = {"locked_until": now + LOCKOUT_SECONDS}
        self._save(state)
        return False, "That code is wrong or expired. Run `python -m vvbot pair` on the PC for a new one."

    def unpair(self) -> None:
        self._delete(OWNER_KEY)
        self._save({})
