# Architecture

Voice Vibe is a Windows application with independently running components:

1. `voicevibe`: microphone capture, local speech recognition, hotkeys, wake
   sessions, input insertion, tray and overlays. It remains usable without a hub.
2. `vvhub`: automation dispatch, local Laya routing when installed, approvals,
   screen context, skills, reports and the control-panel HTTP API. The server
   binds to `127.0.0.1:53874`; local clients authenticate with a bearer token.
3. `vvbot`: optional GPL-2.0-only Telegram bot, communicating with the hub over
   a local WebSocket. It pairs with one owner and handles phone approvals.
4. Airoot: optional standalone Qt overlay, built from source under `assets/`.

## Source map

| Path | Purpose |
| --- | --- |
| `src/voicevibe/` | Dictation, audio, transcribers, actions, session state |
| `src/vvhub/` | Hub, routing, policy, storage, secrets, scheduler |
| `src/vvhub/skills/` | Terminal, apps, GitHub, research, notes, social and reports |
| `src/vvhub/browser/` | OpenCLI and Windows-MCP subprocess adapters |
| `src/vvhub/ui/` | Control panel, launcher and static web assets |
| `src/vvbot/` | Telegram process and retained upstream license |
| `integrations/opencli-plugins/` | Project-specific browser commands |
| `assets/` | Overlay source/build spec, images and demo |
| `tools/` | Benchmarks, routing evaluation and shell catalog generation |
| `tests/` | Unit tests with faked desktop/account interactions |

## Data and dependencies

Runtime data is under `%LOCALAPPDATA%\VoiceVibe`: SQLite storage, local bearer
token, logs, history, reports and crops. Secrets are stored through `keyring`
in Windows Credential Manager (service `voicevibe`), not in Git. Histories have
retention rules; explicitly saved conversations are kept separately.

`pyproject.toml` defines Python dependencies and optional extras. Requirements
files select installation profiles without duplicating the package versions.
Model weights are downloaded separately and cached; installations and external
reference clones are not shipped. `THIRD_PARTY.lock` records their provenance.
The checked-in shell catalog is ready to use without cloning tldr-pages.

Speech recognition is local. Optional LLM providers, Telegram, Notion and web
skills communicate with external services when enabled. Review those settings
before using private text or screenshots with an integration.
