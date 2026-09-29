"""The bot's behaviour, independent of python-telegram-bot.

telegram_bot.py turns Telegram updates into calls here and implements the
`messenger` (send_text / send_card / edit_text). This split replaces
upstream's OpenAIHelper: chat goes to the hub `request`, voice notes to the
hub `transcribe` (Voice Vibe's loaded Whisper) instead of the OpenAI API.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any, Callable

from vvhub import protocol

from . import answers
from .approvals import ApprovalDesk
from .audio import AudioError, to_wav
from .hub_client import HubUnavailable
from .utils import split_into_chunks

log = logging.getLogger(__name__)

LOCKED = ("This bot is locked to its owner. On the PC run `python -m vvbot pair`, "
          "then send /pair CODE here.")
OFFLINE = "The PC hub is offline right now."
HELP = (
    "Voice Vibe on your phone.\n\n"
    "• Send text or a voice note: it goes to the PC like \"computer …\".\n"
    "• Approval cards: tap Approve/Deny, or answer with a plain yes / no "
    "(reply to the card if several are waiting).\n\n"
    "/pending – approvals waiting\n/status – is the PC hub online\n"
    "/plugins – list plugins, /run <function> [json]\n/help – this text"
)
LEVEL_ICON = {"info": "ℹ️", "warning": "⚠️", "error": "❗"}


class BotCore:
    def __init__(self, hub: Any, messenger: Any, pairing: Any, clock: Callable[[], float] = time.time,
                 transcode: Callable[[bytes], bytes] | None = None, plugins: Any = None,
                 desk: ApprovalDesk | None = None) -> None:
        self.hub = hub
        self.messenger = messenger
        self.pairing = pairing
        self.transcode = transcode or to_wav
        self.plugins = plugins
        self.desk = desk or ApprovalDesk(messenger, hub, clock)

    # ---- auth ---------------------------------------------------------------
    async def _allowed(self, chat_id: int, user_id: int, chat_type: str) -> bool:
        if self.pairing.authorized(chat_id, user_id, chat_type):
            return True
        if self.pairing.owner is None and chat_type == "private":
            await self.messenger.send_text(chat_id, LOCKED)
        else:
            log.info("ignored update from chat %s user %s", chat_id, user_id)
        return False

    async def _say(self, chat_id: int, text: str, reply_to: int | None = None) -> None:
        for index, chunk in enumerate(split_into_chunks(text or "")):
            await self.messenger.send_text(chat_id, chunk, reply_to if index == 0 else None)

    # ---- Telegram -> hub ---------------------------------------------------------
    async def on_command(self, chat_id: int, user_id: int, command: str, args: str, chat_type: str) -> None:
        if command == "pair":
            owner = self.pairing.owner
            if owner is not None and not self.pairing.authorized(chat_id, user_id, chat_type):
                return  # already somebody else's bot: say nothing
            _, text = self.pairing.try_pair(chat_id, user_id, (args or "").strip(), chat_type)
            await self.messenger.send_text(chat_id, text)
            return
        if not await self._allowed(chat_id, user_id, chat_type):
            return
        if command in ("start", "help"):
            await self._say(chat_id, HELP)
        elif command == "status":
            online = bool(getattr(self.hub, "connected", False))
            await self._say(chat_id, "The PC hub is online." if online else OFFLINE)
        elif command == "pending":
            await self._say(chat_id, self.desk.describe())
        elif command == "plugins":
            specs = self.plugins.get_functions_specs() if self.plugins else []
            names = [f"{s['name']} – {s.get('description', '')}" for s in specs]
            await self._say(chat_id, "Plugins:\n" + "\n".join(names) if names else "No plugins enabled.")
        elif command == "run":
            await self._run_plugin(chat_id, args or "")
        else:
            await self._say(chat_id, "Unknown command. /help")

    async def _run_plugin(self, chat_id: int, args: str) -> None:
        name, _, raw = args.strip().partition(" ")
        if not self.plugins or not name:
            await self._say(chat_id, "Usage: /run <function> [json arguments]")
            return
        try:
            result = json.loads(await self.plugins.call_function(name, None, raw or "{}"))
        except ValueError as exc:
            await self._say(chat_id, f"Bad arguments: {exc}")
            return
        direct = result.get("direct_result") if isinstance(result, dict) else None
        if direct and direct.get("kind") == "dice" and hasattr(self.messenger, "send_dice"):
            await self.messenger.send_dice(chat_id, direct.get("value"))
        else:
            await self._say(chat_id, json.dumps(result, ensure_ascii=False)[:4000])

    async def on_text(self, chat_id: int, user_id: int, text: str, chat_type: str,
                      reply_to: int | None = None) -> None:
        if not await self._allowed(chat_id, user_id, chat_type):
            return
        if await self._maybe_answer(chat_id, text, reply_to):
            return
        await self._request(chat_id, text)

    async def on_voice(self, chat_id: int, user_id: int, data: bytes, chat_type: str,
                       reply_to: int | None = None) -> None:
        if not await self._allowed(chat_id, user_id, chat_type):
            return
        try:
            wav = self.transcode(data)
        except AudioError as exc:
            await self._say(chat_id, f"Couldn't use that audio: {exc}")
            return
        try:
            reply = await self.hub.call("transcribe", timeout=60,
                                        audio_b64=base64.b64encode(wav).decode("ascii"), format="wav")
        except HubUnavailable:
            await self._say(chat_id, OFFLINE)
            return
        if reply.get("type") != "text":
            await self._say(chat_id, "Voice Vibe isn't running on the PC, so I can't transcribe voice notes.")
            return
        heard = (reply.get("text") or "").strip()
        if not heard:
            await self._say(chat_id, "I couldn't hear anything in that.")
            return
        if await self._maybe_answer(chat_id, heard, reply_to):
            return
        await self._say(chat_id, f"🎙 \"{heard}\"")
        await self._request(chat_id, heard)

    async def _maybe_answer(self, chat_id: int, text: str, reply_to: int | None) -> bool:
        """Answer a waiting approval if that's clearly what this is. True if consumed."""
        if not self.desk.pending:
            return False
        verdict = answers.parse(text)
        target = self.desk.by_message(reply_to) if reply_to is not None else None
        if target is not None:
            if verdict is None:
                await self._say(chat_id, f"I heard \"{text}\". Answer just yes or no, or tap a button.")
                return True
            await self._say(chat_id, await self.desk.decide(target.id, verdict, answer=text))
            return True
        if verdict is None:
            return False
        if len(self.desk.pending) == 1:
            only = next(iter(self.desk.pending))
            await self._say(chat_id, await self.desk.decide(only, verdict, answer=text))
            return True
        await self._say(chat_id, "Several approvals are waiting; reply to the card you mean with yes or no.")
        return True

    async def _request(self, chat_id: int, text: str) -> None:
        try:
            reply = await self.hub.call("request", timeout=25, text=text, context={}, source="telegram")
        except HubUnavailable:
            await self._say(chat_id, OFFLINE)
            return
        if reply.get("type") == "error":
            await self._say(chat_id, f"Hub error: {reply.get('message', 'unknown')}")
            return
        await self._say(chat_id, reply.get("text") or "(no reply)")

    async def on_callback(self, chat_id: int, user_id: int, data: str) -> str:
        if not self.pairing.authorized(chat_id, user_id, "private"):
            return ""
        return await self.desk.on_callback(data)

    # ---- hub -> Telegram ---------------------------------------------------------
    async def on_hub_message(self, msg: dict) -> None:
        kind = msg.get("type")
        owner = self.pairing.owner
        if kind == "approval_request":
            if owner is None:
                await self.hub.send(protocol.reply_to(msg, "approval_result", approved=False,
                                                      decided_by="bot", answer="no paired Telegram chat"))
                return
            await self.desk.open(msg, owner)
        elif kind == "notify":
            if owner is None:
                return
            icon = LEVEL_ICON.get(str(msg.get("level", "info")), "ℹ️")
            title = str(msg.get("title") or "Voice Vibe")
            await self._say(owner, f"{icon} {title}\n\n{msg.get('text', '')}".rstrip())
        elif kind == "ping":
            await self.hub.send(protocol.reply_to(msg, "pong"))
