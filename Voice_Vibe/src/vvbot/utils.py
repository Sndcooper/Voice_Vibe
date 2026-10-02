# Derived from n3d1117/chatgpt-telegram-bot @ df4dcaa26923dee560ef8f9b4f18a682c9b059ad
# (bot/utils.py), GPL-2.0-only -- see src/vvbot/LICENSE.
# Modified for Voice Vibe: kept the helpers the fork still uses, dropped the
# budget/usage-tracker/allowlist code (pairing.py locks the bot to one chat),
# and compare chat types as strings so this imports without telegram.
from __future__ import annotations

import logging


def message_text(message) -> str:
    """
    Returns the text of a message, excluding any bot commands.
    """
    message_txt = message.text
    if message_txt is None:
        return ''

    for _, text in sorted(message.parse_entities(['bot_command']).items(),
                          key=(lambda item: item[0].offset)):
        message_txt = message_txt.replace(text, '').strip()

    return message_txt if len(message_txt) > 0 else ''


def get_thread_id(update) -> int | None:
    """
    Gets the message thread id for the update, if any
    """
    if update.effective_message and update.effective_message.is_topic_message:
        return update.effective_message.message_thread_id
    return None


def is_group_chat(update) -> bool:
    """
    Checks if the message was sent from a group chat
    """
    if not update.effective_chat:
        return False
    return update.effective_chat.type in ('group', 'supergroup')


def split_into_chunks(text: str, chunk_size: int = 4096) -> list[str]:
    """
    Splits a string into chunks of a given size.
    """
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]


async def error_handler(_: object, context) -> None:
    """
    Handles errors in the telegram-python-bot library.
    """
    logging.error(f'Exception while handling an update: {context.error}')
