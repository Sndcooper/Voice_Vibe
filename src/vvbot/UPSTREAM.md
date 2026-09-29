# vvbot provenance

Fork of **n3d1117/chatgpt-telegram-bot**, https://github.com/n3d1117/chatgpt-telegram-bot,
commit `df4dcaa26923dee560ef8f9b4f18a682c9b059ad` (2024-12-28), licence
**GPL-2.0-only** (copied unchanged to `LICENSE`). Everything in `src/vvbot/`
is distributed under GPL-2.0-only. It runs as a separate process and talks to
the hub only over the local WebSocket.

| File | Origin | Changes |
|---|---|---|
| `telegram_bot.py` | upstream `bot/telegram_bot.py` | OpenAI chat/Whisper/DALL-E/TTS/vision, budgets, inline mode, streaming removed; handlers call `core.BotCore`; approval-card callbacks; hub link started in `post_init`; `drop_pending_updates` |
| `__main__.py` | upstream `bot/main.py` | no `.env`; token from keyring; `set-token`/`pair`/`unpair`/`status` |
| `utils.py` | upstream `bot/utils.py` | kept `message_text`, `get_thread_id`, `is_group_chat`, `split_into_chunks`, `error_handler`; budget/allowlist code dropped; no telegram import |
| `plugin_manager.py` | upstream `bot/plugin_manager.py` | lazy, per-plugin imports; only `dice` vendored; run via `/run` |
| `plugins/plugin.py`, `plugins/dice.py` | upstream `bot/plugins/` | unchanged (header added) |
| `pairing.py` | new; pattern from NousResearch/hermes-agent `gateway/pairing.py` (MIT) @ `94f3f170d45add92ea3aa48063c444a985270acd` | single owner, code created on the PC, hash at rest |
| `core.py`, `approvals.py`, `answers.py`, `hub_client.py`, `audio.py` | new glue | hub `request`/`transcribe`, approval cards, strict yes/no, PyAV |

Not kept from upstream: `openai_helper.py`, `usage_tracker.py`,
`translations.json` (English only), the other plugins (they need API keys and
extra packages; add them back to `plugins/` + `PLUGIN_MAPPING` if wanted).

## Setup (user)
```
cd Voice_Vibe
uv pip install --python ..\venvs\telegram-bot\Scripts\python.exe -r src\vvbot\requirements.txt
src\vvbot\run.bat set-token      (paste the @BotFather token; stored in Credential Manager)
src\vvbot\run.bat pair           (prints /pair CODE; send it to the bot from your phone)
src\vvbot\run.bat                (runs the bot; needs the hub for anything but pairing)
```
