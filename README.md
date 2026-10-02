# Voice Vibe workspace

Voice Vibe is a local, Windows voice front door for a personal automation hub.
Press **Ctrl+Alt+W**, say "hey computer", then "computer &lt;task&gt;". Exact
commands (typing, keys, clicks, windows, apps) run locally; everything else goes
to **vvhub**, where a local model (**Laya**) decides what the request is, a
policy decides whether to ask you first, and a skill does the work. **Ctrl+Alt+Space**
is plain dictation with no commands.

This repo is the whole workspace: the app, the standalone transcriber, the
third-party repositories it builds on, and the working notes. Personal use only.

## Layout

| Path | What it is |
|---|---|
| `Voice_Vibe/` | The app. `src/voicevibe` is the front end (Whisper, commands, screen context, overlay), `src/vvhub` the hub and its skills, `src/vvbot` the Telegram bot (a GPL-2.0 fork, see its `UPSTREAM.md`), `integrations/opencli-plugins` the OpenCLI plugins. Has its own `README.md`, `docs/SETUP.md` and `THIRD_PARTY.lock`. |
| `VoiceVibe - transcriber/` | The original standalone dictation app: Ctrl+Alt+Space, Whisper, pastes into the focused field. No hub, no commands. |
| `Repos/` | Clones of the projects the app builds on or learns from, with their `.git` folders removed. Each commit is pinned in `Voice_Vibe/THIRD_PARTY.lock`. Each keeps its own licence. |
| `CONV.md`, `TASK.md` | The rulebook and the running log of the multi-chat build. |
| `RESEARCH.md`, `VOICEVIBE_STATUS.md` | Research and a status snapshot (2026-09-30). |
| `requirements.txt`, `requirements-windows-mcp.txt` | Install everything (below). |

### `Repos/`

| Repo | Licence | Used as |
|---|---|---|
| `laya` | Apache-2.0 | Installed (`laya==0.3.22`): local typed decisions |
| `Agent-Reach` | MIT | Installed from this folder: research readers |
| `Windows-MCP` | MIT | Reference; installed from PyPI as `windows-mcp==0.8.5` |
| `opencli` | Apache-2.0 | Reference; installed from npm as `@jackwener/opencli@1.8.8` |
| `freellmapi` | MIT | Reference; the app runs from its release build |
| `chatgpt-telegram-bot` | GPL-2.0 | Fork base of `Voice_Vibe/src/vvbot` |
| `tldr` | CC BY 4.0 | Source of the shell command catalog |
| `OpenJarvis`, `hermes-agent`, `munder-difflin` | Apache-2.0 / MIT / MIT | Reference only |
| `firecrawl` | **AGPL-3.0** | Reference only, never copy code from it |

## Install

Windows 11, [uv](https://docs.astral.sh/uv/), Node 20+, git. An NVIDIA GPU is
optional (without one, drop the `--extra-index-url` line in `requirements.txt`).
Run everything from this folder.

```powershell
# 1. Main environment: Voice Vibe, vvhub, Laya + torch, research, notes, reports, UI, bot
uv venv --python 3.11 venvs\voicevibe
uv pip install --python venvs\voicevibe\Scripts\python.exe -r requirements.txt

# 2. Windows-MCP lives in its own Python 3.13 environment
uv venv --python 3.13 venvs\windows-mcp
uv pip install --python venvs\windows-mcp\Scripts\python.exe -r requirements-windows-mcp.txt

# 3. OpenCLI (drives your logged-in Edge)
npm install --prefix venvs\node @jackwener/opencli@1.8.8
```

Then, once:

- **Laya model.** The first run downloads `convaiinnovations/laya` (about 0.8 GB)
  into the Hugging Face cache. To keep it with the workspace, set
  `HF_HOME` to `venvs\hf-cache` first. For CPUs without a GPU, build the INT8
  ONNX version with `Repos\laya\scripts\export_onnx.py --quantize` and put it
  in `venvs\models\laya\laya.int8.onnx`.
- **FreeLLMAPI** (text and vision for the hub): install the release listed in
  `Voice_Vibe/THIRD_PARTY.lock`, add your provider keys, and save its key with
  `Voice_Vibe\run.bat --set-key freellmapi`.
- **Edge extension** for OpenCLI, **Notion** and **Telegram** tokens: see
  `Voice_Vibe/docs/SETUP.md`. Secrets go into Windows Credential Manager, never
  into files.

## Run

```powershell
Voice_Vibe\run.bat                  # starts the hub, then Voice Vibe (tray icon + overlay)
python -m vvhub doctor              # from venvs\voicevibe: checks every component
"VoiceVibe - transcriber\run.bat"   # the standalone dictation app instead
```

`Voice_Vibe\run.bat --check` tests the microphone, GPU and clipboard. Quit with
Ctrl+Alt+Shift+Q or from the tray.

## Not in this repo

`venvs/` (environments, wheel cache, model weights: many GB, rebuilt by the steps
above), built executables (`dist/`, `build/`; the Airoot overlay is built from
`Voice_Vibe/assets`), logs, recordings, tokens and databases. Nothing here holds
credentials.

## Licences

The app's own code follows `Voice_Vibe/`. `Voice_Vibe/src/vvbot` is GPL-2.0-only.
Everything under `Repos/` keeps its upstream licence (see each folder). If you
redistribute this repo, mind that `firecrawl` is AGPL-3.0.
