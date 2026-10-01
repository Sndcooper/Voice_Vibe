# TASK.md — Voice Vibe "Computer" automation hub

Read this file AND `CONV.md` (same folder) before doing anything. `CONV.md` is
the master log; this file is the rulebook, the shared interfaces and the work
split. Newest explicit user instruction wins.

Root (main working directory): `C:\Users\vilas\Documents\CIR\voicevibe\`

```
voicevibe\
  CONV.md  TASK.md       memory + rules (NOT in git)
  Repos\                 third-party clones (reference / build-on), pinned
  venvs\                 ALL environments & caches (NOT in git)
    voicevibe\           py3.11: Voice Vibe app + vvhub (+ Laya, Agent-Reach)
    windows-mcp\         py3.13 + Windows-MCP 0.8.5 (WS1 pinned it; 0.8.6+ needs py3.14)
    telegram-bot\        py3.11 (WS4 creates)
    node\                npm prefix + cache (npm_config_cache set)
    uv-cache\ wheelhouse\ hf-cache\
  Voice_Vibe\            ALL app code — the only git repo we commit
    src\voicevibe\       front end (existing)
    src\vvhub\           hub (new)
    src\vvbot\           Telegram bot fork (new, WS4)
    integrations\opencli-plugins\   (WS3)
    tests\  THIRD_PARTY.lock  run.bat  pyproject.toml
```

User env vars already set (User scope): `UV_CACHE_DIR=venvs\uv-cache`,
`HF_HOME=venvs\hf-cache`, `npm_config_cache=venvs\node\cache`. A shell opened
before 2026-09-30 03:06 may not have them — set them in-session if missing.

Python for everything: `..\venvs\voicevibe\Scripts\python.exe` (from
`Voice_Vibe\`). Install packages with
`uv pip install --python ..\venvs\voicevibe\Scripts\python.exe <pkg>==<ver>`.

---

## 1. Rules

### Process
1. **Don't build from scratch.** For every component find and pull one or more
   GitHub repos and copy / build on / combine them so it works; write only
   glue. Record each (URL, commit, license, role) in `Voice_Vibe\THIRD_PARTY.lock`.
   Clones go in `Repos\`; code actually copied/vendored into the app keeps its
   license header + upstream commit.
2. **`CONV.md` is the single source of truth + master log.** Every chat: read
   CONV.md + TASK.md first, follow them, and append to CONV.md §6 Agent log
   after EVERY meaningful action (what was created/changed/decided, files,
   commits, test results, blockers). Update your row on the §4 status board.
3. **Git.** Commit ONLY inside `Voice_Vibe\`. Branch **`voicevibe-automation`**
   (exists; created from main 3bf32b7). Push to remote **`SndcooperPrivate`**
   (`Sndcooper/Voice_Vibe-private`) on that branch — push is allowed. Never
   commit/push to `main`; don't change remotes or git config. Commit without
   asking, one commit per feature or bug fix, plain message, **no co-author
   trailer**. Stage only your own files (`git add <paths>`), never `git add .`
   / `-A`. `git pull --rebase SndcooperPrivate voicevibe-automation` before push;
   on `index.lock` wait a few seconds and retry (another chat is committing).
   Never commit secrets, `Repos\`, `venvs\`, CONV.md, TASK.md, `room.npy`.
   **All chats share ONE working tree and ONE index: never run `git switch`,
   `checkout <branch|.>`, `stash`, `reset`, `restore`, `clean`, `rebase -i` or
   `commit -a`.** Commit with `git commit -m "..." -- <your paths>` so another
   chat's staged files are never swept into your commit.
4. **Tests.** stdlib `unittest`, fakes like `tests/stubs.py`; tests never touch
   real windows, input, browsers, accounts, network. Run:
   `cd Voice_Vibe\tests; ..\..\venvs\voicevibe\Scripts\python.exe -m unittest discover -s .`
   Baseline 2026-09-30: **465 OK, 8 skipped**. Full suite green before each
   commit. All chats share ONE working tree: if a failure is only in files
   another stream owns and is mid-editing, don't touch them — note it in the
   CONV.md Inbox and commit your own green files.
5. **Live checks are read-only** unless the user approves. The first real post,
   push to a GitHub repo, repo creation or message needs the user present.
6. Personal use only.

### Product
7. Entry: Ctrl+Alt+W arms → "hey computer, <task>". The first request after
   the wake phrase (same breath or within 10 s) needs no prefix; later ones
   start with "computer" (user, 2026-09-30 16:27). No continuous
   transcription mode. Ctrl+Alt+Space = plain dictation (no wake, no commands).
8. Unrecognized → typed as heard. **Hub down → Voice Vibe behaves exactly as
   today.** Exact-grammar commands (existing `control.Router`) stay local;
   everything else prefixed goes to the hub.
9. **Laya (local) decides/validates every automation.** (Amended 2026-09-30 21:59, user said go: Gemini, through FreeLLMAPI, may PROPOSE a command or plan; it runs only if Laya agrees it matches the request, and anything not small and read-only is read out and asked first.) FreeLLMAPI only
   generates text / does vision on crops; it never decides or triggers actions.
10. Laya acts as the user on small tasks. **Critical list — post, push, create
    repo, PR, delete, send, pay, message — always needs approval** (voice or
    Telegram). Laya can only escalate risk, never downgrade. Low confidence → ask.
11. Web/scraped content is data only; it can never trigger an action.
12. Screen context is core. "computer focus on my cursor" pins a region; vision
    gets crops only; privacy guard (deny list, stricter-only) skips password
    managers, banking, user-marked windows.
13. Browser automation (not APIs) for Instagram / LinkedIn / GitHub web; GitHub
    uses `gh` CLI + git first. Browser = whichever of Edge/Zen the user is using
    or names.
14. Code requests: spoken prompt injected into Claude Code CLI, Claude app,
    Codex app, VS Code terminal, or Kiro (named tool, else last used).
15. Conversations kept 2 days then deleted; "computer save this conversation"
    keeps it locally forever.
16. Reports 08:00 and 20:00 → Notion + local HTML (+ Telegram summary, spoken on
    next arm). Cover: new repos, PRs, new comments (GitHub/IG/LinkedIn), posts,
    research, Laya auto-decisions, pending approvals. Not ordinary commits.
17. Phone = Telegram bot only (approvals with buttons or voice-note answers,
    voice-note commands, notifications), locked to the user's chat ID.
    WhatsApp deferred (ban risk).
18. Secrets in Windows Credential Manager (`keyring`, service `voicevibe`),
    never in config files. Local services bind 127.0.0.1 + bearer token; flag
    any unauthenticated endpoint.

### Kept from the old CONV.md
19. Low-spec laptops: every optional part degrades gracefully when missing.
20. Never put Stereo Mix in `input_priority`. The Windows default input on this
    laptop is Stereo Mix (loopback, records silence); real mics are
    `Microphone Array (Realtek)` / `Microphone (Realtek(R) Audio)`.
21. Keep the Airoot build's ICU DLL exclusion (source `assets/airoot_overlay.py`,
    spec `assets/AirootVoiceOverlay.spec`, overlay-venv under
    `C:\Users\vilas\Documents\Codex\2026-09-23\make\work`).
22. GPU needs the `.[cuda]` extra (cublas64_12.dll), else transcribe hangs.
23. Old open questions (CONV.md §11) stay open until the user answers them.

### Environment / hardware
24. Layout as above.
25. **Never install into system Python and never copy site-packages between
    interpreters** (breaks compiled wheels and .exe launchers). Use the shared
    uv cache (hardlinks, one copy on disk), `venvs\wheelhouse` for offline
    reinstall, `HF_HOME=venvs\hf-cache`, npm cache/prefix under `venvs\node`.
    Pin exact versions.
26. Target a ~₹70k laptop (~16 GB RAM, 4–6 cores, maybe no GPU): always-on
    budget ≈1.5 GB RAM; heavy parts start on demand and stop when idle; pick
    the lightest working option. (Dev laptop: RTX 5060 8 GB, 32 cores, 32 GB.)
27. Phone bot forked from `n3d1117/chatgpt-telegram-bot`, vendored into
    `src\vvbot` keeping its GPL-2.0 license + upstream commit.

### Multi-agent
28. Claim a workstream by writing `CLAIMED by <chat name> <timestamp>` under it
    here and on the CONV.md status board. Work only on paths you own (§4).
    Message other streams via CONV.md §7 Inbox (`@WS2 from WS3: …`). Only WS0
    changes §3 Interfaces; others propose changes via Inbox. Log every handoff.
    Shared files (`app.py`, `config.py`, `config.toml`, `pyproject.toml`,
    `README.md`): small targeted edits only (strReplace, never rewrite), each
    stream adds its own config section / optional-dependency extra.
29. Model: Claude Opus 5.5; effort high for WS0/WS2, medium otherwise.
30. **LIVE LOCK.** Only one chat at a time may drive the real desktop (mouse,
    keyboard, focus), a browser, or a real account (Edge, Zen, LinkedIn,
    Instagram, GitHub writes, Telegram sends, Notion writes). Before: append
    `- <Get-Date time> · LIVE LOCK taken by WSn: <what>` to CONV.md section 7;
    after: `- <time> · LIVE LOCK released by WSn`. If another chat holds it,
    wait and re-check. Read-only checks (doctor, `gh api` GETs, FreeLLMAPI
    `/v1/models`) need no lock. Anything critical (post, push, create repo,
    PR, send, message) also needs the user to say "go" in that chat first.
31. **Short replies, time limits.** Keep each chat reply under ~300 words and
    work in small steps: long replies time out. Give every command that can
    wait (doctor, network, installs) a time limit. Never block on `run.bat` or
    a GUI app: start them with `Start-Process`, or WMI `Win32_Process.Create`
    so they survive the tool shell.
32. **Never wait on one command.** Anything that can wait (installs, model
    loads, doctor, network, test suites) runs as a background job with a time
    limit (`Start-Job` + `Wait-Job -Timeout`) or in a subagent, while you do
    other independent work; make independent tool calls in parallel. A
    command that hits its time limit is reported and worked around, not
    retried blindly.

---

## 2. Build-on map

| Need | Build on | Our glue |
|---|---|---|
| Decisions | Laya `NandhaKishorM/laya` (model `convaiinnovations/laya` already in hf-cache). GPU: torch. CPU: ONNX INT8 via its `scripts/export_onnx.py --quantize` (export in temp `venvs\laya-export`, then delete) | 2-level schemas, policy |
| Text / vision | FreeLLMAPI `tashfeenahmed/freellmapi`, `http://localhost:3001/v1`, Windows .exe | retries, "pool exhausted" spoken |
| Tool plumbing | MCP Python SDK (client) | hub hosts MCP clients |
| Desktop state, cursor region, Zen DOM | Windows-MCP `CursorTouch/Windows-MCP` (MIT, 0.8.5 pinned on py3.13 in venvs\windows-mcp because 0.8.6+ needs py3.14; on-demand stdio, `ANONYMIZED_TELEMETRY=false`, exclude PowerShell/Registry/FileSystem) + existing `uia.py`/`screen.py` | context bundle, focus pin, privacy guard |
| Edge automation + LinkedIn | OpenCLI `jackwener/opencli` + Browser Bridge extension in Edge; built-in `linkedin` commands; skills via `npx skills add jackwener/opencli` (`opencli-adapter-author`, `opencli-autofix`) | plugins: linkedin post, instagram post/notifications, GitHub web fallbacks |
| Research | Agent-Reach `Panniantong/Agent-Reach` + trafilatura + Jina Reader; JS pages via OpenCLI/Edge; GPT-Researcher / Crawl4AI optional only | Laya relevance filter |
| Notion | official Notion MCP server or `notion-sdk-py` + an existing md→blocks converter | topic pages, chunking (100 blocks/append, 2000 chars/rich text) |
| GitHub | `gh` CLI (logged in as Sndcooper) + git; argument lists, never shell strings | voice commands, watchers |
| Telegram | fork `n3d1117/chatgpt-telegram-bot` + Hermes Agent gateway pairing/approval patterns | approvals, route to hub, PyAV not pydub/ffmpeg |
| Scheduler / reports | APScheduler + OpenJarvis `morning_digest` structure + Jinja2 | sections |
| Control app | NiceGUI native mode (pywebview / WebView2) | tabs |
| Office view | `chaitanyagiri/munder-difflin` office renderer (MIT) | feed from jobs table |
| OCR | Windows built-in OCR (existing); RapidOCR only if needed | — |
| Voice-note STT | Voice Vibe's loaded Whisper via hub `transcribe` | — |
| Reference only | Firecrawl (AGPL), Hermes Agent, OpenJarvis | — |

Key facts: Chrome 136+ (and Edge) ignore `--remote-debugging-port` on the
default profile → OpenCLI extension. OpenCLI is Chromium-only → Zen via
Windows-MCP `use_dom=True`. Laya: 421M/322M params, ~33 ms GPU, 190–460 ms CPU
preloaded, weak >20 options, "confident while wrong" → hard safety floor.
FreeLLMAPI: no SLA, quality dips late day, prompts go to cloud providers.

---

## 3. Interfaces (owned by WS0 — propose changes via Inbox)

Code these against the spec now; use fakes until the other side exists.
Python modules marked (WS0) are being written in `src\vvhub\` by WS0.

### 3.1 Hub process
- `python -m vvhub serve` → binds **127.0.0.1:53874** (Airoot uses 53873).
- Token: `%LOCALAPPDATA%\VoiceVibe\hub.token` (created on first start, random
  32 bytes urlsafe). Every HTTP call: `Authorization: Bearer <token>`; the
  WebSocket sends it in the first `hello` message.
- HTTP: `GET /health` → `{"ok": true, "version": str, "components": {...}}`.
- WebSocket: `ws://127.0.0.1:53874/ws`.
- Store: SQLite `%LOCALAPPDATA%\VoiceVibe\hub.db` (WAL).

### 3.2 WebSocket protocol (`vvhub/protocol.py`, WS0)
Every message is JSON `{"id": str, "type": str, ...}`. Replies carry
`"re": <id of request>`. First message from a client:
`{"type":"hello","token":..,"role":"voicevibe"|"bot"|"ui","version":..}` →
`{"type":"welcome"}` or the socket closes with 4401.

| type | direction | fields | reply |
|---|---|---|---|
| `request` | client→hub | `text`, `context` (3.3), `source` ("voice"/"telegram"/"ui") | `reply` |
| `reply` | hub→client | `text`, `speak: bool`, `handled: bool` | — |
| `confirm` | hub→voicevibe | `prompt`, `preview`, `timeout` s | `confirm_result {approved: bool, answer: str (words heard), unavailable?: true}`; `unavailable` = no session mic open, ask the next channel |
| `approval_request` | hub→bot | approval record (3.5) | `approval_result {approved, decided_by, answer}` |
| `run_steps` | hub→voicevibe | `steps` (actions.py spec list), `dry_run` | `steps_result {ok, error?}` |
| `get_context` | hub→voicevibe | `deep: bool`, `pin: bool|null` (true pins the cursor region, false unpins) | `context` (3.3) |
| `list_mics` / `set_mic` | hub→voicevibe | `set_mic {device}` | `mics {devices, current}` / `ok` |
| `transcribe` | client→hub→voicevibe | `audio_b64` (ogg/wav bytes), `format` | `text {text}` |
| `notify` | hub→bot/ui | `title`, `text`, `level` | — |
| `ping` / `pong` | either | — | `pong` |
| `armed` | voicevibe→hub | — (sent when a session arms) | `reply {text, speak, handled}`: the unspoken report summary, once; `''` if none |
| `error` | either | `message`, `code` | — |

Timeouts: `request` 20 s (then Voice Vibe falls back to typing the text),
`confirm` default 15 s = deny, others 10 s.

### 3.3 Context bundle (WS2 fills; `vvhub/schemas.py` WS0)
```json
{"window": {"hwnd": 0, "title": "", "process": ""},
 "caret_text": "", "selection": "",
 "pointer_element": {"name": "", "type": "", "rect": [0,0,0,0], "ancestors": []},
 "region": {"rect": [0,0,0,0], "ocr_text": "", "image_ref": null},
 "browser": {"name": "", "url": "", "title": "", "dom_text": null},
 "pinned": false, "redacted": false}
```
Every key optional. `image_ref` = path to a PNG crop in
`%LOCALAPPDATA%\VoiceVibe\crops\` (deleted with the 2-day purge).

### 3.4 Decision (`vvhub/schemas.py` WS0; WS2 produces)
`{category, action, target, confidence: float, risk: float, critical: bool,
needs_approval: bool, reason: str, laya_raw: dict}`.
Categories: `screen, research, notes, social, github, code, app, chitchat`.

### 3.5 Approval record (`vvhub/schemas.py` WS0; WS2 `approvals.py` owns logic)
`{id, action, preview, channel ("voice"|"telegram"|"ui"), status ("pending"|
"approved"|"denied"|"expired"), created, decided_by}`.
API (WS2 implements in `vvhub/approvals.py`; dispatch calls it — authoritative):
`await approvals.request(hub, plan: Plan, conversation: str | None = None) -> Approval`
(voice `confirm` via `hub.bus` if Voice Vibe is connected and a session is
armed, else Telegram `approval_request`; returns `Approval` with
`.status in {"approved","denied","expired"}`; store it via
`hub.store.add_approval/update_approval`). Skills never call this themselves
for the main action — dispatch does; a skill needing a *second* approval mid-run
may call it with its own Plan.

### 3.6 Skill interface (`vvhub/skills/base.py`, WS0)
```python
class Skill:
    name: str                 # e.g. "research"
    category: str             # one of the Decision categories
    actions: dict[str, str]   # action -> one-line description (Laya options)
    critical_actions: set[str]
    async def plan(self, decision, context) -> Plan: ...
    async def run(self, plan, approval=None, dry_run=False) -> Result: ...
```
`Plan{skill, action, args, preview, critical}`,
`Result{ok, text, speak, data}`. Skills are **auto-discovered**: any module in
`vvhub/skills/` exposing `SKILL = MySkill()` is registered — no shared registry
file to edit.

### 3.7 Shared services (signatures fixed now; owners implement)
- `vvhub.secrets` (WS0): `get(name) -> str|None`, `set(name, value)`,
  service `voicevibe` in Windows Credential Manager.
- `vvhub.store` (WS0): `add_turn`, `add_decision`, `add_approval`,
  `update_approval`, `add_job`, `update_job`, `add_watch_item`,
  `list_watch_items(since, kinds)`, `purge(now)`. Tables: conversations,
  turns, decisions, approvals, jobs, watch_items.
- `vvhub.smart_router` (WS2): `async decide(hub, text, context) -> Decision | None`
  (None = not a hub task → Voice Vibe types it).
- `vvhub.policy` (WS2): `needs_approval(decision, plan) -> bool` (sync; can only
  add a requirement — dispatch keeps the critical floor regardless).
- `vvhub.laya_engine` (WS2): `decide(state: str, questions: dict,
  min_confidence=None) -> dict` (Laya's result shape), `score(state,
  instruction, criteria) -> float`, `yes_no(state, instruction) -> float`.
- `vvhub.llm` (WS2): `async complete(messages, model="auto", max_tokens=800)
  -> str`, `async vision(prompt, png_bytes) -> str`; raises
  `LLMUnavailable` when the pool is exhausted.
- `vvhub.bus` (WS0): `async send_to(role, message) -> reply`,
  `connected(role) -> bool` — how skills reach Voice Vibe / the bot.

### 3.9 Request pipeline — `vvhub/dispatch.py` (WS0, BUILT, commit afab78c)
`dispatch.handle(hub, text, context, conversation=None, source="voice") -> Result`:
1. exact `skill.phrases` match (normalized lowercase) → that skill;
2. else `await vvhub.smart_router.decide(hub, text, context) -> Decision | None`
   (WS2; module absent or None → `Result.data["handled"] = False` → Voice Vibe
   types the text);
3. skill found by `decision.action in skill.actions` (category preferred);
4. `store.add_decision(...)`, then `plan = await skill.plan(decision, context)`;
5. approval needed if `plan.critical or decision.critical or is_critical(plan.action)`
   OR `vvhub.policy.needs_approval(decision, plan)` (WS2, sync, may only ADD);
6. `approval = await vvhub.approvals.request(hub, plan, conversation=...)` (WS2)
   must return an object with `.status == "approved"`, else "Cancelled.";
   approvals module absent + critical → refused, never run;
7. `await skill.run(plan, approval=approval)`; exceptions → failed Result.

`hub` object (`server.Hub`): `.store` (Store), `.bus` (Bus), `.skills`
(name → Skill), `.token`, `.components`. `schemas.is_critical(action)` matches
critical words inside action names (`linkedin_post`, `git_push`,
`create_repo`, `send_message`…). `Plan.critical` can never be set back to
False for such names. Skill modules may also define `phrases` for exact
matches that skip Laya (keep them few).

Built files: `vvhub/{__init__,__main__,schemas,protocol,secrets,bus,store,
dispatch,server,doctor}.py`, `vvhub/skills/{__init__,base,echo}.py`,
`tests/test_vvhub.py`. `python -m vvhub serve|doctor|token|purge|report|eval` (`report`/`eval` forward to WS4/WS2 parsers); `serve` logs to `%LOCALAPPDATA%\VoiceVibe\logs\vvhub.log` and runs WS4's ReportScheduler in its lifespan.

### 3.8 Paths
Data root `%LOCALAPPDATA%\VoiceVibe\`: `logs\`, `history\` (2-day),
`history\saved\` (forever), `hub.db`, `hub.token`, `crops\`, `reports\`.

---

## 4. Ownership map

| Stream | Owns |
|---|---|
| WS0 | `src\vvhub\{__init__,__main__,server,protocol,schemas,store,bus,secrets,dispatch}.py`, `src\vvhub\skills\{__init__,base,echo}.py`, `src\voicevibe\hub_client.py`, `history.py` retention changes, hub hook in `app.py`, TASK.md §3 |
| WS1 | `Repos\`, `venvs\` installs (except voicevibe base), `THIRD_PARTY.lock`, `src\vvhub\doctor.py` checks (framework built by WS0; add `@check(...)` functions), CONV.md §9 Repo intel |
| WS2 | `src\vvhub\{laya_engine,smart_router,policy,approvals,llm}.py`, `src\vvhub\evals\`, `src\vvhub\skills\{screen,code,app}.py`, `src\voicevibe\{context,focus,privacy}.py`, `profiles.py` additions |
| WS3 | `src\vvhub\skills\{browser,social,research,notes}.py`, `src\vvhub\browser\`, `integrations\opencli-plugins\` |
| WS4 | `src\vvhub\skills\{github,reports,watchers}.py`, `src\vvhub\scheduler.py`, `src\vvbot\`, `venvs\telegram-bot` |
| WS5 | `src\vvhub\ui\`, autostart, README automation section |

Tests: `tests\test_<module>.py` owned by the module's owner.

---

## 5. How to start a chat

> Read `C:\Users\vilas\Documents\CIR\voicevibe\TASK.md` and `CONV.md`, claim
> WS<n>, and start. Log everything to CONV.md.

---

## 6. Workstreams

Every task: tests first → full suite green → commit (rule 3) → log in CONV.md →
demo. Push after each finished task.

### WS0 Foundation — effort high
Status: CLAIMED by chat "WS0 main" 2026-09-30 03:03. T1-T4 done.
Follow-ups (asked by WS2/WS4 in the Inbox) DONE 2026-09-30 15:26, commit 19543ef; the edit freeze below is lifted:
F1 `confirm` replies `unavailable: true` when no session is listening (so
approvals fall back to Telegram) and carries the real heard answer; F2
`get_context` honours `pin`; F3 `list_mics`/`set_mic` handlers; F4 `transcribe`
handler for Telegram voice notes; F5 hub lifespan starts/stops the report
scheduler, plus `python -m vvhub report --now` and `python -m vvhub eval`; F6
spoken report summary when a session is armed; F7 hub file log
`logs\vvhub.log`; then restart hub + Voice Vibe. Until WS0 posts DONE in the
CONV.md Inbox, nobody else edits `app.py`, `hub_client.py`, `server.py` or
`__main__.py`.
Skills: Python 3.11, uv, git, FastAPI/uvicorn, websockets, SQLite, keyring.
- T1 Workspace: tools checked, dirs, env vars, venvs\voicevibe, wheelhouse,
  hf-cache copy, run.bat, branch, CONV.md/TASK.md — **done** (except removing
  old `Voice_Vibe\.venv`: needs VS Code closed).
- T2 Hub skeleton: `python -m vvhub serve`, token, /health, WS hello, skill
  auto-discovery, `vvhub doctor` framework (WS1 adds checks), secrets, bus.
- T3 Store + 2-day retention: SQLite store; `history.py` keep_days=2 with
  exempt `saved\`; "computer save this conversation".
- T4 Voice Vibe ↔ hub link: `hub_client.py` (reconnect/backoff, fallback),
  hook after Router + assistant fallthrough; "computer ping hub" → "Hub is online".
Done when: T2–T4 committed + pushed, §3 matches code.

### WS1 Repos & intel — effort medium
Status: CLAIMED by chat "WS1 kiro" 2026-09-30 03:32. Done 2026-09-30 15:00 (40537fd); user-only steps pending.
Skills: git, Node/npm, uv, Windows installers, reading codebases.
Repos: all in §2.
Depends on: nothing (start now).
- Clone into `Repos\` at pinned commits (shallow OK): laya, freellmapi,
  Agent-Reach, opencli, Windows-MCP, chatgpt-telegram-bot, OpenJarvis,
  hermes-agent, munder-difflin, firecrawl. Write `Voice_Vibe\THIRD_PARTY.lock`.
- Install/link: FreeLLMAPI (Windows .exe from Releases or from the clone; user
  adds provider keys — tell them); OpenCLI via npm with prefix `venvs\node`
  (+ Browser Bridge in Edge — user loads it; `opencli doctor`); `npx skills add
  jackwener/opencli`; uv-managed Python 3.14 (cpython-3.14.7) + Windows-MCP in
  `venvs\windows-mcp`, telemetry off; Agent-Reach into venvs\voicevibe
  (`agent-reach doctor`); Laya into venvs\voicevibe (CUDA torch on this
  laptop; ONNX INT8 export in temp venv, then delete; keep the .onnx in
  hf-cache or `venvs\models`).
- Repo intel in CONV.md §9 per repo: architecture, entry points, what we
  reuse, license, gotchas, Windows issues.
- Extend `vvhub doctor` with a check per component.
Done when: doctor all green except items needing user credentials; §9 filled.

### WS2 "Hey computer" brain — effort high
Status: CLAIMED by chat "WS2 kiro" 2026-09-30 03:32 — T5–T9, T12 done 05:26
(a6a1948, 22cb5a3, f9554e5, 975d85b, c42dac9, a5d6d32).
Skills: Laya API (`Router`, `predict`, `decide`, `min_confidence`,
`ONNXAgent`), Windows UIA, Windows-MCP tools (Snapshot/Screenshot `region`,
`use_dom`), OpenAI client, safety design.
Repos: laya, Windows-MCP, opencli (desktop adapters: Codex), existing
`profiles.py`/`uia.py`/`screen.py`/`actions.py`/`confirm.py`.
Depends on: WS0 interfaces (code against §3 with fakes now); WS1 for Laya install
(install it yourself if WS1 hasn't yet — log it).
- T5 Laya engine + level-1 category routing, hardware tiers,
  `evals/intents.jsonl` (~80 phrases), `python -m vvhub eval`
  (accuracy/latency/RAM), fake Laya for tests.
- T6 Level-2 actions (from registered skills' `actions`), target choice from
  live windows / AI tools, policy (critical list by action type, escalate-only,
  act-as-me, low-confidence ask), decision log.
- T7 Approvals: queue, voice via `confirm`, Telegram via `approval_request`,
  timeout = deny, spoken preview.
- T8 Screen context v2 in Voice Vibe: caret text, pointer element + ancestors,
  ~800×500 region crop + Windows OCR, Windows-MCP region/DOM, "focus on my
  cursor"/"unfocus" pin with timeout + orb frame, privacy guard; bundle sent on
  every hub request; local "what's this".
- T9 `llm.py` FreeLLMAPI client + "explain this" (crop-only, Laya validates
  the reply, pool-exhausted message).
- T12 `skills/code.py`: prompt injection into Claude app, Codex app, VS Code
  terminal (Claude Code / Codex CLI), Kiro; focus → find input → paste →
  Enter; "fix this" attaches pinned context.

### WS3 Social & web — effort medium
Status: CLAIMED by chat "WS3 kiro" 2026-09-30 03:32.
Skills: OpenCLI browser primitives + adapter-author/autofix skills,
Windows-MCP `use_dom`, Notion API, trafilatura, Agent-Reach CLI.
Repos: opencli, Agent-Reach, Windows-MCP, notion-sdk-py / Notion MCP,
OpenJarvis `deep_research` (reference).
Depends on: WS1 installs (OpenCLI, Agent-Reach) — install yourself if needed
and log; WS2 `llm`/`laya_engine`/`approvals` via fakes until ready.
- T14 Browser layer (`src\vvhub\browser\`): Edge via OpenCLI, Zen via
  Windows-MCP; pick by foreground window or spoken name.
- T15 `skills/social.py`: OpenCLI LinkedIn built-ins + new plugins in
  `integrations\opencli-plugins` (linkedin post, instagram post +
  notifications, GitHub web fallbacks); LLM drafts, Laya validates, approval
  always; stop and ask on a failed step.
- T11 `skills/research.py`: Agent-Reach + trafilatura/Jina + OpenCLI for JS
  pages; Laya relevance filter; LLM digest; Notion + local; spoken summary;
  background job; prompt-injection test.
- T10 `skills/notes.py`: Notion token in keyring; parent page with
  Notes/Transcripts/Reports; "note this", "make notes about X", "save this
  transcript"; Laya picks the topic page.

### WS4 GitHub, Telegram, reports — effort medium
Status: CLAIMED by chat "WS4 kiro" 2026-09-30 03:33. T13, T16, T17 done
(04:15); hub wiring requested from WS0 in CONV.md Inbox.
Skills: gh CLI, python-telegram-bot, APScheduler, Jinja2, PyAV.
Repos: chatgpt-telegram-bot (fork), hermes-agent (gateway pairing/approval
patterns), OpenJarvis (`morning_digest`).
Depends on: WS0 protocol (fakes now), WS2 approvals, WS3 notes (for Notion
reports; write HTML first).
- T13 `skills/github.py`: create repo / push / PR critical; commit only on a
  non-default branch; watcher via `gh api` (new repos, PRs, comments) →
  `store.add_watch_item`.
- T16 `src\vvbot\` fork of chatgpt-telegram-bot (venvs\telegram-bot): keep
  allowlist / voice handling / plugins; replace OpenAI Whisper with hub
  `transcribe`, ChatGPT with hub `request`, pydub with PyAV; add approval cards
  (buttons + voice-note strict yes/no + Laya), pairing code, notifications.
  Token in keyring.
- T17 `scheduler.py` + `skills/reports.py` + `skills/watchers.py`: 08:00/20:00
  reports per rule 16 → Notion + HTML (`%LOCALAPPDATA%\VoiceVibe\reports`) +
  Telegram + spoken on next arm; missed-run catch-up; `python -m vvhub report --now`.

### WS5 App & polish — effort medium (UNBLOCKED 2026-09-30 15:12, WS2-WS4 landed; was: start after WS2–WS4 land)
Status: CLAIMED by chat "WS5 kiro" 2026-09-30 18:16.
Skills: NiceGUI, pywebview, Windows startup, psutil / py-spy.
Repos: NiceGUI, munder-difflin.
- T18 Control app (NiceGUI native): Status, Microphone, Services, Approvals,
  Conversations, Logs, Reports, Settings; tray entry.
- T19 Autostart + wiring; `vvhub export-finetune`; README; CPU-only resource
  measurement vs the 1.5 GB budget → CONV.md §10.
- T20 Office view (munder-difflin renderer fed by jobs/approvals).

### WS6 Voice Vibe v2: speech engines and efficiency -- effort high (added 2026-09-30 18:09)
Status: CLAIMED by chat "WS6 kiro" 2026-09-30 18:17. Done 21:30 (f2b04a1, da9c13e); follow-ups in CONV.md §6.
Owns: `src\voicevibe\{transcriber,wakeword,audio,vocab}.py`, new
`src\voicevibe\engines\`, `tools\bench\` (benchmarks), their tests; small
strReplace edits to app.py / config.py / config.toml for new flags.
Goal: research newer local speech tech, benchmark it on this laptop AND a
CPU-only profile, then ship the best 1-2 wins behind config flags without
breaking dictation (defaults unchanged until measured better).