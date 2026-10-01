# Voice Vibe: status, features and architecture

Snapshot of 2026-09-30 22:30. Written from CONV.md (the full log), TASK.md (rules
and work split), the git history (47 commits on `voicevibe-automation`, pushed
to `SndcooperPrivate`) and a live `python -m vvhub doctor`. Update the
"Status" columns when something changes; CONV.md keeps the detail.

---

## 1. In one paragraph

Voice Vibe is two programs that talk over a local WebSocket. **Voice Vibe**
(the front end) listens, transcribes with Whisper and does everything that
has to happen on the desktop right now: typing, keys, clicks, windows, apps,
screen reading, the logo. **vvhub** (the hub) takes the requests Voice Vibe
can't handle itself: Gemini Flash reads them, **Laya** (local model) decides
what they are, a policy decides whether to ask you, and a *skill* does the
work (terminal commands, coding prompts, research, notes, GitHub, social
media, reports). The core runs today. Most integrations are built and tested
with fakes but have never touched your real accounts, because four account
setups are still missing and every live test so far has turned up new bugs.

---

## 2. What is running right now

| Process | Started from | Status |
|---|---|---|
| Voice Vibe (`pythonw -m voicevibe`) | `run.bat` | Running, linked to the hub |
| vvhub (`pythonw -m vvhub serve`) | `run.bat` (starts it first since `fd91d6f`) | Running on 127.0.0.1:53874, Laya on GPU |
| FreeLLMAPI (`FreeLLMAPI.exe`) | its own tray app | Running on :3001, key set, Gemini Flash answering |
| OpenCLI daemon | starts by itself | Running; Edge extension **not connected** |
| Airoot overlay (`AirootVoiceOverlay.exe`) | Voice Vibe launches it | Running when Voice Vibe runs |
| Telegram bot (`src\vvbot\run.bat run`) | by hand | **Not running**: no bot token |
| Windows-MCP | on demand | Starts when a Zen/desktop read needs it |

`vvhub doctor` today: OK for hub, gh, keyring, Laya (GPU + CPU INT8),
FreeLLMAPI + key (256 models), OpenCLI 1.8.8, Windows-MCP 0.8.5, Agent-Reach
(4/16 channels). **Waiting on you:** Edge extension, Notion token, Telegram token.

Start everything: `Voice_Vibe\run.bat`. Check: `..\venvs\voicevibe\Scripts\python.exe -m vvhub doctor`.

---

## 3. Architecture

```
 you ──speech──► Voice Vibe (front end, src\voicevibe)                     local only
                 ├─ hotkeys: Ctrl+Alt+Space dictate · Ctrl+Alt+W session · Ctrl+Alt+Shift+Space speak
                 ├─ audio.py segments speech → transcriber.py (faster-whisper large-v3-turbo GPU,
                 │   base.en for short commands; engines\parakeet.py for CPU-only laptops)
                 ├─ wake.py "hey computer" → session_mode = control (every utterance is a request)
                 ├─ local handlers (no hub needed): save conversation, screen phrases,
                 │   terminal routing, "type …/press enter", app launching, window/keyboard router,
                 │   assistant replies, spoken edits
                 ├─ context.py: window, caret text, element under pointer, crop + OCR, focus pin,
                 │   privacy guard  ──► sent with every hub request
                 ├─ hub_client.py ◄──WebSocket 127.0.0.1:53874 + token──► vvhub
                 └─ airoot.py → Airoot overlay (logo) · overlay.py orb · SAPI voice replies

 vvhub (hub, src\vvhub)                                                     local process
   server.py (FastAPI) → dispatch.py:
     1. exact phrase ("ping hub", "save this conversation")
     2. plain shell in front → skills\terminal.py
     3. broker.py: Gemini Flash / Flash-Lite reads the request + recent turns +
        worklog (Claude Code / Codex sessions, git) → a cleaned request + hints   (text only)
     4. smart_router.py: Laya picks category (8) then action + target            (decides)
     5. policy.py: critical words, risk, confidence → act as you, or ask
     6. approvals.py: ask by voice (Voice Vibe), else Telegram (vvbot), else deny
     7. the skill runs; the reply is spoken
   store.py SQLite (turns, decisions, approvals, jobs, watch items; 2-day purge)
   scheduler.py → 08:00 / 20:00 reports · ui\ control panel API · doctor.py

 outside helpers: FreeLLMAPI (Gemini + other free models) · OpenCLI (+ Edge extension) ·
 Windows-MCP (desktop tree, Zen) · Agent-Reach (web/RSS/GitHub/YouTube) · gh CLI · Notion API ·
 Telegram (vvbot, forked from chatgpt-telegram-bot)
```

**Who decides what (rules 9 and 10):** Laya decides; Gemini only writes text
or *proposes* (a command, a cleaned request). A Gemini proposal runs only if
Laya agrees it matches what you said. Post, push, create repo, PR, delete,
send, pay, message always ask you. If the hub is down, Voice Vibe types what
you said, as before.

---

## 4. How a request is routed

Ctrl+Alt+W → "hey computer" → you say something. In order, the first match wins:

| Step | Where | Example | Result |
|---|---|---|---|
| 1 | `app._do_session` | "never mind", 40 s silence | Session goes back to waiting |
| 2 | `history.is_save_command` | "save this conversation" | Saved forever in `history\saved\` |
| 3 | `context.LocalScreen` | "focus on my cursor", "what's this" | Pin / read locally |
| 4 | `terminal.py` (a terminal is in front) | AI CLI running: anything | Typed as the prompt |
|   |  | plain shell: "type ls, press enter" | Typed raw, Enter |
|   |  | plain shell: "list the files" | Hub terminal skill → `dir` |
| 5 | `inserter.is_session_typing` | "type hello, press enter" | Typed, Enter |
| 6 | `intent.try_launch` | "open terminal" | Launches a Start Menu app |
| 7 | `control.Router` | "scroll down", "new tab", "switch to chrome", "click Settings" | Keys / mouse / window |
| 8 | `intent.Responder` | "where am I", "what's on my screen" | Spoken answer |
| 9 | hub (`dispatch`) | "research X", "tell Claude to …", "how do I …?" | Broker → Laya → policy → skill |
| 10 | — | anything left | Typed as heard |

Inside the hub terminal skill: words that already are a command run as they are →
otherwise BM25 over 110 tldr-pages commands + Laya confirms → the request picks
the variant and fills blanks → if tldr has nothing or Laya doubts it, Gemini
proposes one command and Laya checks it → small read-only commands run, the
rest are read out and asked.

---

## 5. Features

Status: **Works** = seen working on this laptop · **Built** = code + tests with
fakes, not tried live · **Needs you** = waits on an account/setup · **Not built**.

### 5a. UI automation (acts on the desktop)

| Feature | How | Status |
|---|---|---|
| Dictation into any app | Ctrl+Alt+Space, Whisper, paste | Works |
| Voice-control session | Ctrl+Alt+W, "hey computer", control mode | Works (voice tests at 18:15–18:52 found bugs, fixed after) |
| Typing and Enter | "type X, press enter", "X and enter" | Works (18:26) |
| Open apps | Start Menu index (214 apps), `try_launch` | Works ("open terminal" 18:15, 18:50) |
| "Open X and <rest>" | launch, wait for window, do the rest | Built |
| Windows, tabs, scrolling, keys | `control.Router` (Phase 2 grammar) | Works (earlier sessions) |
| Click by name / numbered badges / OCR | `uia.py`, `overlay.Badges`, Windows OCR | Built (read-only live checks only) |
| App profiles | Explorer, Zen, Claude, ChatGPT, Codex, Kiro, VS Code (`profiles.py`) | Built |
| Terminal commands from speech | tldr + Laya + Gemini fallback | Built; real-Laya eval cmd 46/46, PowerShell 45/46; not tried by voice |
| Prompts into AI coding tools | `skills\code.py`: Claude app, Codex app, VS Code terminal, Kiro, Claude Code | Built, never typed live |
| Screen context + focus pin + privacy guard | `context.py`, `focus.py`, `privacy.py` | Built (read-only live checks) |
| Microphone switching | hub `list_mics` / `set_mic`, never Stereo Mix | Built |
| Logo overlay | Airoot EXE, still vs dancing | Works; see §8 (two chats changed it) |
| Browser control (Edge / Zen) | OpenCLI + Edge extension / Windows-MCP | Needs you (Edge extension) |

### 5b. Non-UI automation (hub skills, no clicking)

| Feature | Skill / file | Status |
|---|---|---|
| Hub link, approvals by voice → Telegram | `hub_client.py`, `approvals.py` | Built (voice path unit-tested; spoken approval never tried live) |
| Laya routing | `smart_router.py`, `laya_engine.py` | Works (loads on GPU at start, 91% category / 94.6% action on eval) |
| Gemini broker (reads the request first) | `broker.py`, `worklog.py` | Built by another chat (d1f206c, 6d731ac) |
| Spoken answers | `skills\ask.py` | Built; Gemini answered in 3–9 s (script check) |
| "Explain this" on a screen crop | `skills\screen.py`, `llm.py` vision | Built; key now set, not tried live |
| Web research digests | `skills\research.py` (Agent-Reach, trafilatura, Jina) | Built; not tried live |
| Notion notes / transcripts | `skills\notes.py` | Needs you (Notion token) |
| LinkedIn / Instagram read + post | `skills\social.py`, OpenCLI plugin | Needs you (Edge extension); first post only with you present |
| GitHub: status, PRs, repos, commit, push, PR | `skills\github.py` (gh + git) | Built; read calls worked, writes never tried |
| GitHub watcher | `skills\watchers.py` | Built; read-only run worked |
| 08:00 / 20:00 reports | `scheduler.py`, `skills\reports.py` | Works (HTML written, spoken on arm); Notion part needs the token |
| Telegram bot: approvals, voice notes, commands | `src\vvbot\` | Needs you (bot token + pairing) |
| 2-day conversation retention + save | `history.py`, `store.py` | Works |
| Control panel app | `src\vvhub\ui\` (pywebview, tray) | Built by WS5 (8a28161); WS5 still in progress |
| Autostart at login | `ui\launcher.py`, run.bat | Built (opt-in) |
| CPU-only speech engine | `engines\parakeet.py` | Built (WS6); used only when `[model].engine` says so / no GPU |
| Multi-step tasks ("open terminal, make a folder, write and run a file") | — | **Not built** (waiting for your go) |
| Office view (agents at desks) | — | **Not built** (WS5 T20) |

---

## 6. How the code is organised

```
C:\Users\vilas\Documents\CIR\voicevibe\
  CONV.md                master log of every change (read first)
  TASK.md                rules 1–32, interfaces, who owns which files
  VOICEVIBE_STATUS.md    this file
  Repos\                 third-party clones, pinned (laya, freellmapi, Agent-Reach, opencli,
                         Windows-MCP, chatgpt-telegram-bot, OpenJarvis, hermes-agent,
                         munder-difflin, firecrawl, tldr)
  venvs\                 voicevibe (py3.11: app + hub), windows-mcp (py3.13), telegram-bot,
                         freellmapi, node, models (Laya INT8), hf-cache, uv-cache, wheelhouse
  Voice_Vibe\            the git repo (branch voicevibe-automation)
    run.bat  config.toml  pyproject.toml  README.md  THIRD_PARTY.lock
    src\voicevibe\       front end: app.py (the state machine, 1330 lines), audio, transcriber,
                         engines\, wake/wakeword, inserter, control (router), actions (executor),
                         uia, screen, context/focus/privacy, terminal, intent/launcher, profiles,
                         hub_client, history, airoot/overlay, confirm, speaker, config
    src\vvhub\           hub: server, dispatch, broker, worklog, smart_router, laya_engine,
                         policy, approvals, llm, store, scheduler, bus, protocol, schemas,
                         secrets, doctor, shell_words, evals\, data\shell_catalog.json,
                         browser\ (OpenCLI / Windows-MCP drivers), ui\ (control panel),
                         skills\ (app ask browser code conversation echo github notes reports
                                  research screen social terminal watchers)
    src\vvbot\           Telegram bot (GPL-2.0 fork, see UPSTREAM.md)
    integrations\opencli-plugins\voicevibe\   linkedin-post, instagram / github notifications
    tools\               build_shell_catalog.py, eval_terminal.py, bench\ (speech benchmarks)
    assets\              airoot_overlay.py + spec (overlay EXE source), logos, demo gif
    tests\               67 test files, 1181 tests (stdlib unittest, fakes only)
```

Data (not in git): `%LOCALAPPDATA%\VoiceVibe\` → `logs\voicevibe.log`,
`logs\vvhub.log`, `history\` (2 days) + `history\saved\`, `hub.db`,
`hub.token`, `reports\`, `crops\`. Secrets: Windows Credential Manager,
service `voicevibe` (`freellmapi_key`, `notion_token`, telegram).

---

## 7. What it is built on

| Need | Third-party piece | Glue in this repo |
|---|---|---|
| Speech to text | faster-whisper (Whisper large-v3-turbo, base.en); Parakeet via onnx-asr (CPU) | transcriber.py, engines\ |
| Decisions | Laya (local, GPU or INT8 ONNX) | laya_engine.py, smart_router.py, policy.py |
| Writing / vision / proposals | FreeLLMAPI → Gemini 3.7/3.6/3.5 Flash, Flash-Lite, others | llm.py, broker.py, ask.py |
| Shell commands | tldr-pages (CC BY 4.0) + rank-bm25 | skills\terminal.py, tools\build_shell_catalog.py |
| Desktop UI | Windows UI Automation (uiautomation, comtypes), Windows OCR (winsdk), Windows-MCP | uia.py, screen.py, context.py |
| Browser + social | OpenCLI + its Edge extension | browser\, skills\social.py, OpenCLI plugin |
| Research | Agent-Reach, trafilatura, Jina Reader | skills\research.py |
| Notes | notion-client (Notion Markdown API) | skills\notes.py |
| GitHub | gh CLI + git | skills\github.py, watchers.py |
| Phone | python-telegram-bot, forked chatgpt-telegram-bot | src\vvbot\ |
| Hub server | FastAPI, uvicorn, websockets, keyring, APScheduler | server.py, store.py |
| Control panel | pywebview (Edge WebView2), Pico CSS | ui\ |
| Wake word | Whisper phrase match (default), openWakeWord optional | wake.py, wakeword.py |

---

## 8. Pending work and why it isn't done

| Pending | Why | Next step |
|---|---|---|
| Edge extension, Notion token, Telegram token + pairing | Only you can do these (logins, secrets) | Steps in CONV.md; then `vvhub doctor` |
| Live tests of social, Notion, research, Telegram approvals, GitHub writes | Need the setup above, and rule 5: real posts/pushes only with you present, one chat at a time (LIVE LOCK) | WS3 / WS4 prompts |
| Your voice test of the terminal skill, spoken answers, "explain this" | Built after your last voice test | Try the phrases in my last message |
| Multi-step tasks | Waiting for your go (Gemini drafts steps, Laya checks each) | Say go |
| Control panel polish, CPU-only memory check vs 1.5 GB, office view | WS5 still in progress | WS5 chat |
| Terminal gaps | "zip the reports folder" picks `tar xvf` (now asks first); "how much disk space is left" finds nothing | Add catalog entries |
| Typed text is polished in normal apps | By design for dictation; raw only in shells | Say if you want raw elsewhere |
| CPU-only Laya accuracy (action 62.9%) | Zero-shot model; asks more often on a cheap laptop | Fine-tune on the decision log |
| Logo behaviour conflict | You asked (18:55) for the still original logo in silence; another chat later committed `bd84861` (pink-red wave frame) and `da2f477` ("slow waves and a gentle float" in silence) | Tell me which one you want and I'll pin it |
| Uncommitted work in the tree | `src\voicevibe\control.py` + `tests\test_key_commands.py` from another chat, mid-edit | That chat commits it |
| Old open questions | Wake-word model, partial transcripts, `room.npy`, word timestamps, "delete line" confirmation | CONV.md §11 |

### Why it still feels "in development" although it runs

- **Built in one day by six parallel chats.** 47 commits, 1181 tests, but tests use
  fakes: they prove the logic, not that Instagram's page or your microphone behave.
- **Every voice test found real bugs** (router swallowing "open terminal", the
  20 s silence timer, Laya failing to load under pythonw, the logo fading). Each
  was fixed, but only a voice test shows the next one.
- **Half the skills are waiting on accounts** (Edge, Notion, Telegram), so they
  have never run end to end.
- **Safety gates are on purpose:** posts, pushes and deletes always ask, and the
  first real ones need you present.

---

## 9. Where to look when something is wrong

| Question | Look at |
|---|---|
| What did it hear and do? | `%LOCALAPPDATA%\VoiceVibe\logs\voicevibe.log` |
| What did the hub decide? | `%LOCALAPPDATA%\VoiceVibe\logs\vvhub.log` (no "vvhub stopped" line = killed) |
| Is everything set up? | `python -m vvhub doctor` |
| What changed and why? | CONV.md §6 (log), `git log` in `Voice_Vibe\` |
| Who owns a file / the rules? | TASK.md §1 and §4 |
| Routing accuracy | `python -m vvhub eval`, `tools\eval_terminal.py` |
| Speech engine numbers | CONV.md §10 (WS6 benchmark table) |
