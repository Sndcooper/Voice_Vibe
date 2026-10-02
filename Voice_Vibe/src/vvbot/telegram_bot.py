# Derived from n3d1117/chatgpt-telegram-bot @ df4dcaa26923dee560ef8f9b4f18a682c9b059ad
# (bot/telegram_bot.py), GPL-2.0-only -- see src/vvbot/LICENSE.
# Modified for Voice Vibe: ChatGPT/OpenAI (chat, Whisper, DALL-E, TTS, vision,
# budgets, inline mode, streaming edits) removed; text and voice notes go to
# the local hub through core.BotCore; voice-note download kept, pydub replaced
# by PyAV (audio.py); user-ID allowlist replaced by one paired chat
# (pairing.py); new approval cards with inline buttons (approvals.py) and hub
# notifications. Handler layout, commands registration and run() follow upstream.
from __future__ import annotations

import asyncio
import contextlib
import logging

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

from .core import BotCore
from .hub_client import HubClient
from .utils import error_handler, message_text

log = logging.getLogger(__name__)

MAX_MEDIA_BYTES = 10 * 2**20
SWEEP_SECONDS = 15


class TelegramMessenger:
    """core.BotCore's messenger, backed by a python-telegram-bot Bot. Plain text only,
    so hub text and previews can't inject Markdown."""

    def __init__(self, bot) -> None:
        self.bot = bot

    async def send_text(self, chat_id, text, reply_to=None):
        message = await self.bot.send_message(chat_id=chat_id, text=text, reply_to_message_id=reply_to,
                                              disable_web_page_preview=True)
        return message.message_id

    async def send_card(self, chat_id, text, buttons):
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data) for label, data in buttons]])
        message = await self.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)
        return message.message_id

    async def edit_text(self, chat_id, message_id, text):
        with contextlib.suppress(BadRequest):  # "message is not modified" / too old
            await self.bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id)

    async def send_dice(self, chat_id, emoji):
        await self.bot.send_dice(chat_id=chat_id, emoji=emoji)


class VoiceVibeTelegramBot:
    """
    Class representing the Voice Vibe Telegram bot.
    """

    def __init__(self, config: dict, pairing, plugins=None, hub_factory=HubClient):
        """
        :param config: {'token': bot token (from keyring)}
        """
        self.config = config
        self.pairing = pairing
        self.plugins = plugins
        self.hub_factory = hub_factory
        self.core: BotCore | None = None
        self.hub: HubClient | None = None
        self._tasks: list[asyncio.Task] = []
        self.commands = [
            BotCommand(command='help', description='Show help'),
            BotCommand(command='pending', description='Approvals waiting'),
            BotCommand(command='status', description='Is the PC hub online'),
            BotCommand(command='plugins', description='List plugins'),
            BotCommand(command='run', description='Run a plugin function'),
        ]

    # ---- updates -> core ---------------------------------------------------------
    @staticmethod
    def _who(update: Update):
        return update.effective_chat.id, update.effective_user.id, update.effective_chat.type

    @staticmethod
    def _reply_to(update: Update, context: ContextTypes.DEFAULT_TYPE):
        replied = update.message.reply_to_message if update.message else None
        if replied is not None and replied.from_user and replied.from_user.id == context.bot.id:
            return replied.message_id
        return None

    async def command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.message.text:
            return
        name = update.message.text.split()[0].lstrip('/').split('@')[0].lower()
        chat_id, user_id, chat_type = self._who(update)
        await self.core.on_command(chat_id, user_id, name, message_text(update.message), chat_type)

    async def prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        React to incoming messages and respond accordingly.
        """
        if update.edited_message or not update.message or update.message.via_bot:
            return
        chat_id, user_id, chat_type = self._who(update)
        await self.core.on_text(chat_id, user_id, update.message.text or '', chat_type,
                                reply_to=self._reply_to(update, context))

    async def transcribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Transcribe audio messages (through the hub, with Voice Vibe's Whisper).
        """
        if not update.message:
            return
        chat_id, user_id, chat_type = self._who(update)
        if not self.pairing.authorized(chat_id, user_id, chat_type):
            await self.core.on_voice(chat_id, user_id, b'', chat_type)  # lets core decline/ignore
            return
        attachment = update.message.effective_attachment
        if getattr(attachment, 'file_size', 0) and attachment.file_size > MAX_MEDIA_BYTES:
            await update.message.reply_text('That file is too big; keep voice notes under 10 MB.')
            return
        try:
            media_file = await context.bot.get_file(attachment.file_id)
            data = bytes(await media_file.download_as_bytearray())
        except Exception as e:  # noqa: BLE001
            logging.exception(e)
            await update.message.reply_text(f'Failed to download audio file: {e}')
            return
        await self.core.on_voice(chat_id, user_id, data, chat_type, reply_to=self._reply_to(update, context))

    async def callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        chat_id = query.message.chat.id if query.message else query.from_user.id
        toast = await self.core.on_callback(chat_id, query.from_user.id, query.data or '')
        with contextlib.suppress(BadRequest):
            await query.answer(text=toast or None)

    # ---- lifecycle -----------------------------------------------------------------
    async def post_init(self, application: Application) -> None:
        """
        Post initialization hook for the bot: connect to the hub, set commands.
        """
        messenger = TelegramMessenger(application.bot)
        self.hub = self.hub_factory(on_message=self._on_hub_message)
        self.core = BotCore(hub=self.hub, messenger=messenger, pairing=self.pairing, plugins=self.plugins)
        self._tasks = [asyncio.create_task(self.hub.run_forever()), asyncio.create_task(self._sweeper())]
        await application.bot.set_my_commands(self.commands)

    async def _on_hub_message(self, msg: dict) -> None:
        if self.core is not None:
            await self.core.on_hub_message(msg)

    async def _sweeper(self) -> None:
        while True:
            await asyncio.sleep(SWEEP_SECONDS)
            with contextlib.suppress(Exception):
                await self.core.desk.sweep()

    async def post_shutdown(self, application: Application) -> None:
        if self.hub is not None:
            await self.hub.stop()
        for task in self._tasks:
            task.cancel()

    def build(self) -> Application:
        application = ApplicationBuilder() \
            .token(self.config['token']) \
            .post_init(self.post_init) \
            .post_shutdown(self.post_shutdown) \
            .concurrent_updates(True) \
            .build()

        for name in ('start', 'help', 'pair', 'status', 'pending', 'plugins', 'run'):
            application.add_handler(CommandHandler(name, self.command))
        application.add_handler(MessageHandler(
            filters.AUDIO | filters.VOICE | filters.Document.AUDIO |
            filters.VIDEO | filters.VIDEO_NOTE | filters.Document.VIDEO,
            self.transcribe))
        application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), self.prompt))
        application.add_handler(CallbackQueryHandler(self.callback))
        application.add_error_handler(error_handler)
        return application

    def run(self):
        """
        Runs the bot indefinitely until the user presses Ctrl+C
        """
        # Drop updates queued while the bot was off: a stale "yes" must never
        # answer a card that didn't exist when it was sent.
        self.build().run_polling(allowed_updates=['message', 'callback_query'], drop_pending_updates=True)
