# Derived from n3d1117/chatgpt-telegram-bot @ df4dcaa26923dee560ef8f9b4f18a682c9b059ad
# (bot/main.py), GPL-2.0-only -- see src/vvbot/LICENSE.
# Modified for Voice Vibe: no .env / OpenAI settings; the bot token comes from
# Windows Credential Manager (keyring, service "voicevibe"), and the CLI adds
# set-token / pair / unpair / status.
"""python -m vvbot [run|set-token|pair|unpair|status]"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys

from vvhub import data_dir
from vvhub import secrets

from .pairing import CODE_TTL_SECONDS, Pairing

TOKEN_KEY = "telegram_bot_token"


def _setup_logging() -> None:
    log_dir = data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(log_dir / "vvbot.log", encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                        level=logging.INFO, handlers=handlers)
    # httpx logs every request URL, and Telegram URLs contain the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m vvbot", description="Voice Vibe Telegram bot")
    parser.add_argument("command", nargs="?", default="run",
                        choices=["run", "set-token", "pair", "unpair", "status"])
    parser.add_argument("--plugins", default=os.environ.get("VVBOT_PLUGINS", "dice"),
                        help="comma-separated upstream plugins to enable (default: dice)")
    args = parser.parse_args(argv)
    pairing = Pairing()

    if args.command == "set-token":
        token = getpass.getpass("Bot token from @BotFather (input hidden): ").strip()
        if ":" not in token:
            print("That doesn't look like a bot token.")
            return 1
        secrets.set(TOKEN_KEY, token)
        print("Saved to Windows Credential Manager (service 'voicevibe').")
        return 0
    if args.command == "pair":
        if pairing.owner is not None:
            print(f"Already paired with chat {pairing.owner}. Run `python -m vvbot unpair` first.")
            return 1
        code = pairing.new_code()
        print(f"Send this to your bot within {CODE_TTL_SECONDS // 60} minutes:\n\n    /pair {code}\n")
        return 0
    if args.command == "unpair":
        pairing.unpair()
        print("Unpaired. The bot answers nobody until you pair again.")
        return 0
    if args.command == "status":
        print(f"token: {'set' if secrets.get(TOKEN_KEY) else 'missing (python -m vvbot set-token)'}")
        print(f"paired chat: {pairing.owner or 'none (python -m vvbot pair)'}")
        return 0

    _setup_logging()
    token = secrets.get(TOKEN_KEY)
    if not token:
        logging.error("No bot token. Run `python -m vvbot set-token` first.")
        return 1
    from .plugin_manager import PluginManager
    from .telegram_bot import VoiceVibeTelegramBot

    plugins = PluginManager({"plugins": [p for p in args.plugins.split(",") if p]})
    VoiceVibeTelegramBot({"token": token}, pairing=pairing, plugins=plugins).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
