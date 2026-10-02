# Voice Vibe — deep research: current system, what to add, target architecture

Written 2026-09-30 19:20 by the WS2 chat, from CONV.md, TASK.md, THIRD_PARTY.lock, the code at
`8a28161`, the live process list, and four parallel web-research passes. Not in git (memory
file, like CONV.md). Proposals here are **not decisions**: TASK.md stays the rulebook until
the user approves changes. Where a fact comes from web research and was not re-checked by
hand it is marked (web). Speech engines (STT, TTS, wake word, VAD) are WS6's research and
the control app is WS5's; they are referenced, not repeated.

## 0. Summary

**Where it stands.** Voice Vibe is two local processes plus helpers. `voicevibe` (the app you
talk to: Whisper dictation, "hey computer" sessions, exact local commands, screen context)
and `vvhub` (the brain: Laya routing, policy, approvals, 12 skills). FreeLLMAPI writes text,
OpenCLI drives Edge, Windows-MCP reads the desktop, a Telegram bot is the phone channel, a
pywebview control panel is the UI. Every stream (WS0–WS4) has shipped; WS5 (app) and WS6
(speech engines) are in progress. ~1073 tests pass.

**What limits "automate everything by voice" today.**
1. Skills cover only 8 areas (screen, research, notes, social, GitHub, code, app/windows,
   chat). Nothing yet for media, files, installing apps, mail/calendar/tasks, reminders,
   phone, smart home, or "any app / any website" in general.
2. One routing path. Laya's CPU (ONNX) tier drops action accuracy to 62.9% (GPU 94.6%) and
   uses 1.4 GB of the 1.5 GB budget.
3. No memory across days, no multi-step "and then" plans, no follow-up questions.
4. No voice identity: anyone near the mic in an open session can issue commands.
5. Three wiring gaps between hub and app (Telegram fallback, pin, mics — CONV.md Inbox 14:50).

**Top recommendations** (details in §2–§5):
1. **Router cascade**: hassil sentence templates → model2vec/semantic-router classifier
   trained on your own logged decisions → Laya → LLM. Cheaper and more accurate on CPU
   than Laya alone; Laya keeps the final say on anything critical.
2. **MCP tool host** in the hub: start servers on demand, least privilege, every write
   tool behind approvals. Unlocks Google Workspace / Microsoft 365, GitHub, Filesystem,
   Home Assistant, Todoist, Obsidian, Playwright, WinGet, Android without writing clients.
3. **Deterministic Windows actions first**: pycaw + WinRT media controls, voidtools
   Everything, WinGet, AutoHotkey v2, `ms-settings:` URIs. Fast, free, no LLM.
4. **Generic fallbacks, in order**: Playwright MCP (any website, accessibility tree) →
   Terminator record-and-replay (any desktop app) → UFO² vision agent (last resort).
5. **Memory**: sqlite-vec in hub.db + mem0 (library mode) for facts and preferences,
   plus an activity log of window titles/URLs for "what was I doing".
6. **Offline LLM fallback**: Ollama with Qwen3-4B (or 1.7B), loaded on demand, when
   FreeLLMAPI is exhausted.
7. **Voiceprint filter** (sherpa-onnx speaker embeddings): a filter, not authentication;
   critical actions keep approvals.
8. **Phone**: KDE Connect (notifications, SMS, find phone) + scrcpy / Android-MCP.
9. **Macros by voice**: "when I say start work, do X, Y, Z" — stored step lists replayed
   by the executor, approvals per critical step.
10. **Restructure** the hub into core / brain / tools / skills / memory / security /
    workflows packages (§4), done as one WS0-coordinated move, not piecemeal.

---

## 1. Current system (as built, 2026-09-30 ~19:15)

### 1.1 What runs

| Process | What it is | Where / port | Memory (measured) | Starts |
|---|---|---|---|---|
| Voice Vibe (`pythonw -m voicevibe`) | hotkeys, mic, faster-whisper, wake/session, exact commands, typing, orb, tray, screen context, hub link | tray app; no port | ≈706 MB with large-v3-turbo on GPU (09-29); VRAM ≈1.6 GB | `run.bat` / launcher; autostart opt-in (off) |
| Airoot overlay | the dancing logo | UDP 127.0.0.1:53873 | ≈135 MB | launched by Voice Vibe |
| vvhub (`pythonw -m vvhub serve`) | FastAPI + WebSocket brain, skills, store, scheduler, /ui API | 127.0.0.1:53874, bearer token | 539 MB working set now (19:15); Laya adds 1.07 GB (GPU) / 1.40 GB (ONNX) when loaded | launcher `hub` |
| FreeLLMAPI (Electron tray) | OpenAI-compatible router over free cloud LLMs | 127.0.0.1:3001 | 98 MB (19:15) | user starts it |
| OpenCLI daemon (node) | bridge to the Edge extension | 127.0.0.1:19825 | 43 MB (19:15) | auto on first OpenCLI call |
| Windows-MCP | UIA desktop tools over MCP stdio | venvs\windows-mcp, no port | on demand, ~1 s start | per call (screen skill, Zen) |
| Telegram bot (`vvbot`) | approvals, voice notes, notifications | venvs\telegram-bot | not measured | after the user pairs it |
| Control panel (pywebview) | Status, Mic, Services, Approvals, Chats, Logs, Reports, Settings | page served by the hub at /ui | 122 MB while open | tray "Control panel", `run.bat --ui` |

At 19:15 the hub, FreeLLMAPI and the OpenCLI daemon were listening; Voice Vibe itself was not
running (WS6 holds the live lock for benchmark recordings).

### 1.2 Request flow

```
mic → SegmentRecorder → faster-whisper (large-v3-turbo GPU / base.en for short commands)
  → armed? wait for "hey computer" → awake: next utterance is the request
  → "computer <text>":
       1. LocalScreen phrases (focus on my cursor, unfocus, what's this, private window)
       2. control.Router exact grammar + per-app profiles (scroll, tabs, click X, switch to…)
       3. session typing ("type …", "press enter"), "open X and …"
       4. else → hub_client → WS 127.0.0.1:53874 {request, text, context bundle}
            vvhub.dispatch:
              exact skill phrases → skill
              else smart_router: Laya level 1 (8 yes/no categories + risk, one pass)
                              → level 2 (actions of that category) → target
              policy (critical / low confidence / risk / forwarded words) → ask?
              approvals: voice confirm → Telegram card → UI → deny; timeout = deny
              skill.plan → skill.run (may send run_steps / get_context back to Voice Vibe)
            reply {text, speak} → Voice Vibe speaks it (SAPI) or types the original text
  hub down / not handled → typed exactly as heard (rule 8)
```

### 1.3 Code map (`Voice_Vibe\`)

| Folder | Modules | Owner |
|---|---|---|
| `src\voicevibe\` | app, audio, transcriber, wake, wakeword, hotkey, inserter, polish, vocab, suggest, history, config, control, actions, confirm, profiles, intent, launcher, winctl, uia, screen, context, focus, privacy, overlay, airoot, speaker, feedback, hub_client, selftest, cuda_setup | original + WS0/WS2 |
| `src\vvhub\` | server, protocol, bus, schemas, store, secrets, dispatch, doctor, scheduler, laya_engine, smart_router, policy, approvals, llm | WS0 / WS2 / WS4 |
| `src\vvhub\skills\` | app, browser, code, conversation, echo, github, notes, reports, research, screen, social, watchers | WS2 / WS3 / WS4 / WS0 |
| `src\vvhub\browser\` | drivers (Edge via OpenCLI, Zen via Windows-MCP), opencli, services, untrusted | WS3 |
| `src\vvhub\ui\` | api, chats, launcher, procs, services, settings, window + static page | WS5 |
| `src\vvhub\evals\` | runner + intents.jsonl (81 phrases) | WS2 |
| `src\vvbot\` | fork of chatgpt-telegram-bot: core, telegram_bot, approvals, pairing, answers, audio (PyAV), hub_client, plugin_manager | WS4 |
| `integrations\opencli-plugins\voicevibe\` | linkedin-post, instagram-notifications, github-notifications (JS) | WS3 |
| `tests\` | 58 test files, stdlib unittest + fakes | each owner |

### 1.4 Skills and actions registered today

| Skill [category] | Actions | Critical |
|---|---|---|
| app [app] | focus_window, list_mics, set_mic | — |
| browser [app] | open_website, summarize_page | — |
| code [code] | prompt, fix_this | — (forwarded critical words ask) |
| conversation [chitchat] | save_conversation | — |
| echo [chitchat] | ping | — |
| github [github] | status, list_prs, list_repos, create_branch, commit, push, create_repo, create_pr | push, create_repo, create_pr |
| notes [notes] | note_this, make_notes, save_transcript | — |
| reports [notes] | read_report, report_now | — |
| research [research] | research, research_status | — |
| screen [screen] | explain, summarize, read, focus, unfocus | — |
| social [social] | linkedin_post, instagram_post, linkedin_feed, linkedin_messages, instagram_notifications | linkedin_post, instagram_post |
| watchers [github] | check_now | — |

Plus Voice Vibe's local grammar (no hub): editing, scrolling, tabs, windows, switch to X,
click-by-name, numbered hints, OCR click, volume/media keys, lock, open apps, spoken edits,
and per-app profiles for Explorer, Zen, Claude, ChatGPT.


### 1.5 Third-party repos (`Repos\`, pinned in `THIRD_PARTY.lock`)

| Repo | Pin | Licence | Used as | How it runs |
|---|---|---|---|---|
| NandhaKishorM/laya | 6d942c9 (PyPI 0.3.22) | Apache-2.0 | every routing / validation decision | in the hub process; GPU torch or ONNX INT8 |
| tashfeenahmed/freellmapi | 6def0ff (v0.13.2) | MIT | text + vision generation only | Electron tray app, :3001 |
| jackwener/opencli | 2413694 (v1.8.8) | Apache-2.0 | Edge automation, LinkedIn built-ins, Codex `send`, plugins | node CLI + daemon :19825 + Edge extension |
| CursorTouch/Windows-MCP | 30c1472 (v0.8.5) | MIT | region Snapshot, Zen DOM | MCP stdio, on demand, telemetry off |
| Panniantong/Agent-Reach | a19a171 (1.5.0) | MIT | web / RSS / GitHub / YouTube readers for research | Python package in venvs\voicevibe |
| n3d1117/chatgpt-telegram-bot | df4dcaa | GPL-2.0 | vendored as `src\vvbot` (licence kept) | venvs\telegram-bot |
| open-jarvis/OpenJarvis | 5e5f5ef | Apache-2.0 | reference: digest + research flow | not installed |
| NousResearch/hermes-agent | 94f3f17 | MIT | reference: gateway pairing/approvals | not installed |
| chaitanyagiri/munder-difflin | ed06e3e | MIT code, LimeZu assets | office-view renderer (WS5 T20) | to be ported as web code |
| firecrawl/firecrawl | b5d187b | AGPL-3.0 | reference only, never copied | not installed |
| tldr | (WS1 clone) | see lock | reference | not installed |

### 1.6 Dependencies

**venvs\voicevibe** (CPython 3.11.16, uv, pinned). Base: faster-whisper 1.2.1, ctranslate2 4.8.2,
sounddevice 0.5.6, numpy 2.2.6, pynput 1.8.2, pyperclip 1.9.0, pystray 0.19.5, pillow 11.3.0,
psutil 7.2.2. Extras in `pyproject.toml`:

| Extra | Packages | For |
|---|---|---|
| cuda | nvidia-cublas-cu12 12.9.1.4, nvidia-cudnn-cu12 9.13.1.26 | Whisper on GPU |
| screen | comtypes 1.4.17, uiautomation 2.0.29, winsdk 1.0.0b10 / winrt-* 3.2.1 | UIA, OCR |
| wakeword | openwakeword 0.6.0 (+ onnxruntime 1.30.0) | wake word engine |
| tts | soprano-tts 0.2.0 | speak hotkey |
| hub | fastapi 0.142.0, uvicorn 0.54.0, websockets 17.1, keyring 25.7.0 | vvhub |
| reports | apscheduler 3.11.0, jinja2 3.1.6 | 08:00/20:00 reports |
| web | trafilatura 2.2.0, notion-client 3.1.0, mcp 2.2.0 | WS3 skills, MCP client |
| brain | laya 0.3.22, torch 2.11.0 (+cu128 here), transformers 5.17.0, safetensors 0.8.0, httpx 0.28.1 | Laya, FreeLLMAPI client |
| (WS5) | pywebview 6.2.1 | control panel |

**Other environments**: `venvs\windows-mcp` (Python 3.13, windows-mcp 0.8.5),
`venvs\telegram-bot` (python-telegram-bot fork deps, websockets 17.1, keyring 25.7.0, PyAV),
`venvs\node` (npm prefix: @jackwener/opencli 1.8.8), `venvs\freellmapi` (desktop app),
`venvs\bench` (WS6), `venvs\uv-cache`, `venvs\wheelhouse` (offline reinstall).

### 1.7 Models, data and secrets

| Item | Where | Size / note |
|---|---|---|
| Whisper large-v3-turbo, base.en, tiny.en | venvs\hf-cache | main + short-command models |
| Laya english + multilingual checkpoints | venvs\hf-cache (convaiinnovations/laya) | 843 MB + 644 MB; only english is used |
| Laya INT8 ONNX | venvs\models\laya\laya.int8.onnx | ≈600 MB; CPU tier |
| openWakeWord hey_jarvis | in the package | no "hey computer" model exists |
| Data root | `%LOCALAPPDATA%\VoiceVibe\` | hub.db (SQLite WAL), hub.token, logs\, history\ (2 days) + history\saved\ (forever), crops\ (2 days), prompts\ (2 days), reports\, code.json, watchers.json |
| Secrets | Windows Credential Manager, service `voicevibe` | `freellmapi_key`, `notion_token`, `telegram_bot_token` (+ pairing owner); none set yet |

### 1.8 Known gaps and blockers (2026-09-30 evening)

| Gap | Effect | Owner |
|---|---|---|
| hub `confirm` gets `approved:false` instead of `unavailable:true` when no session listens | approvals are denied instead of going to Telegram | WS0 (Inbox 14:50) |
| `get_context` drops `pin` | hub-side focus/unfocus don't pin (the local phrase works) | WS0 |
| no `list_mics` / `set_mic` handlers | "use the jack microphone" via the hub fails | WS0 |
| no `python -m vvhub eval` | use `python -m vvhub.evals` | WS0 |
| ONNX tier: category 86.4%, **action 62.9%**, 1.40 GB | CPU laptops route poorly and fill the RAM budget | WS2 (§2.4, §5 P1) |
| routing misses 1/10 critical ("send a message to Rahul on LinkedIn" → reads messages) | would be asked anyway only if another rule fires | WS2 |
| user setup: FreeLLMAPI unified key, Edge extension, Notion token, Telegram pairing | social / notes / explain / phone approvals untested live | user |
| ChatGPT-desktop profile also matches the Codex app (both ChatGPT.exe) | wrong shortcuts in Codex | user decision |
| no wake-word model for "hey computer" | Whisper engine does wake detection (costly) | WS6 |


---

## 2. Research: repos worth adding (2026-09-30, web)

Verdicts: **adopt** = build on it now; **trial** = spike behind a flag, measure; **watch** =
revisit later; **skip** = not for us (reason given). RAM is the researchers' estimate unless
it says measured. Licences and activity were checked on each project page during the
research passes but not re-verified by hand.

### 2.1 Desktop and browser automation ("any app, any website")

| Project | Licence | What it gives | Fit / RAM | Verdict | Plugs in as |
|---|---|---|---|---|---|
| AutoHotkey v2 | GPL-2.0 (separate process) | hotkeys, Send, window/media control, ControlClick | native, ~5 MB | **adopt** | `connectors/ahk` action backend; push-to-talk key |
| voidtools Everything + ES CLI | freeware + MIT CLI | instant file search by name/date/type | tens of MB, Everything must run | **adopt** | `files` skill: "open last week's invoice PDF" |
| WinGet (+ `winget mcp`) | MIT | find / install / upgrade / uninstall apps | built in | **adopt** | `system.install` (install/uninstall = critical) |
| microsoft/playwright-mcp | Apache-2.0 | browser tools on the accessibility tree; `--extension` attaches to the logged-in profile | node ~200 MB + browser, on demand | **trial** | generic web fallback when no OpenCLI adapter exists |
| mediar-ai/terminator | MIT | UIA SDK + MCP: record a workflow once, replay deterministically, AI only on failure | Windows-only, active | **trial** | `workflows` replay engine for desktop apps |
| pywinauto | BSD-3 | in-process UIA/Win32 by name / AutomationId | ~50 MB, slow releases | **trial** | deterministic per-app skills |
| microsoft/UFO (UFO²) | MIT | full Windows agent over UIA + Win32 + COM, multi-app plans | ~0.5 GB, needs a vision LLM (FreeLLMAPI) | **trial** | last-resort `desktop.agent`; approvals enforced by the hub, not by UFO |
| microsoft/OmniParser v2 | code CC-BY-4.0, weights MIT (old detectors AGPL) | screenshot → clickable boxes where UIA is blind (canvas, games, RDP) | 2–3 GB, slow on CPU | watch | vision parse fallback |
| bytedance/UI-TARS-desktop | Apache-2.0 | vision-only GUI agent + CLI/MCP | 7B model wants a GPU | watch | possible grounding model later |
| simular-ai/Agent-S3 | Apache-2.0 | top OSWorld agent | needs a hosted grounding model; exec()s generated code | watch | — |
| browser-use | MIT | autonomous web agent reusing the Chrome profile | ~0.5 GB + browser | watch | hard to pause for approval mid-run |
| PowerToys (Command Palette, Workspaces) | MIT | launcher extensions, window layouts | 100–300 MB if resident | watch | Workspaces for "set up my coding layout" |
| yuka-friends/Windrecorder | GPL-2.0 | local screen history + Windows OCR search | 10–20 GB/month video, pauses idle | trial (opt-in) | "what error did I see at 3?" |
| Screenpipe | now source-available commercial | 24/7 screen + audio memory, MCP | 0.5–3 GB, analytics on | watch | too heavy for the budget |
| Stagehand / Skyvern / Open Interpreter / OpenRecall | MIT / AGPL / Apache / AGPL | overlap or stale / heavy (Docker+Postgres) / no desktop control now / unmaintained | — | skip | — |

Order to try for any action: **deterministic skill (AHK, pywinauto, Everything, WinGet,
settings URIs) → OpenCLI adapter → accessibility tree (Windows-MCP, Playwright MCP,
Terminator) → vision agent (UFO²)**. Vision agents spend many screenshots per task on the free
LLM pool and are the least predictable, so they go last and never hold post/send/pay tools.

### 2.2 Voice-assistant patterns and voice security (not engines)

| Project | Licence | What we take | Fit / RAM | Verdict | Plugs in as |
|---|---|---|---|---|---|
| OHF-Voice/hassil (+ HA intents) | Apache-2.0 | sentence templates: alternatives, optionals, `{slot lists}`, ranges, wildcards, context-gated intents | pure Python, tiny | **adopt** | router stage 0 (exact templates, slot filling) |
| aurelio-labs/semantic-router | MIT | embedding routes, per-route thresholds, "none" route, local mode | ~100–250 MB with a small encoder | **adopt** (pinned) | router stage 1 pre-filter |
| k2-fsa/sherpa-onnx (speaker ID only) | Apache-2.0 | ONNX speaker embeddings + verify/identify, no torch | ~50–150 MB, Windows wheels | **adopt** | `security/voiceprint` score on every command |
| wenet-e2e/wespeaker | Apache-2.0 | better speaker-embedding models (CAM++, ResNet) exported to ONNX | torch only to export | trial | voiceprint model source |
| SpeechBrain ECAPA-TDNN | Apache-2.0 | reference verifier (0.80% EER VoxCeleb1) | torch ≈0.5 GB | trial (offline) | enrolment + threshold calibration script |
| pipecat-ai/pipecat (+ flows) | BSD-2 | barge-in, turn-taking, node-based follow-up questions | 150–300 MB | trial (patterns) | `conversation/` design |
| OpenVoiceOS intent pipeline | Apache-2.0 | confidence tiers (`high → converse → low → fallback`), active skill gets the next utterance first | pure-Python plugins | trial (plugins/patterns) | router tiers + follow-ups |
| OHF-Voice/wyoming | MIT | JSONL + PCM event schema, multiple intents per request, context round-trip | tiny, no auth | trial (as schema) | lets wyoming-* servers plug in later |
| Talon Voice + Cursorless | Talon closed freeware; Cursorless MIT | explicit modes (command / dictation / sleep), per-app grammars, voice coding | takes the mic | trial (coding mode only) | "coding mode": Voice Vibe sleeps, Talon listens |
| clovaai/AASIST | MIT | tiny synthetic-speech (deepfake) detector | tiny, research code | watch | extra signal, never a gate |
| LiveKit Agents / Leon 2.0 / Rhasspy 3 / Dicio / Serenade / Resemblyzer / pyannote / Voice Access | various | patterns only / archived / Android / stale / heavy / no API | — | skip (copy ideas) | — |

Findings that change our design:
- **A voiceprint is a filter, not authentication.** Replays and clones fool ECAPA-class
  verifiers, and deepfake detectors are trained on synthetic speech, not replays through a
  speaker. Keep approvals (voice + Telegram) for post / push / send / delete / pay; use the
  voiceprint to drop other people's commands and to raise risk when the score is low.
- **Short commands verify worse than benchmark EERs.** Enrol 30–60 s across mics and rooms;
  score wake phrase + command together; calibrate on the user's own false accepts.
- **Browsers can open ws://127.0.0.1.** CORS doesn't apply to WebSockets. The hub already
  requires the token in the first `hello`; also check `Origin` and reject browser origins.
- **Embedding routers misroute multi-step or out-of-scope requests.** Require a threshold
  *and* a margin over the runner-up *and* a "none" route; send "and then / after that" to
  Laya/LLM for a typed step list.


### 2.3 Integrations for everyday life (mostly MCP servers the hub can host)

The hub already ships the MCP Python client (`mcp` 2.2.0). Each server below is a separate
process: start it per request, stop it when idle, start read-only or allow-listed, and route
every write tool through `approvals`.

| Project | Licence | Gives | Account | Verdict | Plugs in as |
|---|---|---|---|---|---|
| pycaw | MIT | master / per-app volume, mute, output devices | none | **adopt** | `media.volume` |
| pywinrt `winrt-Windows.Media.Control` | MIT | now playing, play / pause / next for Spotify, Edge, any app with system media controls (winsdk successor) | none | **adopt** | `media.transport` |
| modelcontextprotocol/servers (Filesystem, Fetch, Time, Git) | MIT → Apache-2.0 | files in allowed folders, fetch pages, time zones | none | **adopt** (Filesystem, Time) | `files`, `time` |
| taylorwilsdon/google_workspace_mcp | MIT | Gmail, Calendar, Drive, Docs, Sheets, Tasks, Contacts; `--read-only`, `--tools` filter | own Google OAuth client | **adopt** (if Google) | `mail`, `calendar`, `tasks`, `drive` |
| Softeria/ms-365-mcp-server | MIT | Outlook, Calendar, OneDrive, OneNote, To Do, Contacts (personal accounts); read-only mode | Microsoft account | **adopt** (if Outlook) | same skills, MS backend |
| github/github-mcp-server | MIT | issues, PRs, Actions, repos; toolsets, read-only | PAT | trial (gh CLI covers basics) | `github` extras (issues, CI status) |
| Home Assistant MCP Server (official) | Apache-2.0 | control exposed entities + live state at `/api/mcp` | HA on another box (Pi / mini-PC) | adopt **if** you have smart devices | `home` |
| Doist todoist MCP (official) | MIT | tasks and projects | Todoist token | trial | `tasks` (Todoist backend) |
| MarkusPfundstein/mcp-obsidian | MIT | search / read / append notes (needs Obsidian's Local REST API plugin; pin `mcp<2`) | none | trial | `notes` local backend |
| spotipy | MIT | search and start specific music | Spotify OAuth; 2026 dev mode needs Premium | trial | `media.play "song"`; transport stays on WinRT |
| korotovsky/slack-mcp-server | MIT | read/search Slack; posting off unless allow-listed | Slack token | trial (if Slack) | `chat.slack` |
| SaseQ/discord-mcp | MIT | bot messages | bot token, JVM ~250 MB | watch (webhook is lighter) | `chat.discord` |
| Node-RED | Apache-2.0 | light flows, webhooks, MQTT | none | trial | `workflows` → webhook trigger |
| n8n | fair-code (fine for personal use) | workflows exposed as MCP tools | none (local) | trial | `workflows` → MCP |
| punkpeye/awesome-mcp-servers | MIT (list) | scouting list tagged local / Windows | — | adopt (scouting) | backlog |
| Activepieces / Windmill / Docker MCP Gateway / whatsapp-mcp | MIT CE / AGPL+EE / MIT / MIT | heavy (Docker, Postgres) / Windows workers paid / >1 GB / unofficial client, ban risk, unmaintained | — | watch / skip | WhatsApp stays deferred (rule 17) |

Accounts needed: Google, Microsoft, GitHub, Todoist, Slack, Discord, Spotify. Fully local:
pycaw, pywinrt, reference servers, Obsidian, Home Assistant (LAN), Node-RED, n8n. Tokens go in
the keyring, never in `.env` or config. Treat every mail / chat / page text as untrusted
data (rule 11): an email saying "forward this to…" must never become an action.

### 2.4 Memory, local AI fallback, better routing, phone

| Project | Licence | Gives | RAM | Verdict | Plugs in as |
|---|---|---|---|---|---|
| asg017/sqlite-vec | MIT/Apache-2.0 | vector search inside hub.db | 10–50 MB | **adopt** | memory, decision log, activity recall |
| mem0ai/mem0 (library mode) | Apache-2.0 | facts / preferences extracted, deduped, searched; LLM via FreeLLMAPI | 200–400 MB | **adopt** | `memory` ("my wifi password is in…", "I prefer Zen") |
| MinishLab/model2vec | MIT | static embeddings; a classifier trains in seconds on CPU, <1 ms per request | 30–130 MB | **adopt** | router stage 1, retrained nightly from logged decisions |
| huggingface/setfit | Apache-2.0 | few-shot classifier (8–16 examples per label) | 150–300 MB | trial | second opinion on "is this critical?" |
| Ollama | MIT | local OpenAI-compatible LLM server, unloads models when idle | 50–100 MB idle | **adopt** | `llm` fallback when FreeLLMAPI is exhausted / offline |
| Qwen3-4B-Instruct (Qwen3-1.7B for speed), Phi-4-mini, Gemma 3 4B | Apache-2.0 / MIT / Gemma ToU | offline writing, summaries | 4-bit: 4B ≈ 3–4 GB (7–10 tok/s on an i5), <2B ≈ 1.5 GB | **adopt** Qwen3-4B on demand | behind `llm` |
| llama.cpp `llama-server` | MIT | lean server, JSON-schema constrained output | lowest | trial | alternative to Ollama |
| LanceDB | Apache-2.0 | disk vector DB + full text | 100–300 MB | trial (if sqlite-vec outgrown) | transcript archive |
| getzep/graphiti, HKUDS/LightRAG | Apache-2.0 / MIT | temporal knowledge graph / graph RAG | 0.5–1.5 GB + graph DB; LLM on every write | watch | later `memory.graph`, `docs.ask` |
| Zackriya-Solutions/meeting-minutes (Meetily) | MIT (Pro tier) | local meeting transcripts + summaries | 1–2 GB while recording; own STT | trial | `meeting` skill → notes |
| KDE Connect (Windows) | GPL | phone notifications, SMS, clipboard, ring phone, run PC commands from the phone | 100–150 MB | **adopt** | `phone` skill via `kdeconnect-cli` |
| Genymobile/scrcpy | Apache-2.0 | mirror + control Android over ADB | 0 idle | **adopt** (on demand) | `phone.screen` |
| CursorTouch/Android-MCP | MIT | MCP tools over ADB: screen state, tap, type, swipe | 100–150 MB, 2–4 s/action | trial | `phone.agent` |
| Letta, Khoj, Chroma, Screenpipe, OpenRecall, Phone Link | — | duplicate server / AGPL + Postgres / redundant / paid / stale / no API | — | skip | — |

Laya itself: refit its temperatures on held-out logged decisions (cheap, CPU) so its
confidence means something, and fine-tune the typed-decisions checkpoint on our own
(utterance → approved skill/action) pairs on a free GPU notebook (the model card reports
0.362 → 0.766 on its benchmark from fine-tuning). The first-stage classifier must never
auto-approve post / push / send / delete / pay on its own.


---

## 3. What becomes possible: voice-only automation catalogue

"Risk" is how policy would treat it: **auto** = acts as you; **ask** = approval first
(rule 10's critical list, plus installs, file deletes, killing apps, power actions, phone
messages). "Needs" = new code; ✔ = already works today.

| Domain | Say it like this | Backend | Risk | Needs |
|---|---|---|---|---|
| Windows & apps | "open Spotify", "switch to VS Code", "snap left", "close this" | launcher, winctl, Router | auto | ✔ |
| | "set up my coding layout" (VS Code left, terminal right, Zen on screen 2) | winctl + stored layout / PowerToys Workspaces | auto | `layouts` in workflows |
| | "install OBS", "update everything", "uninstall Photoshop Express" | WinGet (+ `winget mcp` search) | ask | `system` skill |
| System settings | "turn on dark mode", "open Bluetooth settings", "night light on" | `ms-settings:` URIs, registry via PowerShell (allow-listed) | auto / ask | `system` skill |
| | "Wi-Fi off", "Bluetooth on", "airplane mode" | WinRT `Windows.Devices.Radios` (desktop access to be checked) | auto | `system` |
| | "sleep", "restart", "shut down in 10 minutes" | `shutdown.exe`, LockWorkStation | ask | `system` |
| | "battery?", "what's using my CPU", "free disk space" | psutil | auto | `system` |
| | "kill Chrome" | psutil terminate | ask | `system` |
| Media | "pause", "next song", "what's playing", "volume 30", "mute Discord" | WinRT media controls, pycaw | auto | `media` skill |
| | "play lo-fi on Spotify", "play Arijit Singh" | spotipy (Premium) or OpenCLI on open.spotify.com | auto | `media` |
| Files | "find the invoice PDF from last week", "open my resume" | Everything ES | auto | `files` skill |
| | "move this to Documents\Taxes", "rename it to report-final", "zip these" | Explorer selection via UIA + Filesystem MCP (allowed dirs) | auto | `files` |
| | "delete these screenshots", "empty the recycle bin" | same | ask | `files` |
| | "clean up my Downloads" (sort by type/date) | rules + preview | ask (shows the plan) | `files` |
| Web | "open LinkedIn in Zen", "summarize this page" | browser skill | auto | ✔ |
| | "on amazon.in search for a USB-C hub under 2000 and open the top 3" | Playwright MCP / OpenCLI browser primitives | auto (buy = ask) | `web.generic` |
| | "fill this form with my details" | Playwright MCP + memory (address, email) | ask before submit | `web.generic` + memory |
| Mail | "any important mail?", "read the mail from Priya", "draft a reply saying I'll join" | Google Workspace / MS 365 MCP + FreeLLMAPI draft | read auto, **send ask** | `mail` skill |
| Calendar & tasks | "what's on today", "move my 3 pm to Friday", "remind me to call mom at 7", "add milk to my list" | Workspace/365 MCP, Todoist MCP, APScheduler | auto (invites to others = ask) | `calendar`, `tasks`, `reminders` |
| Timers | "timer 10 minutes", "wake me at 6:30", "every weekday at 9 open standup notes" | APScheduler (exists for reports) | auto | `reminders` |
| Messaging | "message Rahul on LinkedIn: see you at 5" | social skill (exists: posts; DMs to add) | ask | `social` extension |
| | "reply on Slack: on it" / Discord | Slack / Discord MCP | ask | `chat` |
| | "read my new WhatsApp" | deferred (ban risk) | — | — |
| Phone | "what's on my phone", "read my last SMS", "text Mom I'm late", "find my phone", "send this file to my phone" | KDE Connect CLI | read auto, **SMS ask** | `phone` skill |
| | "on my phone open Swiggy and reorder" | scrcpy + Android-MCP | ask per step | `phone.agent` |
| Coding | "ask Claude to add tests", "fix this with Kiro", "in VS Code terminal run the tests" | code skill | auto (forwarded push = ask) | ✔ (+ run tests) |
| | "create a repo called X and push", "open a PR" | github skill | ask | ✔ |
| | "what failed in CI?", "summarize issue 42" | github-mcp-server | auto | `github` extras |
| Screen | "explain this", "what's this", "focus on my cursor", "read this out" | screen skill, LocalScreen | auto | ✔ (explain needs FreeLLMAPI key) |
| | "what error did I see at 3 pm?", "what was I doing before lunch" | activity log (window titles/URLs) → sqlite-vec; optional Windrecorder | auto | `recall` |
| Notes & knowledge | "note this", "make notes about the meeting", "what did I save about Laya?" | notes skill + memory search | auto | ✔ + `memory` |
| | "remember my car's service is due in March" / "what's my passport number stored as" | mem0 + sqlite-vec (secrets stay in keyring) | auto | `memory` |
| Meetings | "start meeting notes", "summarize the call", "send the action items to Notion" | Whisper (already loaded) or Meetily → FreeLLMAPI → notes | auto (sharing = ask) | `meeting` |
| Research | "research budget laptops and put it in Notion" | research skill | auto | ✔ |
| Smart home | "lights off", "AC to 24", "is the door locked" | Home Assistant MCP | auto (locks/alarms = ask) | `home` |
| Macros | "when I say 'start work', open VS Code, play my focus playlist and mute notifications" → "start work" | stored step lists (actions.py specs + skill calls) | ask when saving, per-step rules at run | `workflows` |
| | "record what I do" … "save it as 'export report'" | Terminator record/replay | ask when saving | `workflows` |
| Multi-step | "open Chrome, go to Gmail and search invoices" | planner: Laya/LLM → typed step list, each step checked by policy | per step | `conversation/planner` |
| Follow-ups | "remind me" → "when?" → "at 7" | conversation state (active skill gets the next utterance) | — | `conversation` |
| Daily brief | 08:00 / 20:00 report, spoken on next arm | reports skill | auto | ✔ |
| | "good morning": weather, calendar, mail count, GitHub, reminders | reports + mail/calendar + Fetch | auto | `briefing` |
| Utilities | "what's 18% of 2450", "convert 5 miles to km", "translate this to Hindi", "spell 'necessary'" | local Python / FreeLLMAPI | auto | `utility` skill |
| Accessibility | "show numbers" → "click 7", "scroll down", "read the answer" | Router + badges | auto | ✔ |
| Modes | "coding mode" (hand the mic to Talon), "dictation mode", "go to sleep" | mode switch in Voice Vibe | auto | `modes` (WS6/WS0) |

Guardrails that make "voice only" safe:
1. Everything scraped (mail, pages, chats, screen text) is data: it can be read, summarised
   or quoted, never turned into an action (rule 11; already enforced in WS3/WS2 skills).
2. Critical = rule 10 list **plus** install/uninstall, file delete, kill process, power off,
   SMS/phone messages, form submits, calendar invites to others, smart locks/alarms.
3. Voiceprint mismatch → no auto actions at all, only "Sorry, I didn't catch that."
4. Every new connector starts read-only; write tools are added one by one with tests.


---

## 4. Proposed target folder architecture

Goals: every new capability has an obvious home; connectors (how we reach a tool) are
separate from skills (what the user asked for); the brain (routing, policy, approvals) is
one package; nothing breaks for the streams working today. **Proposal only** — the move is a
WS0 change to TASK.md §3/§4 and needs the user's go-ahead. Skill auto-discovery already
works for this layout: `pkgutil.iter_modules` also lists sub-packages, so
`skills/media/__init__.py` exposing `SKILL` registers without touching the registry.

```
voicevibe\                              workspace (not a repo)
  CONV.md  TASK.md  RESEARCH.md
  Repos\                                clones, pinned (unchanged)
  venvs\                                envs + caches (unchanged; + models\ for Qwen/ONNX/voiceprint)
  Voice_Vibe\                           the only git repo
    src\voicevibe\                      the app you talk to (stays light: no hub deps)
      app.py  __main__.py  config.py    entry + wiring
      audio\        recorder, devices                       (from audio.py)
      speech\       transcriber, wake, wakeword, vocab, polish, suggest
        engines\    stt\ tts\ vad\ wake\                    (WS6 plugs engines in here)
      input\        actions, inserter, hotkey, confirm
      control\      router (control.py), profiles, intent, launcher, winctl, modes (new)
      screen\       screen, uia, context, focus, privacy
      ui\           overlay, airoot, feedback (tray)
      link\         hub_client
      security\     voiceprint (new: enrol, score, per-utterance tag)
      history.py  selftest.py  cuda_setup.py
    src\vvhub\                          the brain
      core\         server, protocol, bus, schemas, store, secrets, doctor, scheduler, dispatch
      brain\        laya_engine, llm, policy, approvals
        router\     templates (hassil) → semantic (model2vec) → laya → planner (multi-step)
      conversation\ state, follow-ups ("when?" → "at 7"), active skill, barge-in / stop
      memory\       vectors (sqlite-vec in hub.db), facts (mem0), activity log, recall
      security\     ws origin check, voiceprint policy, audit log of every action
      tools\        MCP host: on-demand start/stop, per-server allow-lists, idle reaper
      connectors\   windows_mcp, opencli, playwright, terminator, ahk, everything, winget,
                    pycaw/media, kdeconnect, adb, homeassistant, google, ms365, todoist,
                    ollama (each: thin, testable, fakeable, no skill logic)
      browser\      (existing WS3 layer; later folded into connectors\)
      workflows\    macros (store, validate, replay), recorder bridge, webhooks (n8n/Node-RED)
      skills\       one module or package per domain
        existing:   app browser code conversation echo github notes reports research
                    screen social watchers
        new:        system media files mail calendar tasks reminders phone home meeting
                    recall utility briefing web_generic desktop_agent
      ui\  evals\   (existing WS5 / WS2)
    src\vvbot\                          Telegram bot (unchanged)
    integrations\
      opencli-plugins\                  (existing)
      ahk\                              AutoHotkey v2 scripts the ahk connector runs
      mcp\                              one manifest per MCP server: command, pinned version,
                                        allowed tools, read-only flag, env names (no secrets)
      workflows\                        example macros (JSON) shipped with the app
    models\manifest.toml                model names, sources, hashes (files stay in venvs\)
    tools\bench\                        WS6 benchmarks
    tools\dev\                          scaffolding: new skill / connector / MCP manifest
    docs\                               architecture.md, skills.md, connectors.md, safety.md
    tests\                              mirrors src: tests\voicevibe\…, tests\vvhub\…
                                        (each folder needs __init__.py for `discover -s .`)
```

Contracts to add to TASK.md §3 (WS0 owns them):
- **Connector**: `class Connector: name; async def available() -> bool; async def call(op,
  **args)`; raises `ConnectorUnavailable(spoken)`; no network in tests (fake transport).
- **MCP manifest** (`integrations\mcp\<name>.toml`): `command`, `args`, `version`,
  `allow_tools`, `write_tools` (always approval), `env_secrets` (keyring names), `idle_s`.
- **Macro**: `{name, trigger_phrases, steps: [actions.py spec | {skill, action, args}],
  created_by: "voice", approved_at}`; critical steps still ask at run time.
- **Memory item**: `{id, kind (fact|preference|activity|transcript), text, source, ts,
  embedding}`; secrets never stored here (keyring only).
- **Voiceprint tag** on every `request`: `{"speaker": {"score": float, "owner": bool}}`.

Migration, so nothing breaks mid-flight:
1. **Now**: new code goes into the new packages only (`connectors\`, `tools\`, `memory\`,
   `workflows\`, new skills). No existing file moves.
2. **One WS0 commit**: move `vvhub` modules into `core\` / `brain\`, leaving one-line shims
   (`vvhub/store.py`: `from .core.store import *`) so every stream's imports keep working;
   full suite green; update §4 ownership.
3. **Later, one commit**: split `src\voicevibe\` the same way (shims kept one release).
4. Tests move with their modules; flat `tests\` keeps working until then.


---

## 5. Roadmap (proposed workstreams)

| Phase | Stream | Work | Done when |
|---|---|---|---|
| P0 fix | WS0 + user | the 3 hub-link gaps (§1.8) + `vvhub eval`; user adds FreeLLMAPI key, Edge extension, Notion token, Telegram pairing; restart both processes | one live run each: explain this, approve on Telegram, post dry-run, prompt into Kiro |
| P1 brain v2 | WS2 (+ WS6 for audio) | router cascade: hassil templates → model2vec classifier trained from hub.db decisions + intents.jsonl → Laya (unsure or critical only) → LLM planner for "and then" chains; Laya temperature refit; conversation state + follow-ups + "stop" cancels remaining steps; WS origin check; voiceprint tag (sherpa-onnx) with enrolment in the control panel | eval ≥ 90% action on the CPU tier, ≤ 10% asked on safe requests, critical 10/10, p50 < 150 ms on CPU |
| P2 life automation | new WS7 | `connectors\` + skills: system (settings URIs, WinGet, power, psutil), media (WinRT + pycaw), files (Everything + Filesystem MCP), reminders/timers (APScheduler), utility; then the MCP host (`tools\`) and mail / calendar / tasks via Google Workspace or MS 365 MCP (read-only first) | each skill: tests with fakes, eval phrases added, live read-only check |
| P3 memory & recall | new WS8 | sqlite-vec in hub.db, mem0 facts/preferences, activity log (window title/URL every change), `recall` skill, Ollama fallback in `llm.py` (Qwen3-1.7B low-spec / 4B dev laptop) | "what was I doing at 3", "what did I save about X" answered from local data |
| P4 phone & home | new WS9 | KDE Connect (`phone`: notifications, SMS with approval, find phone, send file), scrcpy / Android-MCP (on demand), Home Assistant MCP if there are devices | phone notification read aloud; SMS only after approval |
| P5 agents & macros | WS2 + WS3 | `workflows\` voice macros ("when I say X, do …"), Terminator record/replay, Playwright MCP `web_generic`, UFO² `desktop_agent` as last resort, all behind per-step policy | a saved macro replays with approvals; a site with no adapter can be searched and read |

Order inside every connector: read-only → tests with fakes → eval phrases → live read-only
check → write tools one by one behind approvals → commit per feature (TASK.md rule 3).

### 5.1 Memory budget (target laptop, CPU only, ≈1.5 GB always-on)

| Part | Today | With the plan |
|---|---|---|
| Voice Vibe + Whisper (CPU model) | WS6/WS5 measuring (GPU build ≈706 MB) | WS6 decides the engine |
| Airoot overlay | ≈135 MB | same (optional) |
| vvhub without models | 539 MB working set (measured 19:15) | same + model2vec 30–130 MB + sqlite-vec ~20 MB |
| Laya ONNX INT8 | 1.40 GB when loaded, unloads after 600 s idle | loaded only when the classifier is unsure or the request is critical → mostly unloaded |
| FreeLLMAPI + OpenCLI daemon | 98 + 43 MB | same |
| Always-on helpers | — | Everything (tens of MB), AHK (~5 MB), KDE Connect (100–150 MB, opt-in), voiceprint (50–150 MB) |
| On demand only | Windows-MCP, Telegram bot, control panel (122 MB) | MCP servers (50–150 MB each, reaped when idle), Playwright (~200 MB + browser), Ollama (1.5 GB with Qwen3-1.7B, 3–4 GB with 4B), UFO² (~0.5 GB), scrcpy |

The single biggest saving is not loading Laya for every request (P1). Qwen3-4B fits in 16 GB
when loaded on demand (rule 26 allows heavy parts on demand), but at 7–10 tokens/s on CPU a
spoken answer takes several seconds; Qwen3-1.7B is the low-spec pick, 4B the dev-laptop one.

---

## 6. Questions for the user (not decided here)

1. Mail and calendar: Google (Gmail/Calendar) or Microsoft (Outlook/To Do)? Both need a
   one-time OAuth setup on your own account.
2. Tasks: Todoist, Microsoft To Do, Google Tasks, or keep them in Notion?
3. Do you have smart-home devices (for Home Assistant), an Android phone (KDE Connect /
   scrcpy), Spotify Premium (needed for "play X" by name)?
4. OK to keep a local activity log (window titles / URLs, 2-day retention like chats) for
   "what was I doing"? Full screen recording (Windrecorder) is optional and heavier.
5. Voiceprint: enrol your voice so other voices can't issue commands? (Critical actions keep
   approvals either way.)
6. Coding: try Talon + Cursorless as a separate "coding mode", or stay with prompts into
   Claude / Codex / Kiro?
7. Approve the folder restructure (§4) and the new streams WS7–WS9 (§5)?
8. Macros by voice: may saved macros run critical steps with a per-step approval, or should
   macros be limited to non-critical steps?

WhatsApp stays deferred (unofficial clients risk a ban; rule 17).

## 7. Sources

CONV.md §2, §4, §6 (all stream logs to 19:10), §8, §9 (WS1 repo intel), §10, Inbox; TASK.md
§1–§6; `Voice_Vibe\THIRD_PARTY.lock`; `pyproject.toml`; `uv pip list` of venvs\voicevibe; skill
discovery output; live ports/processes at 19:15 (read-only); WS2 evals (GPU 14:50, ONNX 14:50).
Web research (4 parallel passes, 2026-09-30): project pages / READMEs of every repo named in
§2 (owner/name as written). Versions, dates and RAM figures in §2 are from those pages or
estimates by the researchers and should be re-checked when a project is adopted (pin exact
versions then, per rule 25).
