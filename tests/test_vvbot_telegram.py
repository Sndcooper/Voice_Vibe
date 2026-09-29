"""python-telegram-bot glue for the bot fork (src/vvbot/telegram_bot.py).

Runs only where python-telegram-bot is installed (venvs\\telegram-bot);
skipped in the app venv like the PySide tests. Builds the Application without
connecting, and drives the handlers with stand-in updates -- nothing reaches
Telegram.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    import telegram  # noqa: F401

    from vvbot import telegram_bot
except ImportError:  # the app venv doesn't carry the bot's dependencies
    telegram_bot = None


class Entity:
    offset = 0


class FakeBot:
    id = 42

    def __init__(self):
        self.calls = []

    async def send_message(self, **kw):
        self.calls.append(("send_message", kw))
        return NS(message_id=len(self.calls))

    async def edit_message_text(self, **kw):
        self.calls.append(("edit", kw))

    async def send_dice(self, **kw):
        self.calls.append(("dice", kw))


class RecordingCore:
    def __init__(self):
        self.calls = []

    async def on_command(self, *a):
        self.calls.append(("command", a))

    async def on_text(self, *a, **kw):
        self.calls.append(("text", a, kw))

    async def on_callback(self, *a):
        self.calls.append(("callback", a))
        return "Approved."


@unittest.skipIf(telegram_bot is None, "python-telegram-bot not installed (bot venv only)")
class TelegramGlueTests(unittest.TestCase):
    def test_messenger_card_has_inline_buttons(self):
        bot = FakeBot()
        m = telegram_bot.TelegramMessenger(bot)
        mid = asyncio.run(m.send_card(5, "Approve?", [("✅ Approve", "ap:x:y"), ("❌ Deny", "ap:x:n")]))
        self.assertEqual(mid, 1)
        kw = bot.calls[0][1]
        rows = kw["reply_markup"].inline_keyboard
        self.assertEqual([b.callback_data for b in rows[0]], ["ap:x:y", "ap:x:n"])
        self.assertNotIn("parse_mode", kw)

    def test_build_registers_handlers_without_network(self):
        app = telegram_bot.VoiceVibeTelegramBot({"token": "123456:TEST"}, pairing=None).build()
        handlers = [h for group in app.handlers.values() for h in group]
        kinds = {type(h).__name__ for h in handlers}
        self.assertEqual(kinds, {"CommandHandler", "MessageHandler", "CallbackQueryHandler"})
        commands = {c for h in handlers if type(h).__name__ == "CommandHandler" for c in h.commands}
        self.assertTrue({"pair", "pending", "status", "help"} <= commands)

    def test_handlers_route_to_core(self):
        vb = telegram_bot.VoiceVibeTelegramBot({"token": "123456:TEST"}, pairing=None)
        vb.core = RecordingCore()
        chat = NS(id=7, type="private")
        user = NS(id=7)
        ctx = NS(bot=FakeBot())

        msg = NS(text="/pair ABCD2345", parse_entities=lambda types: {Entity(): "/pair"},
                 reply_to_message=None, via_bot=None)
        asyncio.run(vb.command(NS(message=msg, effective_chat=chat, effective_user=user), ctx))
        self.assertEqual(vb.core.calls[-1], ("command", (7, 7, "pair", "ABCD2345", "private")))

        replied = NS(message_id=99, from_user=NS(id=42))
        msg = NS(text="yes", reply_to_message=replied, via_bot=None)
        asyncio.run(vb.prompt(NS(message=msg, edited_message=None, effective_chat=chat, effective_user=user), ctx))
        self.assertEqual(vb.core.calls[-1], ("text", (7, 7, "yes", "private"), {"reply_to": 99}))

        answered = []

        async def answer(text=None):
            answered.append(text)

        query = NS(data="ap:x:y", from_user=user, message=NS(chat=chat), answer=answer)
        asyncio.run(vb.callback(NS(callback_query=query), ctx))
        self.assertEqual(vb.core.calls[-1], ("callback", (7, 7, "ap:x:y")))
        self.assertEqual(answered, ["Approved."])


if __name__ == "__main__":
    unittest.main()
