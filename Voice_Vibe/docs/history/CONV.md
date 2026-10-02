# CONV.md — Voice Vibe master memory + log (all chats)

## 1. How to use this file
- Read this file and `TASK.md` (same folder) before doing anything.
- Append to §6 after EVERY meaningful action: time, stream, what, files,
  commits, tests, result/blocker. Newest at the bottom. Never delete others'
  entries; mark superseded ones instead.
- Update your row in §4 when you claim, finish or block a task.
- Cross-stream messages go in §7 Inbox. Research facts go in §8, repo
  architecture notes in §9.
- Newest explicit user instruction wins. Record user decisions in §8.

## 2. Vision & requirements (summary)
Voice Vibe (local Whisper dictation + voice control, Windows) becomes the voice
front door of a personal automation hub. Ctrl+Alt+W → "hey computer" →
"computer <task>". Exact commands stay local. Everything else goes to **vvhub**
(a separate local process): the smart router asks **Laya** (local, typed
decisions); the policy acts as the user on small tasks and asks for approval
(voice or Telegram) on critical ones; skills do the work by building on
existing repos: screen context and "explain this" (Windows-MCP + UIA + OCR +
FreeLLMAPI vision on crops), research (Agent-Reach), Notion notes, LinkedIn /
Instagram / GitHub web via browser automation (OpenCLI in Edge, Windows-MCP in
Zen), GitHub via `gh`, and prompts typed into Claude Code / Claude app / Codex
app / VS Code terminal / Kiro. Reports go to Notion + HTML at 08:00/20:00.
Conversations are kept 2 days unless saved. Telegram bot (forked) is the phone
channel. A NiceGUI control app comes later, then a Munder-Difflin-style office
view. Personal use only; target a ~₹70k laptop (≈1.5 GB always-on RAM).

## 3. Rules
The full rules are in `TASK.md` §1 (29 rules). Short version: build on GitHub
repos (never from scratch); log everything here; commit only `Voice_Vibe\` on
`voicevibe-automation`, push to `SndcooperPrivate`, no co-author trailer, stage
own files only; stdlib unittest with fakes, suite green; Laya decides and
FreeLLMAPI only writes; critical actions always need approval; hub down means
Voice Vibe behaves as today; secrets go in keyring; no installs into system
Python; venvs/caches under `venvs\`; never use Stereo Mix.

## 4. Workstream status board
| Stream | Owner chat | Status | Current task |
|---|---|---|---|
| WS0 Foundation | WS0 main | done | T1–T4 (fa700cd, afab78c, c4de14a, 39a610a) + follow-ups F1–F7 (19543ef, 15:26); maintains §3 |
| WS1 Repos & intel | WS1 kiro | done (40537fd) — waiting on user keys / Edge extension | — |
| WS2 Hey-computer brain | WS2 kiro | CLAIMED by WS2 kiro 2026-09-30 03:32 — **T5–T9, T12 done** 05:26 (a6a1948, 22cb5a3, f9554e5, 975d85b, c42dac9, a5d6d32); waiting on WS0 hub_client for live end-to-end | — |
| WS3 Social & web | WS3 kiro | CLAIMED by WS3 kiro 2026-09-30 03:32 — T14/T15/T10/T11 done, pushed; live checks blocked on user (Edge extension, Notion token) | T14 7f1cf03 · T15 71ed9b4 · T10 0997240 · T11 d3c6520 · extra bd5dfef |
| WS4 GitHub/Telegram/reports | WS4 kiro | CLAIMED by WS4 kiro 2026-09-30 03:33 — T13, T16, T17 done (04:15) | waiting on WS0 wiring (Inbox) + user setup (bot token, pairing) |
| WS5 App & polish | WS5 kiro | CLAIMED by WS5 kiro 2026-09-30 18:16 — in progress | research → T19 → T18 UI → §10 → T20 |
| WS6 Voice Vibe v2 (speech engines) | WS6 kiro | done (f2b04a1, da9c13e) — optional follow-ups listed in §6 21:35 | — |

## 5. Master task list
| # | Task | Stream | Status |
|---|---|---|---|
| 1 | Workspace, venvs, docs, branch | WS0 | done (old .venv removal pending: VS Code must close) |
| 2 | Hub skeleton + doctor framework | WS0 | done afab78c |
| 3 | Store + 2-day retention + save conversation | WS0 | done c4de14a |
| 4 | Voice Vibe ↔ hub link | WS0 | done 39a610a |
| – | Clone/install/link repos, THIRD_PARTY.lock, repo intel, doctor checks | WS1 | done (40537fd) |
| 5 | Laya engine + category routing + eval | WS2 | done a6a1948 |
| 6 | Actions / targets / policy | WS2 | done 22cb5a3 |
| 7 | Approvals (voice + Telegram) | WS2 | done f9554e5 |
| 8 | Screen context v2 + focus pin + privacy | WS2 | done 975d85b |
| 9 | FreeLLMAPI client + explain this | WS2 | done c42dac9 (live check needs FreeLLMAPI key) |
| 10 | Notion notes | WS3 | done 0997240 (live: needs Notion token) |
| 11 | Web research | WS3 | done d3c6520 |
| 12 | Prompts into AI coding tools | WS2 | done a5d6d32 |
| 13 | GitHub skill + watcher | WS4 | done (a8e5b7f, b1276d1) |
| 14 | Browser layer (Edge/Zen) | WS3 | done 7f1cf03 (live: needs Edge extension) |
| 15 | Social (LinkedIn/Instagram) | WS3 | done 71ed9b4 (live: selectors unverified) |
| 16 | Telegram bot fork | WS4 | done (cf225a1, 05ca9e8); user: set-token + pair |
| 17 | Watchers + reports | WS4 | done (95a6ba9); hub wiring → WS0 Inbox |
| 18 | Control app | WS5 | todo |
| 19 | Autostart, wiring, resource check | WS5 | todo |
| 20 | Office view | WS5 | todo |

## 6. Agent log
- 2026-09-30 00:13–03:03 · planning chat · Requirements gathered with the user
  (see §8 User decisions). Plan approved at 03:03.
- 2026-09-30 03:04 · WS0 · Tool check: git, gh (logged in as Sndcooper,
  scopes repo/workflow), node v24.16.0, npm, uv 0.12.19, claude CLI, codex CLI
  and Codex app present. **Missing: Python 3.13** (WS1 installs it via uv for
  Windows-MCP). Available Pythons: uv 3.11.16, system 3.10.0.
- 03:05 · WS0 · Branch `voicevibe-automation` created from `main` 3bf32b7
  (main == voicevibe-assistant). Remotes unchanged.
- 03:05 · WS0 · Created `Repos\`, `venvs\{uv-cache,wheelhouse,hf-cache,node\cache}`.
  An empty `venv's\` folder already existed (user-made) — left untouched; it
  can be deleted.
- 03:06 · WS0 · User env vars set (User scope): `UV_CACHE_DIR`, `HF_HOME`,
  `npm_config_cache` → under `venvs\`. Copied `~\.cache\huggingface` (3.14 GB:
  laya, faster-whisper large-v3-turbo, base.en, tiny.en) to `venvs\hf-cache`
  (original left in place).
- 03:07 · WS0 · Built `venvs\voicevibe` (CPython 3.11.16) from an exact freeze
  of the old `.venv` (57 packages incl. cuda, screen, wakeword, py-spy) + `-e`
  Voice_Vibe. Wheelhouse: 57 files, 1.25 GB, plus `voicevibe-requirements.txt`
  (pyperclip 1.9.0 is sdist-only → `--prefer-binary`).
- 03:18 · WS0 · `run.bat` now uses `..\venvs\voicevibe` (falls back to
  `.venv`) and sets HF_HOME/UV_CACHE_DIR if unset. Tests on the new venv:
  **465 OK, 8 skipped**. `run.bat --check`: GPU inference works, mic `[3]
  Microphone (Realtek(R) Audio)` chosen over the default Stereo Mix, clipboard
  ok. Commit `fa700cd` "Run from the shared ..\venvs environment and model
  cache".
- 03:20 · WS0 · Wrote root `TASK.md` (rules, build-on map, interfaces §3,
  ownership, workstreams) and this CONV.md; old `Voice_Vibe\CONV.md` moved to
  the §12 appendix and replaced by a pointer file.
- 03:22 · WS0 · Pushed `voicevibe-automation` to SndcooperPrivate (tracking
  set). User asked for parallel prompts → handed out WS1–WS4 start prompts
  (TASK.md §5). WS0 continues with T2–T4 in its own chat.
- 03:32 · WS1 · Claimed WS1 (chat "WS1 kiro"): TASK.md §6 + §4 board. Env vars
  present in session; Repos\ empty; branch voicevibe-automation @ fa700cd.
- 03:35 · WS1 · Shallow-cloned 10 repos into Repos\ (HEADs in THIRD_PARTY.lock).
  Downloaded FreeLLMAPI v0.13.2 portable win.zip → `venvs\freellmapi\app\`
  (zip deleted). `npm i -g @jackwener/opencli@1.8.8` with prefix `venvs\node`
  (17 pkgs). opencli skills (adapter-author, autofix, browser, usage) from the
  pinned clone via `npx skills@1.7.0 add … -g --copy -a claude-code codex
  kiro-cli` → `~\.claude\skills`, `~\.agents\skills`, `~\.kiro\skills`.
  Browser Bridge extension v1.0.24 unpacked to
  `venvs\node\opencli-extension\v1.0.24` (user loads it in Edge).
- 03:38–10:23 · WS1 · STALL: `opencli doctor` blocked waiting for the Edge
  extension (not loaded) and the chat sat on it; user cancelled. Lesson: all
  WS1 probes / doctor checks now run with timeouts. OpenCLI daemon (node PID
  11464) left running (auto-started by opencli; harmless).
- 10:25 · WS1 · uv Python 3.13.15 installed; `venvs\windows-mcp` (py3.13).
  **Windows-MCP HEAD 0.8.6 needs Python ≥3.14** → pinned **0.8.5** (≥3.12),
  clone checked out at tag v0.8.5 (30c1472). `venvs\windows-mcp\config.toml`
  excludes PowerShell/Registry/FileSystem. User env
  `ANONYMIZED_TELEMETRY=false` (User scope; telemetry is env-only). Read-only
  stdio probe via MCP SDK: 17 tools listed, the 3 excluded absent.
- 10:27 · WS1 · Laya 0.3.22 + torch 2.11.0+cu128 + transformers 5.17.0 and
  agent-reach 1.5.0 were already in venvs\voicevibe (installed by another
  stream) — not reinstalled.
- 10:30 · WS1 · FreeLLMAPI desktop defaults to **127.0.0.1:31415**, not 3001.
  Set `"port": 3001` in `%APPDATA%\FreeLLMAPI\config.json` (the app's own
  setting) so TASK §2 / llm.py `BASE_URL` hold unchanged. Verified: /v1/models
  → 401 on 127.0.0.1:3001 (no key yet). LAN access stays off.
- 03:32 · WS2 · Claimed WS2 (chat "WS2 kiro") in TASK.md + §4. Plan: T5 →
  T6 → T7 → T8 → T9 → T12, tests first, one commit each. src\vvhub doesn't
  exist yet and Repos\ is empty → coding against §3 with fakes.
- 03:32 · WS3 · Claimed WS3 (chat "WS3 kiro"): TASK.md §6 + §4 board. Order:
  T14 browser → T15 social → T11 research → T10 notes. src\vvhub not present
  yet (WS0 T2 pending) → coding against §3 with local fakes.
- 03:33 · WS4 · Claimed WS4 (chat "WS4 kiro"): TASK.md §6 + §4 board. Order:
  T13 GitHub skill + watcher → T16 Telegram bot fork → T17 scheduler +
  reports. src\vvhub not present yet → coding against §3 with fakes; no
  real repo creation / push to real repos / messages in tests.
- 03:40 · WS3 · OpenCLI 1.8.8 already installed by WS1 in venvs\node. Installed
  into venvs\voicevibe (uv, pinned): trafilatura 2.2.0, notion-client 3.1.0,
  agent-reach 1.5.0 (from Repos\Agent-Reach @a19a171), mcp 2.2.0 (+deps incl.
  pywin32 312, httpx2). `opencli doctor`: daemon OK on 19825, **Browser Bridge
  extension not connected** (user must load `venvs\node\opencli-extension`
  unpacked in Edge — blocks live Edge checks, not tests).
- 03:50 · WS3 · T14 done. Commit `7f1cf03` "Add the browser layer: Edge via
  OpenCLI, Zen via Windows-MCP, and a browser skill", pushed. Files:
  `src\vvhub\browser\{__init__,drivers,opencli,services,untrusted}.py`,
  `src\vvhub\skills\browser.py` (actions open_website, summarize_page),
  `tests\{test_browser,ws3_fakes}.py` (24 tests). Decisions: OpenCLI is run as
  `node …\main.js` (never `opencli.cmd`: cmd.exe re-parses `& | %` in
  dictated text), positionals after `--`; exit codes → typed kinds (69 bridge,
  77 auth…). Edge page read = `browser <s> bind → extract → unbind` (never
  owns/closes the user's tab). Zen read = Windows-MCP `Scrape(use_dom=True,
  use_sampling=False)` over on-demand stdio, `ANONYMIZED_TELEMETRY=false`,
  PowerShell/Registry/FileSystem excluded. Open = browser exe + one http(s)
  URL arg. Browser choice: spoken name > foreground process > last > Edge.
  Web text reaches LLMs only via `untrusted.fence()` + DATA_ONLY prompt.
  Suite: 571 run, only error = `test_vvbot` import (WS4's untracked files,
  mid-edit; not touched).
- 03:57 · WS3 · T15 done. Commit `71ed9b4` "Add the social skill and an
  OpenCLI plugin for LinkedIn posts, Instagram and GitHub notifications",
  pushed. Files: `src\vvhub\skills\social.py` (actions linkedin_post,
  instagram_post [critical]; linkedin_feed, linkedin_messages,
  instagram_notifications), `integrations\opencli-plugins\voicevibe\`
  (lib.js + linkedin-post / instagram-notifications / github-notifications,
  site `voicevibe`, JS so no esbuild), tests `test_social.py` (24),
  `test_opencli_plugins.py` + `tests\opencli_plugins\lib.test.mjs` (node:test,
  8, fake page). Instagram post = OpenCLI built-in `instagram post --media`;
  LinkedIn reads = built-ins `timeline`/`inbox`. Post gate: hard checks
  (length, email/phone/keys, injection text) → Laya `yes_no` ≥0.6 (Laya
  missing = no post) → approval → **approval must be decided on voice/ui**
  (Telegram yes is refused for posts: user said never post without them
  present) → one OpenCLI call, never retried; timeout = "may already be
  live". Blocked plans become action `say` so nobody is asked to approve an
  error. `linkedin-post` is dry-run unless `--send` (like OpenCLI's
  `connect`/`safe-send`). Bug found by tests + fixed before commit: a denied
  approval passed in made the skill re-ask. Plugin installed locally:
  `opencli plugin install …\integrations\opencli-plugins\voicevibe` (junction
  in `~\.opencli\plugins\voicevibe`; undo: `opencli plugin uninstall
  voicevibe`); `opencli voicevibe --help` lists the 3 commands. **Not
  verified live** (bridge not connected, and no posting allowed): LinkedIn
  composer / IG `/api/v1/news/inbox/` / GitHub notifications selectors.
  Suite: **666 OK, 12 skipped**.
- 04:03 · WS3 · T10 done (before T11 so research can save through it).
  Commit `0997240` "Add the Notion notes skill: topic pages picked by Laya,
  transcripts, Markdown API with chunking", pushed. Files:
  `src\vvhub\skills\notes.py` (actions note_this, make_notes,
  save_transcript; `NotionNotes` service reusable by research/reports:
  `layout()`, `create_page`, `append`, `add_to_section(section, title, md)`),
  `tests\test_notes.py` (14). Built on notion-client 3.1.0 `AsyncClient.request`
  with Notion-Version **2026-03-11** and Notion's native Markdown endpoints
  (`POST /v1/pages {markdown}`, `PATCH /v1/pages/{id}/markdown`
  insert_content end) — the md→blocks libs are archived since Notion added
  this (Feb 2026). Chunking: ≤12k chars/request, no line >1900 chars.
  Layout: user-shared page "Voice Vibe" → Notes / Transcripts / Research /
  Reports (created if missing, ids cached in `%LOCALAPPDATA%\VoiceVibe\notion.json`).
  Token: keyring `notion_token`; setup: `..\venvs\voicevibe\Scripts\python.exe
  -m vvhub.skills.notes setup` (hidden prompt). Topic page: exact title match
  → Laya `score` per topic (≥0.5) → new page (LLM 2–5 word title). Redacted
  context is never read. Transcript = `hub.store.turns(today_conversation())`.
  Not verified live: needs the user's Notion token. Suite: 698 run; only
  failures = WS4's untracked `test_scheduler` / `test_reports` (mid-edit).
- 04:07 · WS3 · T11 done. Commit `d3c6520` "Add the research skill: OpenCLI
  search, trafilatura/Jina/OpenCLI reading, Laya relevance filter, fenced LLM
  digest", pushed. Files: `src\vvhub\skills\research.py` (actions research
  [background job], research_status), `tests\test_research.py` (11, incl.
  prompt-injection + SSRF tests). Pipeline: named URLs or OpenCLI
  `duckduckgo search` → Laya `score` on results (≥0.3) → read via
  trafilatura → Agent-Reach Jina `WebChannel.read` → OpenCLI `web read`
  (JS pages) → Laya `score` on pages (≥0.4, top 4) → LLM digest ("SUMMARY:"
  line spoken) with sources fenced → local `%LOCALAPPDATA%\VoiceVibe\research\
  *.md` + Notion Research page + `add_watch_item(source="research")` +
  `notify` to bot/ui. Every URL passes Agent-Reach's
  `normalize_public_http_url` (no localhost/LAN/credentials). Injection test:
  hostile page + hijacked LLM reply → no approvals, only read commands,
  forged fence marker neutralised, sources flagged in digest. LLM busy →
  extracts saved. Suite: **722 OK, 12 skipped**.
- 04:10 · WS3 · Commit `bd5dfef`: pyproject `web` extra (trafilatura 2.2.0,
  notion-client 3.1.0, mcp 2.2.0; Agent-Reach from the clone, comment says
  why). Suite 722 OK. Pushed.
- 04:11 · WS3 · Verified: `vvhub.skills.discover()` loads browser / social /
  research / notes with no import errors; live read-only fetch of
  en.wikipedia.org/wiki/Solar_panel via `Fetcher` → trafilatura, 12000
  chars. **Not verified live** (needs the user): anything through Edge
  (Browser Bridge not connected), Zen (Windows-MCP venv not there yet),
  Notion (no token), any post (never without the user present).
  **User to-do:** (1) Edge → edge://extensions → Developer mode → Load
  unpacked → `venvs\node\opencli-extension`, then `opencli doctor`;
  (2) Notion: create an internal integration, create/share a page named
  "Voice Vibe" with it, run `..\venvs\voicevibe\Scripts\python.exe -m
  vvhub.skills.notes setup` from `Voice_Vibe\` (PYTHONPATH=src); (3) first
  real LinkedIn post: only with you at the laptop (voice/ui approval).
  WS3 T14/T15/T11/T10 all committed; WS3 idle until selectors can be
  checked live or other streams need changes.
- 03:50 · WS4 · T13 done. `src\vvhub\skills\github.py` (GitHubSkill: status,
  list_prs, list_repos, create_branch, commit, push, create_repo, create_pr;
  gh + git via argument lists through an injectable async runner, no shell;
  GIT_TERMINAL_PROMPT=0/GH_PROMPT_DISABLED=1; push/create_repo/create_pr
  critical → refused unless approval.status == "approved"; decision can only
  escalate; commit/push/PR refuse the default branch (origin/HEAD, plus
  main/master always; fallback main/master/trunk), detached HEAD; commit =
  `git add -u` only; push never forced; repos private unless "public" asked;
  spoken names normalised + option-proof). `src\vvhub\skills\watchers.py`
  (GitHubWatcher via `gh api`: new owned repos, PRs involving me, notification
  comments/mentions/reviews; skips CI/commit/release noise; key per event →
  WS0 `Store.add_watch_item`, dedupe by UNIQUE(source,key); per-source error
  isolation; `poll_all` with state file `watchers.json`, 24 h first lookback,
  5 min overlap; WatchersSkill "check_now"). Tests `test_github_skill.py`,
  `test_watchers.py` (fake runner; no git/gh/network). Suite **529 OK, 8
  skipped**. Commits `a8e5b7f`, `b1276d1`, pushed. Depends on WS0's
  uncommitted `vvhub/{__init__,schemas,store}.py` + `skills/{__init__,base}.py`
  (present in the shared tree). Not live-checked against real gh (read-only
  check deferred).
- 03:45 · WS2 · Survey done. WS0's `src\vvhub\{schemas,bus,dispatch,store,
  protocol,secrets,skills\base}.py` now exist (uncommitted) → coding against
  them directly: `dispatch` calls `await smart_router.decide(hub, text, ctx)
  -> Decision|None`, `policy.needs_approval(decision, plan) -> bool`,
  `await approvals.request(hub, plan, conversation=)`; `hub.store/.bus/.skills`.
  Repos cloned by WS1: laya 6d942c9 (Apache-2.0; `Router.predict`/`Agent.predict`
  /`ONNXAgent.predict(state, questions, min_confidence=)`, answers carry
  `answer_confidence`; ONNXAgent still imports torch via laya.common),
  Windows-MCP b2016c0 (Snapshot/Screenshot `region`, `use_dom`,
  `ANONYMIZED_TELEMETRY=false`, `--exclude-tools`), opencli 2413694
  (clis/codex: composer = last `[contenteditable]`, needs CDP port → we use
  UIA instead), freellmapi 6def0ff (`model:"auto"`, unified Bearer key; pool
  exhaustion = 429 `rate_limit_error` + `retryAtMs`, else 502/503).
  Laya NOT installed in venvs\voicevibe yet (no torch/transformers); model
  weights are in hf-cache (english 843 MB + multilingual 644 MB).
  Live read-only: Codex app = `ChatGPT.exe` from package OpenAI.Codex; Claude
  app = `claude.exe`; Kiro = `kiro-cli` in WindowsTerminal (title "kiro: …");
  no Kiro IDE installed; VS Code = `Code.exe`.

- 03:47 · WS0 · T2 done. vvhub skeleton committed `afab78c` + pushed:
  server (127.0.0.1:53874, token file, /health 401 without token, /ws hello
  4401 on bad token), protocol, bus, schemas (Decision/Plan/Result/Approval,
  `is_critical`), secrets (keyring), store (+2-day purge), dispatch pipeline
  (TASK.md §3.9 now documents the exact hooks WS2 plugs into), skills
  auto-discovery + echo ("ping hub"), doctor framework (WS1 adds `@check`s).
  pyproject: `hub` extra (fastapi 0.142.0, uvicorn 0.54.0, websockets 17.1,
  keyring 25.7.0, installed in venvs\voicevibe), `vvhub` script, package
  added. Suite **529 OK, 8 skipped** (incl. WS4's tests). Live: serve up,
  unauthenticated /health → 401, `python -m vvhub doctor` all OK.
  Added rule 3 addendum: shared tree → no switch/stash/reset/restore; commit
  with `git commit -m ... -- <paths>`.
- 04:10 · WS4 · T16 done. `src\vvbot\` = fork of n3d1117/chatgpt-telegram-bot
  @ df4dcaa (GPL-2.0-only; LICENSE copied, UPSTREAM.md lists every file's
  origin/changes, headers on derived files). Kept: handler layout/run()
  (`telegram_bot.py`), main→`__main__.py`, utils subset, plugin_manager +
  plugin base + dice (lazy imports; `/plugins`, `/run`). Replaced: OpenAI
  chat → hub `request` (source "telegram"), Whisper → hub `transcribe`
  (voice/audio/video notes → 16 kHz mono WAV via **PyAV**, no pydub/ffmpeg;
  60 s bot-side wait), allowlist → `pairing.py` (hermes-agent pairing pattern,
  MIT: 8-char code from `python -m vvbot pair` on the PC, SHA-256 at rest,
  1 h TTL, lockout after 5 misses, private chat + single owner, owner id in
  keyring `telegram_chat_id`). New: `approvals.py` cards (✅/❌ inline
  buttons `ap:<id>:y|n`, expiry → "treated as denied", sweep every 15 s),
  `answers.py` strict yes / loose no for text + voice notes (ambiguous never
  approves; reply-to-card targets one of several), `hub_client.py` (role bot,
  token re-read per attempt, backoff, 4401 reported), notify → owner chat,
  `drop_pending_updates` so stale "yes" can't hit new cards. Token in keyring
  `telegram_bot_token` (`run.bat set-token`, getpass). httpx logs silenced
  (URLs carry the bot token). venvs\telegram-bot created (py3.11.16):
  python-telegram-bot 21.9, websockets 17.1, keyring 25.7.0, av 18.1.0
  (`src\vvbot\requirements.txt` = full freeze). Launcher `src\vvbot\run.bat`.
  Tests `test_vvbot.py` (58, no telegram needed) + `test_vvbot_telegram.py`
  (3, skipped in app venv; OK in the bot venv). Suite **644 OK, 12 skipped**.
  Live (loopback only, temp VVHUB_HOME): bot HubClient ↔ real `vvhub serve`:
  ping→pong, request "ping hub"→"Hub is online.", transcribe without Voice
  Vibe → error no_transcriber, wrong token → rejected. `run.bat status`:
  token missing, not paired (user action). No Telegram contact made.
  Commits `1e8a8da` (BOM fix), `cf225a1`, `05ca9e8`, pushed.
- 04:15 · WS4 · T17 done. `src\vvhub\skills\reports.py` (structure from
  OpenJarvis `agents/morning_digest.py` @ 5e5f5ef, Apache-2.0: collect per
  section → omit empty → deliver; no LLM step, so the summary only states
  counts/titles from the store). Sections = rule 16: new repos, PRs, new
  comments (any `*_comment/_mention/_reply/_review` watch item: GitHub, IG,
  LinkedIn), posts (`*_post`), research (watch items `research*` + done
  `research` jobs), Laya auto-decisions (decisions without critical /
  needs_approval, not chitchat), pending approvals. Kinds containing
  "commit" never reported. Channels independent: HTML (Jinja2 autoescape,
  http(s)-only hrefs, rel=noopener, lang/landmarks/focus styles, dark mode)
  → `%LOCALAPPDATA%\VoiceVibe\reports\YYYY-MM-DD-HHMM.html`; Notion via the
  notes skill (`save_report(title, markdown)` or `run(Plan(action=
  "save_report", args={title, markdown}))` → url; markdown escapes link
  syntax); Telegram = `notify` to the bot (summary ≤4000 chars); spoken =
  `reports\spoken.json`, `take_spoken()` returns it once. ReportsSkill
  (`read_report`, `report_now`; phrases "read my report", "what did i
  miss", "report now"). `src\vvhub\scheduler.py`: APScheduler 3.11.0
  AsyncIOScheduler (cron 08:00 + 20:00 local, coalesce, 1 h misfire grace;
  15-min tick = watcher poll + catch-up), asyncio fallback loop without
  APScheduler; catch-up from `reports\scheduler.json`: any passed,
  unreported slot → ONE report covering everything since the last one;
  failed report leaves the slot open for the next tick. CLI
  `python -m vvhub.scheduler report --now [--no-poll] [--html-only]`
  (doesn't consume a slot, never sends Telegram). Installed apscheduler
  3.11.0 into venvs\voicevibe (jinja2 3.1.6 already there); pyproject
  `reports` extra added. Tests `test_reports.py` (19), `test_scheduler.py`
  (13). Suite **711 OK, 12 skipped** (a transient WS2 mid-edit failure in
  test_smart_router/test_evals cleared on re-run). Live read-only: `report
  --now --html-only` → real `gh api` reads (0 new items in 24 h, no errors),
  wrote `reports\2026-09-30-0407.html`, "Morning report: nothing new."
  Commit `95a6ba9`, pushed. Tool gotcha: this shell tool drops ALL output
  when it contains non-ASCII (e.g. "·"): redirect to a file and print
  ASCII-escaped.
- 14:50 · WS4 · Completion audit (user asked). All T13/T16/T17 commits are
  ancestors of HEAD and HEAD == SndcooperPrivate/voicevibe-automation.
  Follow-up from Inbox: reports now use WS3's `notes.notion.add_to_section(
  "Reports", …)` and count WS3's bare `post`/`comment` watch kinds (were
  silently dropped). Commit `c50e122`, pushed. Suite **938 OK, 13 skipped**.
  Still open (not WS4 paths): WS0 hub wiring (scheduler, `vvhub report`,
  spoken-on-arm) and app.py `transcribe` handler; user: bot token + pairing,
  Notion token. THIRD_PARTY.lock (WS1, uncommitted) already lists
  chatgpt-telegram-bot and OpenJarvis.
- 03:55 · WS0 · Acted on the user's read-only audit: (1) my T2 log entries
  were stamped 04:00 but written ~03:47 — corrected to 03:47. (2) TASK.md §3.5
  approvals API corrected to the real signature `request(hub, plan,
  conversation=None) -> Approval`; §3.7 now lists `smart_router.decide` and
  `policy.needs_approval`; §3.9 pipeline and §4 ownership already updated.
  (3) Windows-MCP pyproject says `requires-python >=3.14` (verified in
  Repos\Windows-MCP) → TASK.md now says py3.14 (uv cpython-3.14.7), own venv
  `venvs\windows-mcp`, still a separate on-demand process. (4) VS Code closed
  by user → quit the running Voice Vibe (old .venv, PID 63308) with
  Ctrl+Alt+Shift+Q (clean exit), deleted `Voice_Vibe\.venv` and the empty
  `venv's\`, relaunched via run.bat → PID 71568 runs from
  `venvs\voicevibe` and loaded large-v3-turbo + base.en from
  `venvs\hf-cache`. Open question 8 resolved. (5) Note for bisecting: WS4's
  a8e5b7f/b1276d1 need afab78c (vvhub core) — fine at the tip.
  Timestamp rule: take times from `Get-Date`, never estimate.
- 04:07 · WS2 · **Installed Laya** into venvs\voicevibe (no WS1 reply in
  Inbox): `uv pip install --torch-backend=cu128 laya==0.3.22
  torch==2.11.0+cu128 transformers==5.17.0 safetensors==0.8.0` (+ deps jinja2
  3.1.6, sympy 1.14.0, networkx 3.6.1, mpmath, typer, shellingham,
  setuptools 81). torch sees the RTX 5060. Windows torch wheels bundle their
  own CUDA DLLs, so faster-whisper's nvidia-cublas-cu12 12.9 is untouched.
  Loads offline from hf-cache (`HF_HUB_OFFLINE=1` works).
- 04:07 · WS2 · **T5 done** — commit `a6a1948`, pushed. Files:
  `src\vvhub\{laya_engine,smart_router}.py`, `src\vvhub\evals\{__init__,
  __main__,runner}.py` + `intents.jsonl` (81 phrases, all 8 categories ≥10,
  expected action + critical flags for T6), tests `test_{laya_engine,
  smart_router,evals}.py` (fake Laya backends; no model). Suite **722 OK,
  12 skipped**.
  - `laya_engine`: §3.7 `decide/score/yes_no`; tiers gpu (laya.Router CUDA,
    english only) / onnx (ONNXAgent INT8 if an export exists) / cpu / keywords
    (no model; confidence capped 0.5 so policy always asks); lazy load, idle
    unload after 600 s (`Engine.reap()`), failed load remembered, shared
    engine falls back to keywords. `$VVHUB_LAYA_TIER` forces a tier,
    `$VVHUB_LAYA_ONNX` points at an export.
  - `smart_router.decide(hub, text, ctx) -> Decision|None` (level 1 so far).
    Laya reads request + app + window title only, never OCR/DOM (rule 11).
    Measured on the eval (English ckpt, GPU): one 8-way `choice` 60.5% →
    eight `noul` questions in one pass 81.5% → + lexical prior (0.25 ×
    overlapping words) **91.4%**; held-out 96 other phrasings: noul 76%,
    prior alone 69%, combined 87.5%. Confidence = Laya's own yes-prob (the
    prior can't inflate it); < 0.55 → "low confidence".
  - `python -m vvhub.evals [--tier] [--json] [--limit]`: gpu 91.4%, load
    11.2 s, p50 58 ms / p95 95 ms, RSS 1.07 GB after load → 2.1 GB after the
    first passes (CUDA kernels); cpu-torch 90.1%, p50 795 ms, RSS 2.3–2.6 GB
    (**over the 1.5 GB budget → CPU laptops need the ONNX INT8 tier**);
    keywords 79.0%, <1 ms, 28 MB. `python -m vvhub eval` needs WS0's
    __main__ (Inbox). Critical flagging 0/10 until T6.
- 04:31 · WS2 · **T6 done** — commit `22cb5a3`, pushed. Files:
  `src\vvhub\policy.py` (new), `src\vvhub\skills\app.py` (new),
  `smart_router.py`, `evals\runner.py`; tests `test_policy.py` (incl. 2
  end-to-end through WS0's real dispatch + Store), `test_app_skill.py`,
  `test_smart_router.py`. Suite **760 OK, 12 skipped**.
  - Level 2: actions = union of `actions` of the skills in the chosen
    category; one `noul` per action ("Does the user want to <desc>?") + the
    same lexical prior. Measured (38 rows with a known action, incl. planned
    screen/code actions): choice 27/38, noul 33, noul+prior **35/38**. Floor
    0.2 → no action → unhandled; a single-action category needs yes ≥ 0.5
    (so "hello there" no longer maps to echo's ping).
  - Risk: a `noul` "would this publish/post/send/…/push…?" asked in the same
    level-1 pass → `Decision.risk`.
  - **Confidence = score margin** winner vs runner-up (level 1), not the raw
    yes-prob: the checkpoint is uncalibrated (its temperatures are rejected
    at load); raw ≥ 0.55 asked on 44/71 safe requests. Over 177 requests
    (eval + held-out) margin ≥ 0.3 auto-acts on 66% with 4 wrong, sends 15/19
    routing errors to a question. Level-2 margin doesn't gate (right 35/38
    even when thin); keyword tier confidence capped at 0.1 (always asks).
  - Targets: optional duck-typed skill hooks `target_options(decision,
    context) -> {label: desc}` (≤ 20) and `default_target(context)`; a label
    the request names by a word only it has wins without Laya; else Laya
    `choice` accepted at ≥ 0.6; else default. Skills without the hook get
    `Decision.target` = free-text argument (`smart_router.argument`: "called
    X" → X, research/notes/app leading verb stripped, notes/social "about X",
    social "saying X" → "exactly: X", "" if none) — matches what WS3/WS4
    skills and their tests pass as target.
  - `policy`: `preflight(text, decision, skill)` in the router (so the stored
    decision says `auto: act as you` or `ask: <reasons>` → the decision log
    reports use), `needs_approval(decision, plan)` for dispatch: floor
    (critical name/Plan/Decision/needs_approval), low confidence (< 0.3),
    risk ≥ 0.9, or risk ≥ 0.5 + a spoken critical word, or a forwarded
    `prompt`/`message`/`body` arg naming a critical act (Claude Code could
    push). Never lowers anything; speak-only plans (`say`) don't ask.
  - `skills/app.py` (category app): focus_window (targets = live Alt+Tab
    windows via `winctl.top_level_windows`, match via `winctl.match_window`,
    focus executed by Voice Vibe through `run_steps [{"focus": {hwnd,
    title}}]`), list_mics / set_mic via `list_mics`/`set_mic`, loopbacks
    (Stereo Mix…) never listed or set (rule 20). Nothing critical.
  - Eval (gpu): category 91.4%, action 94.4% (18), critical flagged 9/10
    (miss: "send a message to Rahul on LinkedIn" → linkedin_messages, which
    only reads), asked on safe **9/71** (2 of them real misroutes caught),
    p50 94 ms (two passes).
- 04:37 · WS2 · **T7 done** — commit `f9554e5`, pushed. `src\vvhub\approvals.py`
  + `tests\test_approvals.py` (21, fake bus + WS0's real in-memory Store,
  one end-to-end through dispatch). Suite **781 OK, 13 skipped**.
  - `await approvals.request(hub, plan, conversation=)` (dispatch) and
    `await approvals.request(action, preview, critical=True)` (§3.5, uses
    the hub bound by `approvals.bind(hub)` or the first dispatch call).
    Returns `schemas.Approval` (status approved/denied/expired, channel,
    decided_by).
  - Order: voice (Voice Vibe connected → `confirm {prompt, preview, timeout
    15, approval_id}`; a reply with `unavailable: true` = no armed session →
    next channel; voice no/timeout is final) → telegram (`approval_request
    {approval: <record>, timeout: 300}` — matches WS4's `vvbot.approvals`
    desk) → ui (same message, WS5) → nobody = denied. Timeout = "expired"
    (deny). Voice questions serialized (one mic); cards can overlap.
    `pending()` lists open ones; `bind()` expires rows left pending by a
    previous run. Every request + outcome in the store's approvals table.
  - Answers re-checked by the hub, downgrade only: strict yes (same rule as
    `voicevibe.confirm` / `vvbot.answers`), then Laya `yes_no({question:
    preview, answer}, "Is the answer an unambiguous yes?") ≥ 0.4` (measured:
    clear yeses 0.60–0.82; no / "yes but not now" / "Thank you." ≤ 0.27).
    Button presses skip the text checks; Laya missing → strict rule only.
  - Spoken prompt = preview's first 160 chars as a question with yes-words
    stripped (an echo of the question can't read as its answer); full
    preview sent alongside for the screen.
- 04:49 · WS2 · **T8 done** — commit `975d85b`, pushed. New
  `src\voicevibe\{privacy,focus,context}.py`, `src\vvhub\skills\screen.py`;
  targeted edits to shared `app.py` (+32: build ContextBuilder/LocalScreen,
  local screen phrases checked **before** `router.route` — the router's
  `focus(?: on)? <window>` rule would otherwise treat "focus on my cursor" as
  a window name; warm-up + crop purge thread at start; frame stop on quit;
  class default `local_screen = None` for piecemeal test instances),
  `config.py` + `config.toml` `[screen]` keys `focus_seconds = 180`,
  `region_size = [800, 500]`, `privacy_deny_processes/titles = []`. Tests
  `test_{privacy,focus,context,screen_skill}.py` (58, all OS sources
  injected). Suite **841 OK, 13 skipped**.
  - `privacy.PrivacyGuard`: built-in deny = password managers (process +
    title), banking/payments (whole-word title rules: "<X> bank", netbanking,
    PayPal/Paytm/PhonePe/GPay/UPI, Zerodha/Groww…), private browsing, Windows
    Security prompts; config can only add; "computer don't look at this
    window" marks the hwnd, "you can look at this window again" lifts only
    that mark. Checked: foreground + window under the pointer, and (deep)
    every window overlapping the region → bundle = `{window: {process},
    pinned, redacted: true}` and nothing else is read.
  - `focus.FocusPin`: ~800×500 around the pointer, slid inside its monitor
    (multi-monitor via MonitorFromPoint), 180 s timeout, click-through outline
    in the orb's session blue on its own thread (overlay's layered-window
    helpers, like Badges).
  - `context.ContextBuilder.bundle(deep=False, pin=None)` → §3.3: shallow =
    window, caret_text (UIA focused element), pointer_element (UIA
    ElementFromPoint + ≤6 named ancestors), region rect, browser name/title,
    pinned; deep adds selection (Ctrl+C round trip), region crop PNG in
    `%LOCALAPPDATA%\VoiceVibe\crops\crop-<ms>.png` + Windows OCR, browser URL
    (address-bar UIA). `purge_crops()` (2 days) runs at app start.
    `LocalScreen`: focus on my cursor / unfocus / what's this (element name +
    type + first ancestor + app; one retry for a sleeping Chromium tree;
    OCR line fallback) / don't look at this window / you can look again.
  - Hub `skills/screen.py`: `fetch_context(hub, deep, pin)` (get_context;
    accepts reply `{context: {...}}` or flat), actions focus / unfocus / read;
    `deep_context()` adds a **Windows-MCP `Snapshot(region=…, use_vision=
    False, use_dom=<browser>)`** via WS3's `browser.drivers.WindowsMCP`
    (→ `region.ui_text` or `browser.dom_text`), skipped when not installed
    (venvs\windows-mcp doesn't exist yet) and never for a redacted bundle.
  - **Live (read-only)**: bundle on the real desktop (Edge/Instagram in
    front): window, pointer element "Photo by … Button" + 3 ancestors,
    region crop saved (temp dir) + OCR text; warm shallow ≈ 20 ms (element
    10–150 ms, caret 4 ms, windows 3 ms); first call ≈ 1 s (COM setup →
    `warm()` at start). Selection (Ctrl+C) and the on-screen frame not
    exercised live. The running Voice Vibe (PID 71568) still has the old code
    until restarted.
- 04:56 · WS2 · **T9 done** — commit `c42dac9`, pushed. New
  `src\vvhub\llm.py` + `tests\test_llm.py` (15, httpx MockTransport, no
  network); `skills/screen.py` gains explain / summarize (+10 tests);
  `pyproject.toml` new extra **`brain`** (laya 0.3.22, torch 2.11.0,
  transformers 5.17.0, safetensors 0.8.0, httpx 0.28.1; CUDA laptops add
  `--torch-backend=cu128`). Suite **866 OK, 13 skipped**.
  - `llm.complete(messages, model="auto", max_tokens=800)`, `llm.vision(
    prompt, png_bytes, system="")` (§3.7) over FreeLLMAPI
    `/v1/chat/completions` (image as an `image_url` data-URL part). Key =
    keyring `voicevibe`/**`freellmapi_key`** (the unified key from FreeLLMAPI's
    Keys page). Loopback base URLs only. `LLMUnavailable(kind, spoken,
    retry_after)`: `exhausted` (429 — FreeLLMAPI already failed over, so no
    retry; "The free AI pool is used up for now. Try again in about N
    minutes." from Retry-After), `unavailable` (5xx/timeout after 2 retries),
    `offline` (nothing on :3001), `no_key` (missing / 401), `no_vision` (422),
    `rejected`. `vision` refuses non-PNGs and anything > 1400×1000 (crops
    only, rule 12).
  - "explain this" / "summarize this": deep context (Voice Vibe bundle +
    Windows-MCP region snapshot when installed); redacted → "That window is
    private"; crop read only if it's `crops\crop-*.png`; screen text fenced
    with WS3's `browser.untrusted.fence` + a data-only system prompt; vision
    for explain (text-only fallback on `no_vision`), text-first for
    summarize; reply spoken only if not `untrusted.suspicious` **and** Laya
    `yes_no({request, screen, answer}, "Does the answer correctly explain or
    summarize the screen text for the request?") ≥ 0.35` (measured on 10
    pairs: good 0.49–0.91; refusal / off-topic / injected "post to LinkedIn"
    / rate-limit text 0.05–0.20). Pool exhausted → the spoken message.
  - Eval now (gpu, screen actions registered): category 91.4%, action
    **96.2%** (26), critical 9/10, asked on safe 13/71.
  - **Not verified live**: FreeLLMAPI isn't running (nothing on :3001) and
    no `freellmapi_key` in the keyring. User: start FreeLLMAPI (installed by
    WS1 in venvs\freellmapi), add provider keys, then store the unified key:
    `..\venvs\voicevibe\Scripts\python.exe -c "from vvhub import secrets;
    secrets.set('freellmapi_key', input('key: '))"` (from Voice_Vibe\src).
    Note: FreeLLMAPI forwards prompts (and crops) to cloud providers.
- 05:26 · WS2 · **T12 done** — commit `a5d6d32`, pushed. New
  `src\vvhub\skills\code.py` + `tests\test_code_skill.py` (29, fake bus /
  windows / exe paths / OpenCLI; nothing typed); `profiles.py` +
  `PROMPT_BOXES` (Claude "Prompt|Reply|Message", Codex "Ask Codex|Ask for
  follow-up changes|Message|Prompt"); `context.py` bundle gains
  `focused_element {name, type, class}` (UIA GetFocusedElement). Suite on
  the tip (incl. WS0's c4de14a) **907 OK, 13 skipped**.
  - Tools: claude_app (claude.exe, not the claude-code binary), codex_app
    (ChatGPT.exe whose exe is in the **OpenAI.Codex** package — told apart
    from the ChatGPT app), vscode_terminal (Code.exe), kiro (terminal window
    titled "kiro"), claude_code (terminal titled "claude"). Choice: tool named
    in the words → router target if named → last used (`code.json` in the data
    dir) → most recent open one. `target_options`/`default_target` = open
    tools (T6 hooks).
  - Delivery via Voice Vibe `run_steps`, two batches with a check between:
    focus (+ click_named focus on the prompt box for apps; Ctrl+Shift+P
    "Terminal: Focus Terminal" for VS Code) → `get_context`: same hwnd in
    front and focused element is a text box / the terminal → type + Enter
    (apps: Shift+Enter between lines; terminals: one line). VS Code terminal:
    reads what runs there from the focused element name ("Terminal 1, pwsh");
    agent running → type the prompt; pwsh/bash/cmd → start `claude`/`codex`/
    `kiro-cli chat` with the prompt as one literal, shell-quoted argument
    (PowerShell curly quotes normalised; cmd `%` and `"` neutralised);
    anything else (python…) refused. Busy Kiro (spinner ◐◑◒◓ in title)
    skipped. Nothing typed if any check fails.
  - Codex: OpenCLI `codex send` (clis/codex, CDP injection + submit
    verification) when port 9238 answers and OpenCLI exists; else UIA.
  - "fix this": deep context read **before** switching windows (pin if set);
    private → refused; `untrusted.suspicious` screen text left out (said so);
    attached as quoted data inline for apps, as `%LOCALAPPDATA%\VoiceVibe\
    prompts\fix-<ms>.md` (2-day purge) for terminals.
  - Policy: prompt is `plan.args["prompt"]` → "fix the tests and push" asks
    first (forwarded critical word). Nothing critical by name.
  - Level-2 wording measured: first draft 34/37 actions, a second 32/37,
    final ("send a coding request to Claude, Codex, Kiro or the VS Code
    terminal" / "fix the error or bug that is shown on the screen right now")
    **35/37** (misses unchanged: "explain this code to me" → code category,
    "commit … message …" → list_prs). Eval now: category 91.4%, action 94.6%,
    critical 9/10, asked on safe 17/71 (mostly screen requests with thin
    level-1 margins).
  - **Live (read-only)**: on the real desktop the skill sees kiro,
    claude_app, codex_app, vscode_terminal open, picks the right hwnds, and
    plans all 5 sample requests correctly. UIA probe: VS Code exposes Edit
    "Message input" (Copilot chat) and the terminal; Claude and Codex windows
    exposed only title-bar elements to this process (Chromium tree asleep /
    window occluded), so their prompt-box names are from the earlier session
    (Claude "Prompt") and OpenCLI's source (Codex) — **not verified live**. No
    prompt was sent anywhere.
  - Finding: the pre-existing `profiles.py` "chatgpt.exe" profile (ChatGPT
    desktop shortcuts: ctrl+shift+o new chat…) also matches the Codex app,
    whose process is ChatGPT.exe. Left unchanged; flagging for the user.
- 05:26 · WS2 · **WS2 summary** — T5 `a6a1948`, T6 `22cb5a3`, T7 `f9554e5`,
  T8 `975d85b`, T9 `c42dac9`, T12 `a5d6d32`, all pushed; suite 465 → 907
  OK (13 skipped) with every stream's work. Blocked on others for a live
  end-to-end: WS0 `hub_client.py` (attach `app.context.bundle()` to
  requests; handle `confirm`, `get_context {deep, pin}`, `run_steps`,
  `list_mics`/`set_mic`), WS0 `python -m vvhub eval` subcommand, WS1
  THIRD_PARTY.lock entries + Laya ONNX INT8 export (CPU tier) +
  venvs\windows-mcp. Needs the user: FreeLLMAPI running + `freellmapi_key`,
  restart Voice Vibe (PID 71568 runs pre-T8 code). Scratch files in %TEMP%
  deleted.

- 05:27 · WS0 · T3 done, commit `c4de14a`: Voice Vibe history keep_days 2
  (config.py, config.toml, app.py, README), `history\saved\` never pruned,
  `History.save()` merges without duplicates, `is_save_command` exact
  phrases; "computer save this conversation" handled in
  `_do_command_or_insert` BEFORE the router (its "save" = Ctrl+S). Hub skill
  `skills/conversation.py` marks the kept days saved in hub.db.
  `tests/test_retention.py` (12). Suite 907 OK.
- 10:28 · WS0 · T4 done, commit `39a610a`, pushed: `src/voicevibe/hub_client.py`
  (daemon thread + asyncio + websockets; hello/token; reconnect 1→30 s;
  `request` returns None when down/slow → typed as heard; answers hub
  `confirm` (only while the session mic is open; errors = no), `get_context`
  (WS2 ContextBuilder), `run_steps`; `list_mics`/`set_mic`/`transcribe`
  report "no handler" until WS4/WS5 wire them). `app._do_hub` runs after
  Router + assistant fallthrough; `[hub].enabled` (default true).
  `tests/test_hub_client.py` (11, real uvicorn hub on a free port).
  **Bug found live and fixed before commit:** the 05:29 launch linked up, then
  the reconnect task was garbage-collected (asyncio holds only weak refs), so
  after the hub restarted the link never came back (/health connected=[]).
  Now strong refs + a regression test that restarts the hub with gc. Also the
  earlier live-check command hung the tool (it waited on run.bat); relaunch now
  uses Start-Process. Live: hub PID 25732, Voice Vibe relaunched 10:28, connected
  in 8 s (/health connected=["voicevibe"]). Suite **918 OK, 13 skipped**.
  Not verified: spoken "computer ping hub" (needs the user's voice).
- 14:50 · WS1 · Laya INT8 ONNX export done in temp `venvs\laya-export`
  (py3.11, torch 2.11.0+cpu, transformers 5.17.0, onnx 1.23.1, onnxscript
  0.7.2, laya from clone; HF offline). First run crashed on cp1252 (✅ print)
  → rerun with PYTHONUTF8=1. Kept `venvs\models\laya\laya.int8.onnx`
  (600 MB, where laya_engine looks); deleted fp32 laya.onnx/.data (1.7 GB)
  and the whole export venv.
- 14:52 · WS1 · User PATH += `venvs\node` (so agent-reach finds opencli);
  agent-reach doctor: web/Jina, rss, v2ex, bilibili ok; instagram/reddit warn
  (Edge extension), youtube/exa off (optional).
- 14:55 · WS1 · `src\vvhub\doctor.py`: WS1 checks laya, freellmapi,
  freellmapi key (user), opencli, opencli edge extension (user, via daemon
  /status — no blocking `opencli doctor`), windows-mcp (py3.13 + pin +
  exclusions), agent-reach (`doctor --json`, 60 s cap), notion token (user),
  telegram token (user). All probes time-bounded, injectable.
  `tests\test_doctor_components.py` (fakes only). Live `python -m vvhub
  doctor`: OK gh, keyring, laya (tier gpu, int8 onnx found), opencli 1.8.8,
  windows-mcp 0.8.5/3.13, agent-reach 4/16; USER freellmapi key, edge
  extension, notion, telegram; FAIL hub server (WS0's, not started) and
  freellmapi (had been closed → restarted, /v1/models 401 on :3001 = up).
- 14:58 · WS1 · Full suite **936 OK, 13 skipped**. Commit `40537fd` "Pin
  third-party repos in THIRD_PARTY.lock and add doctor checks …" (3 files:
  THIRD_PARTY.lock, src/vvhub/doctor.py, tests/test_doctor_components.py).
  My push raced WS4's; WS4's c50e122 sits on top and is pushed, so 40537fd
  is on SndcooperPrivate/voicevibe-automation (verified `git branch -r
  --contains`). §9 Repo intel filled for all 10 repos.
- 15:00 · WS1 · DONE except user-only steps: FreeLLMAPI provider keys +
  unified key into keyring, load the Edge extension, Notion/Telegram tokens.
- 14:50 · WS2 · Completion audit. All six WS2 commits on the remote tip;
  suite **938 OK, 13 skipped**. WS0's `39a610a` wires context-on-request,
  confirm, get_context, run_steps — 3 gaps posted to WS0 (Inbox 14:50).
  New since 05:26: venvs\windows-mcp and `venvs\models\laya\laya.int8.onnx`
  exist (WS1), THIRD_PARTY.lock lists laya (uncommitted, WS1). **ONNX tier
  eval**: category 86.4%, action **62.9%** (GPU 94.6%), critical 9/10,
  asked on safe 23/71, load 39.7 s, p50 562 ms, RSS 1.40 GB (fits 1.5 GB
  but leaves ~0.1 GB). FreeLLMAPI still not running (no :3001).
- 19:40 · WS2 · User asked for deep research (current architecture, repos,
  dependencies, what runs; new repos/features to automate everything by
  voice; new folder architecture). Wrote **`RESEARCH.md`** at the workspace
  root (not in git, 523 lines): §1 as-built system (processes/ports/RAM
  measured 19:15: hub 539 MB WS, FreeLLMAPI 98 MB on :3001, OpenCLI daemon
  43 MB; Voice Vibe not running), request flow, code map, 12 skills, repos,
  pinned deps, models/data/secrets, gaps; §2 ~70 projects researched in 4
  parallel web passes (desktop/browser automation, voice patterns + voice
  security, MCP integrations, memory/local AI/phone) with verdicts; §3
  voice-only automation catalogue with risk class per command; §4 proposed
  folder layout (vvhub core/brain/conversation/memory/security/tools/
  connectors/workflows, voicevibe audio/speech/input/control/screen/ui/link/
  security) + contracts + shim-based migration; §5 roadmap P0–P5 and new
  streams WS7–WS9 (proposed), memory budget; §6 8 questions for the user.
  Nothing installed, no code or folders changed; proposals need the user's
  OK and WS0 for §3/§4 changes.

- 15:12 · WS0 · User shared the WS1-WS4 completion reports and asked for the
  next plan + prompts. Checked: 23 commits after fa700cd, branch in sync with
  SndcooperPrivate, tree clean except room.npy; suite 938 OK, 13 skipped.
  `vvhub doctor`: laya (GPU + int8 onnx), freellmapi (:3001), opencli 1.8.8,
  windows-mcp 0.8.5 on py3.13, agent-reach 4/16 OK; red for the user:
  freellmapi_key, Edge extension, notion_token, telegram token. **Hub DOWN and
  Voice Vibe not running** (both stopped some time after the 10:28 launch;
  cause unknown, the hub had no file log -> F7). Running: FreeLLMAPI, OpenCLI
  daemon. TASK.md: rules 30 (LIVE LOCK) + 31 (short replies, time limits),
  WS0 follow-ups F1-F7, WS5 unblocked, Windows-MCP docs = 0.8.5 on py3.13.
  Gave the user follow-up prompts for the WS1-WS4 chats and a WS5 start prompt
  (not subagents: blocking subagents freeze this chat and lack the chats' context).
- 15:26 · WS0 · F1-F7 done, commit `19543ef`, pushed. Voice Vibe side
  (`app.py`, `hub_client.py`, `confirm.py`): `confirm` -> `{approved, answer
  (words heard), unavailable}`, unavailable when no session mic is open so
  approvals go to Telegram; `get_context` forwards `pin`; `list_mics` (names
  deduped across host APIs, no PortAudio refresh under an open stream) and
  `set_mic` (exact then substring match, refuses loopbacks, pinned for this
  run only); `transcribe` decodes voice notes with faster-whisper's PyAV
  `decode_audio` and the loaded model; `run_steps` via the Executor, dry runs
  only validate; on arm Voice Vibe sends `armed` and speaks the reply. Hub
  side (`server.py`, `__main__.py`, `protocol.py`): `armed` returns
  `reports.take_spoken()` once; the lifespan starts/stops WS4's ReportScheduler
  (only from `build_hub`, never in tests); `python -m vvhub report --now` and
  `python -m vvhub eval` forward to WS4/WS2; `serve` logs to
  `logs\vvhub.log` and writes "vvhub stopped" on a clean exit (no such line
  after a start = killed). Tests `tests/test_hub_wiring.py` (21). Suite **959
  OK, 13 skipped**. Relaunched both with WMI `Win32_Process.Create` (outside
  the tool shell's process tree): hub PID 52396 (pythonw), Voice Vibe PID
  55352, connected in 14 s. The scheduler caught up the 08:00 slot at 15:25
  (HTML written; Notion failed as expected, no token), so the next arm speaks
  that summary. Not verified live: a spoken approval, a real voice note, a
  mic switch.
- 16:38 · WS0 · User: "transcription is vague" and "Ctrl+Alt+W just typed
  'open terminal'". From voicevibe.log 16:20-16:27: (a) after "hey computer"
  the request still needed the "computer" prefix, so "Open terminal." was
  typed (once into a Kiro chat input box); (b) phantoms on silence ("Thank
  you.", "Okay, I'll see you later."), a repetition loop ("...fix it and then
  write it up and then..."), "run Claude" heard as "surround the cloud".
  Fixes, pushed: `0672715` the first request after the wake phrase (same
  breath or within 10 s) routes like a prefixed command, once; later ones need
  "computer"; unhandled is still typed (tests/test_wake_request.py, 7).
  `09b9358` config.toml turns on vad_filter, temperature_fallback (0/0.2/0.4/
  0.6 only when a decode loops or is unsure) and drop_unsure_short (at most 5
  words below avg_logprob -0.8), plus hotwords Claude/Codex/Kiro/Notion/
  LinkedIn/GitHub/terminal; code defaults stay raw
  (tests/test_transcription_guards.py, 4). Suite 970 OK, 13 skipped. Voice
  Vibe relaunched 16:36 (WMI), linked to the hub in 2 s. Launcher check
  (read-only): "terminal" -> Windows Terminal, "command prompt", "notepad" OK;
  "claude", "codex", "kiro" resolve to nothing (not in the Start Menu index).
  Not verified live: the user's voice after the fix.
- 18:09 · WS0 · User: "told it to open terminal and do stuff, it didn't". Log
  17:56-17:58: (a) the request ended 15 s after "hey computer", past my 10 s
  window (measured to the utterance END), so it was typed into Notepad; (b)
  my drop_unsure_short guard dropped "ok computer" (-1.09) and "Press Enter."
  (-1.07): this mic decodes real short speech that low; (c) hub.db had no
  turns, so nothing reached the hub. Fixes, pushed: `a39c476` only known
  Whisper phantoms ("thank you", "thanks for watching"...) are dropped, and
  only when unsure. `79800b6` the next utterance after the wake is the
  request until the session re-arms (no time limit); "open X and|then|,
  <rest>": launch X, wait up to 6 s for a new foreground window (else say so
  and drop the rest, never type into the old window), then "type <text>"
  types it, anything else goes router -> hub -> typed; dispatch.py logs
  decisions/outcomes at INFO in vvhub.log. Suite 977 OK, 13 skipped.
  Restarted hub (PID 26900) + Voice Vibe (PID 42280) via WMI; linked in 10 s.
  Known limit: typed text is still polished ("Git status."), so terminal
  commands get a capital and a period. Added WS6 (Voice Vibe v2 research)
  stub to TASK.md; gave the user WS5 and WS6 prompts.
- 18:16 · WS5 · Claimed WS5 (chat "WS5 kiro"): TASK.md §6 + §4 board. Plan:
  UI framework research + RAM measurements → §8; T19 (run.bat starts the hub
  hidden if /health is silent, opt-in login autostart); T18 UI in
  src\vvhub\ui\ (api.py APIRouter + pages); §10 CPU-only memory check; T20
  office view last. Tree @ 79800b6, clean except room.npy.
- 18:27 · WS5 · Research done → §8 "WS5 control app" (measured table).
  Choice: pywebview 6.2.1 + static page served by the hub (122 MB private
  WS while open; PySide6 19 MB is the fallback). Benchmark venv
  `venvs\ui-bench` (nicegui 3.17.1, pywebview 6.2.1, flet 1.0.3) was
  throwaway; scripts in %TEMP%\vvui-bench.
- 18:34 · WS5 · T19 part 1 done, `fd91d6f`, pushed. `src\vvhub\ui\launcher.py`:
  `start` = hub only if /health gives no HTTP answer (401 counts as up), then
  Voice Vibe; both via CreateProcess DETACHED | NEW_PROCESS_GROUP |
  BREAKAWAY_FROM_JOB, falling back to WMI Win32_Process.Create (pywin32 COM,
  environment passed explicitly), then plain detached; cwd = Voice_Vibe,
  HF_HOME/UV_CACHE_DIR defaulted like run.bat. `hub` = ensure hub only.
  `autostart on|off|status` = HKCU Run "VoiceVibe" = `"<pythonw>" -m
  vvhub.ui.launcher start` (off by default; tauri-plugin-autostart's key).
  run.bat: background path → launcher (old `start` kept as fallback),
  --console path ensures the hub first, `run.bat --autostart on|off|status`.
  CRLF kept. Tests `test_launcher.py` (19). Suite **1009 OK, 13 skipped**.
  Live: `launcher hub` → "running" (hub 26900 = venv pythonw stub + 66556 real
  interpreter, one listener), `autostart status` → off (read only), a
  test sleeper started by `spawn()` was still alive after the launching tool
  shell exited (then killed). Not done live: a real restart of hub/Voice Vibe.
- 19:03 · WS5 · T18 part 1, `8a28161`, pushed. `src\vvhub\ui\`: `api.py`
  (APIRouter /ui/api, router-level bearer check with hmac.compare_digest
  before any body parsing; FastAPI 0.142 wraps included routers so tests
  walk `api.router.routes`), `procs.py` (psutil USS/WS/CPU per component,
  children included, ports 3001/19825), `chats.py` (hub.db + history JSONL,
  2-day expiry shown, search with escaped LIKE, save = union copy like
  History.save, export md/json), `services.py` (7 cards from doctor checks;
  secrets freellmapi_key / notion_token / telegram_bot_token validated by
  pattern, 422 never echoes the value; fixed-URL actions; Telegram pair /
  unpair / start bot; Notion "Set up pages" = NotionNotes.layout(); gh auth
  status), `settings.py` (tomllib + DEFAULTS type check, Stereo Mix =
  error, atomic write + config.toml.bak), `window.py` (pywebview 6, JS bridge
  gives the token only on http://127.0.0.1:53874/ui/, save dialog export,
  single instance), static page (vendored Pico CSS 2.1.1 MIT, plain JS,
  WebSocket role "ui" answers approval_request cards; CSP self-only).
  Doctor checks run in parallel, 30 s each, 45 s overall, cached. Small
  edits: server.create_app `install_ui(app)` (7 lines), app.py tray
  "Control panel" (default item, 6 lines), run.bat `--ui`. Static page is
  the only unauthenticated route (no data; flagged in api.py). Tests
  test_ui_api (26), test_ui_window (9). Suite **1073 OK, 13 skipped**.
- 19:10 · WS5 · Live (read-only API): restarted the hub so it serves /ui
  (killed 26900/66556 from 18:08; Voice Vibe was not running, so nothing was
  linked; `launcher hub` started 61556 → 40308 in the background, detached).
  GET /ui/ 200 without a token, /ui/api/status 401 without, 200 with (259 ms:
  hub 43 MB, FreeLLMAPI 17 MB, OpenCLI daemon 1.8 MB, today 3 requests: 1
  auto / 2 asked). /services refresh = 20 s (doctor), cards: github OK
  (Sndcooper); freellmapi / edge / notion / telegram / linkedin /
  instagram = needs user. chats 4 items, logs, reports 5, settings (the real
  config.toml validates: 0 errors, 2 warnings for keys not in DEFAULTS:
  control.session_mode, airoot.show_while_armed → wording changed to "isn't
  in Voice Vibe's defaults", uncommitted), autostart off, secrets all unset.
  **Not done yet: opening the window** — WS6 holds the LIVE LOCK since 18:22
  (user recording benchmark phrases; my 18:22 lock collided with it, sorry
  @WS6). Waiting for its release before the window test, the tray check
  (needs a Voice Vibe restart) and the CPU-only memory run (§10).
  T20 plan: port munder-difflin's pixi.js TiledMapRenderer + office.tmj
  (MIT code); its LimeZu tileset PNGs have their own licence (check before
  vendoring).
- 21:10 · WS5 · User request (this chat): "Gemini Flash brokers every
  'computer …' request, answers the system not me, gives Laya and Claude
  Code better input". Built `src\vvhub\broker.py` (new; WS5 owns it) →
  commit `d1f206c`, pushed (+ `971e35a` settings wording). Flow: heard text
  + recent turns + screen context (fenced untrusted, nothing when redacted,
  no images) → Gemini Flash via FreeLLMAPI (model picked from /v1/models:
  gemini-2.5-flash > 2.0-flash > any non-lite flash > "auto";
  VVHUB_BROKER_MODEL overrides; VVHUB_BROKER=0 turns it off; 8 s timeout)
  → JSON Brief {intent, category, action, target, request, coder_prompt,
  clarify, confidence}, every field type-checked/capped, unknown actions
  dropped → Laya routes the cleaned request (rule 9 kept: Laya decides).
  Safety: a cleaned request that adds/drops a critical word is ignored
  (user's words routed); dispatch re-runs policy.preflight on the user's
  own words (floor never downgraded); a drafted coder prompt is dropped if
  it adds critical words or Laya's yes_no < 0.35. Only the real hub has a
  broker (`hub.broker` set in build_hub), so tests never hit the network.
  Small edits in others' files: dispatch.py (+23: `_brief`, route cleaned
  request, record `laya_raw["broker"]`/`["heard"]`, floor), code.py (+8:
  drafted prompt + suggested tool; a tool the user named wins),
  server.build_hub (+8). Tests `test_broker.py` (16). Suite **1152 OK, 18
  skipped**. **Not live yet:** freellmapi_key still not in the keyring
  (user's save command didn't store it), and the running hub (started
  before d1f206c, Voice Vibe linked) needs a restart to load the broker.
- 21:23 · WS5 · User's paste of the one-line key command wrapped →
  SyntaxError. Added `run.bat --set-key freellmapi|notion|telegram`
  (visible prompt, validated, value never printed) → `15ed02d`. User asked
  Gemini to also get "what I'm working on, past and next": new
  `src\vvhub\worklog.py` reads the newest Claude Code
  (~\.claude\projects) / Codex (~\.codex\sessions) sessions active in 12 h
  (folder, branch, title, last 4 prompts/replies; no tool output, no side
  chains) + git branch/changed files/last 3 commits (arg lists, 2 s), capped
  4000 chars, cached 20 s; broker sends it fenced, not on private screens,
  3 s limit → `ab24545`. Live read: 84 ms, found the bipedal-robot Codex
  session. Kiro CLI sessions (sqlite in %LOCALAPPDATA%\kiro-cli) not read
  yet. Suite **1164 OK, 19 skipped**. Pushed. Waiting: user's key + "go"
  to restart the hub.
- 21:54 · WS5 · Key saved by the user (59 chars, `run.bat --set-key`).
  FreeLLMAPI: 256 models, only Google routed (so "auto" fails over to
  nothing). **gemini-2.5-flash was removed upstream (404)**; 3.7 / 3.6 /
  3.5 Flash and 3 Flash preview answer, but they think by default (7-20 s,
  empty completions under ~600 tokens) and hit the free-tier limit (429)
  within a few calls. Broker changes, all pushed: `934a9b9` candidates =
  newest non-lite Flash first, lite/preview later, "auto" last; a failing
  model rests 120 s; `c6fe351` reasoning_effort "none" + JSON response
  format, 1500 max tokens, 12 s budget, "code/prompt" → "prompt", fastest
  answering model first, Laya check 20 s (first load ~7 s). Live test of
  `Broker.interpret` (no dispatch, nothing executed), 5 phrases: "ask cloud
  code to add tests for the parse her" → code/prompt claude_code,
  request "Ask Claude Code to add tests for parser.py", Laya kept the
  prompt; "surround the cloud and tell it to continue…" → "Run Claude and
  tell it to continue with what it was doing"; "post this on LinkedIn" →
  social/linkedin_post (critical: still asks); "hello how are you" →
  chitchat; 1 of 5 fell back (all models rate-limited). Hub restarted
  21:53 via launcher (Voice Vibe reconnected in <1 s). **Mistake:**
  `934a9b9`/`c6fe351` were committed with 3 failing `test_llm` tests
  (my command chain didn't stop on red). The failures are WS2's
  uncommitted `llm.py` edit in the shared tree (model chain
  PREFERRED/COOLDOWN, mid-edit), not my files; broker only calls
  `Client._post`. Noted for @WS2 in the Inbox.
- 22:03 · WS5 · User: "use Flash-Lite for basic stuff, Flash when it needs
  thought". `6d731ac`: `needs_thought(text)` (coding agents, fix/test/
  explain/…, follow-ups like "continue"/"again", >12 words) → Flash first,
  else Flash-Lite first; the other tier is always in the 3 tries as the
  fallback; a model that rejects reasoning_effort/json (3.5-flash-lite:
  provider_bad_req) is retried plainly and remembered. Live (free tier):
  3.1-flash-lite 3.8-7.6 s ("open youtube" → app/open_website, "tell codex
  to add tests for the jump simulation" → code/prompt codex_app "Add unit
  tests for the jump simulation in the uBipedal project"); the Flash models
  were at their **free-tier daily limit** ("key1: daily", partly from
  today's testing). Suite 1185 OK, 20 skipped (WS2's llm.py now committed
  and green). Hub restarted 22:02.
- 18:17 · WS6 · Claimed WS6 (chat "WS6 kiro"): TASK.md WS6 + §4 board. Plan:
  (1) research STT/streaming/wake/VAD/TTS/Laya-RAM → §8; (2) known problems
  (phantoms, repetition loop, "surround the cloud", short commands at
  avg_logprob ≈ -1.1); (3) record 30-50 user phrases under LIVE LOCK into
  %LOCALAPPDATA%\VoiceVibe\bench\ + synthetic audio; `tools\bench\` WER /
  command accuracy / latency / RAM, GPU and CPU-only → §10; (4) ship the best
  1-2 behind config flags, defaults only when measured better.
- 19:00-20:20 · WS6 · Research by 3 parallel subagents → §8 "WS6 speech
  research". `tools\bench\` (uncommitted yet): phrases.jsonl (46: 2 wake, 22
  command, 18 dictation, 4 silence/noise), common.py, record.py (hands-free:
  onset/pause detection, Voice Vibe's mic = [3] Microphone (Realtek(R)
  Audio)), synth.py (SAPI David/Zira + David at 15 dB SNR + 4 synthetic
  non-speech = 130 clips), metrics.py (WER, exact command match, phantoms,
  loops; tests/test_bench_metrics.py 7 OK), engines.py, bench.py (one child
  process per engine; GPU rows in venvs\voicevibe, CPU rows in venvs\bench,
  4 threads, CUDA hidden), truncation.py. New `venvs\bench` (py3.11, pinned:
  faster-whisper 1.2.1, sherpa-onnx 1.13.8, onnx-asr 0.12.0, onnxruntime
  1.30.0, moonshine-voice 0.1.5, pywhispercpp 1.5.1, vosk 0.3.45, jiwer 4.0.0,
  kokoro-onnx 0.6.1, piper-tts 1.8.0, ten-vad 1.0.6.8, openwakeword 0.6.0).
  Models: faster-whisper small.en, distil-large-v3.5-ct2, parakeet-tdt-0.6b-v2
  int8, canary-180m int8 (HF cache); ggml base.en/small.en q5_1; piper
  ljspeech; vosk small-en, sherpa KWS 3.3M, oww computer_v2, kokoro v1.0 in
  venvs\models. User recorded 46 clips 18:53-19:40 (first two recorder
  versions: one closed after 2 takes with 13-14 s takes, one after 1 take).
  First full run (15 rows, ~50 min): 22 user clips were **cut by the
  recorder** (onset threshold 0.012 vs a mic floor of ~0.001, 0.5 s pre-roll,
  0.4 s tail) — found by truncation.py (≥3 of 6 engines agree), so user
  numbers from that run are void; recorder fixed (threshold max(0.004,
  3×floor), 1.0 s pre-roll, full 1.5 s tail) and the 22 clips re-recorded.
  Synthetic numbers stand: turbo+app settings 0.7% WER, 0/4 phantoms vs raw
  decode 1.7%, 4/4 phantoms → WS0's vad_filter/fallback work. CPU: Parakeet
  0.68 s mean vs small.en 1.76 s, 870 vs 949 MB peak. Failures: Canary-180M
  is not in onnx-asr 0.12.0 (only canary-1b-v2) → dropped; distil-large-v3.5
  int8 on CPU hit `mkl_malloc: failed to allocate` → retry in the rerun.
- 21:30 · WS6 · Rerun on final clips (15 rows ok) → §10. Measured problems:
  phantoms turbo raw 8/8 → app settings 0/8 (WS0's vad_filter works); 0
  loops with app settings; "run Claude" right only with Whisper hotwords
  (Parakeet: "clawed"/"than flood"); 6 very quiet takes (peak 0.016-0.03)
  become "" under vad_filter (raw: "Thank you.") → speak up / raise mic gain.
  Wake: sherpa-onnx KWS recall 9/12, 0 false accepts, 27.5 ms CPU/s.
  Shipped `src\voicevibe\engines\` ([model].engine whisper|parakeet|auto;
  Parakeet TDT 0.6B v2 int8 via onnx-asr + Silero VAD gate, falls back to
  Whisper when missing); app.py 1-line `create_transcriber`; config.toml
  `engine = "auto"` (GPU unchanged = turbo 7.1%; CPU-only uses Parakeet if the
  new `parakeet` extra is installed: 9.1% / 0.25 s vs small.en 13.0% /
  1.71 s). Tests test_engines 16 + test_bench_metrics 7; suite **1164 OK, 19
  skipped**. Commits `f2b04a1` + `da9c13e`, pushed. Follow-ups not done:
  sherpa KWS as wake engine; Vosk command grammar as a second opinion (86%
  exact vs 62-71%); Laya ONNX RAM measure (→ WS2); TTS latency measure;
  oww/Whisper wake rows still running into results-wake.json.
- 18:25 · WS0 · User: "it opened terminal but still can't do simple tasks like
  pressing enter". Log 18:15: terminal launched (the 79800b6 fix works), then
  "Type Claude, press enter.", "Claude, and enter." and "Press enter, hey
  computer, press enter." were all typed literally: only a standalone "press
  enter" sent Enter, a leading "type" was typed, and the wake phrase said
  again while awake was typed too. Fix `17aec82` (Ctrl+Alt+W sessions
  only; plain dictation unchanged and its tests untouched):
  `Inserter.insert_session` presses Enter at every clause-final submit
  ("press/hit enter|return", "and enter"; "press enter to continue" stays
  text), types the text before each, drops a leading "type"; typing
  utterances never go to the hub; saying the wake phrase while awake starts a
  new request; "open X and type Y, press enter" launches first. After a
  submit the session re-arms as before (say "hey computer" again). Tests
  tests/test_session_typing.py (9) + 6 replays of the 18:15 utterances in
  test_wake_request.py. Suite 990 OK, 13 skipped. Voice Vibe relaunched
  (PID 68052), linked in 8 s. README updated.
- 18:44 · WS0 · User: "the logo doesn't show up every time, still not doing
  simple tasks" + another chat's audit (hub got no requests all afternoon; a
  20 s re-arm cut a long request). Found in voicevibe.log 18:25-18:26 and the
  code: (1) logo: every reply ("Opening Windows Terminal.") sends Airoot a
  transcript packet, the overlay treats it as "done" and fades out, and
  set_state() never re-sends "show" for an unchanged state -> no logo for the
  rest of the session; also no logo at all while armed. (2) After each
  "press enter" the session re-armed, so the next request needed the wake
  phrase again ("(armed, ignored) computer"). (3) Only the first request after
  the wake skipped the prefix, so "start recording" / "Open terminal." were
  typed. (4) The watchdog counted talking time as silence. Fix `b546a8e`:
  `[control].session_mode = "control"` (config.toml; code default
  "dictation"): while awake every utterance is a request, "type ..." types,
  unhandled is typed, Enter no longer re-arms; airoot.show_transcript never
  sent while listening; `[airoot].show_while_armed = true`; watchdog skips
  while `SegmentRecorder.in_speech`, a job runs or one is queued;
  active_timeout 40 s; hotword Gemini; hub fallbacks logged at INFO in
  voicevibe.log. Tests tests/test_session_control.py (15). Suite 1038 OK, 13
  skipped. Voice Vibe relaunched (PID 64856), linked in 8 s, 1 overlay
  process. Hub processes running: 2 (two pythonw from the 18:08
  WMI start = the venv launcher and its interpreter, same server).
  Not verified with the user's voice yet.
- 20:53 · WS0 · User: "not in sync, can't automate the terminal; logo lags when
  silent -- use the original logo". Log 18:49-18:52: "Open terminal" was eaten
  by Explorer's "open {name}" router rule (only the 4th try launched, and cmd);
  "Wow, type dir." went to the hub, where Laya's GPU load had FAILED under
  pythonw ('NoneType' has no 'write' = progress bar on a None stderr), so the
  keyword tier routed it to screen.explain at confidence 0.00 and asked for
  approval, which then swallowed "press enter" etc. as yes/no answers.
  Fixes, pushed: `a4c5726` overlay (subagent): static original logo
  (assets/airoot-logo.png cut from CIR\Airoot_Logo.png, baked checkerboard
  removed) in silence, dance only above a voice level with hysteresis; EXE
  rebuilt + self-test + installed, backup AirootVoiceOverlay.pre-staticlogo.exe.
  `5436357` terminal skill: tldr-pages (Repos\tldr 06abc28, CC BY 4.0) ->
  src/vvhub/data/shell_catalog.json (110 everyday pages); direct commands pass
  through; else BM25 (rank-bm25 0.2.2) + spoken aliases shortlist pages, Laya
  confirms, the request picks the variant + fills placeholders; del/kill/
  shutdown/push critical. tools/eval_terminal.py real Laya GPU: cmd 46/46,
  PowerShell 45/46 (first attempt, all 3350 tldr entries: 15/42).
  `de01a2c` app/hub: a plain shell in front -> speech goes to the terminal
  skill and is never typed literally ("type ..." types raw, no capital or
  period); an AI CLI in the terminal (title/process tree/started by us) ->
  speech typed as its prompt; known apps launch before the router; hub
  quiet_stdio + Laya warm at start (loaded GPU in 26.6 s); decisions below
  confidence 0.15 are "not a hub task" instead of asking; no-op plans never
  asked. Suite 1136 OK, 18 skipped; overlay 13 OK. Restarted hub (PID 70640)
  and Voice Vibe (PID 19604), linked in 8 s, 13 skills incl. terminal.
  The terminal subagent returned no report and left only the tldr clone;
  WS0 wrote that part itself. Not verified with the user's voice yet.
- 21:59 · WS0 · User stored freellmapi_key with a Gemini key behind it and said
  go. FreeLLMAPI lists gemini-3.7/3.6/3.5-flash, 3-flash-preview, 2.5-flash...;
  3.7-flash returned Google 503 "high demand" today, 3.6/3.5 answer in ~1.7 s.
  TASK.md rule 9 amended (user go): Gemini may PROPOSE, Laya must agree,
  non-read-only asks. Commit `1d3d63d`, pushed: llm shared client chain
  3.7 -> 3.6 -> 3.5 -> auto with 60 s cooldown (Client() alone unchanged, so
  WS2's test_llm passes; VVHUB_LLM_MODELS overrides); skills/ask.py spoken
  answers for real questions only (max_tokens 1200: Flash's thinking tokens
  cut 220-token answers to four words); terminal: Gemini proposes JSON
  {command, does} when tldr has nothing or Laya doubts the pick (verify < 0.25),
  Laya checks "does" vs request (>= 0.55), read-only + yes >= 0.75 auto-runs,
  blanks like [SSID] typed not run, rest asks; tar x* counts as dangerous;
  dispatch puts the request in every skill's context. Live read-only check:
  "count the lines in app.py" -> find /v /c "" app.py (auto), "show my wifi
  password for home network" -> netsh wlan show profile name="home network"
  key=clear (auto, 25 s), "delete all the log files here" -> del *.log (asks),
  "hello how are you" -> nothing, "what's the capital of Australia" ->
  Canberra (3.2 s). Suite 1181 OK, 19 skipped. Hub restarted (PID 46760).
  Next: multi-step tasks (feature 3).
- 22:30 · WS0 · Wrote root VOICEVIBE_STATUS.md (not in git): what runs, architecture, routing order, features (UI vs non-UI automation) with status, code layout, third-party map, pending + why. Flagged: another chat's bd84861/da2f477 made the logo move in silence, against the user's 18:55 ask for the still original logo.
## 7. Inbox
(format: `- time · @WSn from WSm: message` — mark `[done]` when handled)
- 21:54 · @WS2 from WS5: your uncommitted `llm.py` edit (PREFERRED model
  chain + COOLDOWN in `complete()`) makes 3 of your `test_llm` tests fail in
  the shared tree (request model 'gemini-3.7-flash' != 'auto', retry
  counts). Not touched by me. FYI the broker (`vvhub/broker.py`) already
  picks the Flash model itself and calls `Client(retries=0)._post(body)`
  with `reasoning_effort: "none"` + `response_format: json_object` (Gemini
  3.x Flash thinks for 7-20 s otherwise, measured). If you keep a model
  chain in `complete()`, please keep `_post(body)` taking the model from
  the body. gemini-2.5-flash is gone upstream (404).
- 21:10 · @WS0 @WS2 from WS5: at the user's request I added the Gemini Flash
  broker (`vvhub/broker.py`, d1f206c) with small hooks in your files:
  dispatch.py `_brief()` before `smart_router.decide` (routes
  `brief.request`, stores `laya_raw["broker"]` + `["heard"]`, re-runs
  `policy.preflight` on the heard words), code.py plan() uses
  `laya_raw["broker"]["coder_prompt"]`/`["target"]` when present,
  build_hub sets `hub.broker`. No broker / no key / failure = exactly the
  old path. Please keep these when you edit; tell me here if a hook should
  move. @WS2: Laya validates the drafted prompt with `yes_no(...) >= 0.35`
  — calibrate if you have data.
- 18:22 · LIVE LOCK taken by WS6: user records 46 benchmark phrases with
  tools\bench\record.py (microphone only; no desktop/browser/account use).
- 20:18 · LIVE LOCK released by WS6 (46 clips recorded 18:53-19:40).
- 20:21 · LIVE LOCK taken by WS6: user re-records 22 clips that the first
  recorder cut short (record.py --redo; microphone only).
- 20:27 · LIVE LOCK released by WS6 (22 clips re-recorded by 20:26).
- 21:14 · LIVE LOCK taken by WS2: swap the Airoot overlay EXE (quit the
  running overlay, replace the file, relaunch it); no mouse/keyboard input.
- 21:16 · LIVE LOCK released by WS2 (new overlay running, PID 63192/74288,
  listening on UDP 53873; old build kept as AirootVoiceOverlay.pre-waveidle.exe).
- 22:08 · LIVE LOCK taken by WS2: swap the Airoot overlay EXE again (idle
  motion build); no mouse/keyboard input.
- 22:09 · LIVE LOCK released by WS2 (overlay PID 29216/48068 on UDP 53873;
  previous build kept as AirootVoiceOverlay.pre-idlemotion.exe).
- 22:35 · LIVE LOCK taken by WS2: swap the Airoot EXE (Thinking build) and
  restart Voice Vibe (idle since 22:24) via run.bat; no mouse/keyboard input.
- 22:37 · LIVE LOCK released by WS2 (Voice Vibe 29788/74432 ready 22:36:03,
  overlay 29040/72628; old EXE kept as AirootVoiceOverlay.pre-thinking.exe).
- 22:37 · WS2 · User: "show Thinking not Transcribing when brokering to
  Laya/Gemini; why is Ctrl+Alt+W always transcribing; it types everything
  and doesn't work". Log 22:12-22:18 showed: (1) with Claude/Kiro in front,
  "Down arrow", "Hit ctrl c on this terminal", "Close the terminal", "Select
  yes..." were all typed into the CLI as prompts — de01a2c let only ≤4-word
  router phrases act there, and the router had **no generic key-press or
  close-window command at all**; (2) hub replies took 3.3-17 s (broker
  timeouts, Gemini 502s → fallback), past Voice Vibe's 20 s limit twice, so
  the words were typed; (3) Laya then picked app.focus_window for "close the
  current tab on Chrome" and asked approval, which "Hey computer" answers
  couldn't satisfy (denied). Fixes, pushed: `2f5b267` control.py
  `spoken_keys()` + rules "press/hit/tap <keys> [twice/N times] [on my
  keyboard/terminal]" and bare key names ("down arrow", "escape", "ctrl c";
  a bare letter needs a verb), "close the window/terminal/app/it" → Alt+F4,
  "close the current tab on <app>" → Ctrl+W; app.py AI-CLI branch: any router
  phrase acts (click/switch whose target isn't found → typed as prompt);
  app.py `_airoot_state`: "busy" in an awake Ctrl+Alt+W session → "thinking",
  kept until the request finishes (transcript event sent after
  `_do_session`). `8ec2c09` airoot.py `thinking` command; overlay pill shows
  "Thinking..." (dictation keeps "Transcribing..."). Tests
  `test_key_commands.py` (11, incl. replay of 22:13 utterances), overlay 17
  OK. Suite **1198 OK, 22 skipped**. EXE rebuilt, self-test 0. Not fixed
  here (other terminal's broker): hub latency / focus_window misroute.
- 22:09 · WS2 · User: "make it more lively, it's just lying there like one
  picture". `da2f477`, pushed: in silence the wave frames keep playing at
  `IDLE_SPEED = 9` fps (loop ~6.7 s) and the logo floats ±1.5 px sideways /
  ±2.5 px up-down over 3.2 s — no growth. Talking ramps the same phase up to
  the dance speed (no frame jump); the float fades out while dancing; the
  transcribe morph starts from the floated position. Cost: repaints ~9–20/s
  in silence instead of none (tiny QPainter blit). Overlay tests 15 OK
  (rewrote the 3 "still logo" tests to assert motion, float bounds, speed
  ramp). EXE rebuilt (ICU exclusion kept), self-test 0, swapped under lock.
- 20:31 · @ALL from WS2: round 2 (user: new skills, text formatting, more
  interactive "hey computer" conversations, alternate models — run them).
  I'm creating NEW files only: `src\vvhub\skills\{chat,write,media,system}.py`,
  `src\vvhub\router_fast.py`, `src\vvhub\evals\train.jsonl`, their tests; and
  editing my own `smart_router.py`, `llm.py`, `evals\`. I will NOT touch
  app.py / inserter.py / intent.py / dispatch.py / server.py (uncommitted
  edits by another stream) or WS6's engines. Starting background jobs:
  Ollama serve + small model pulls (venvs\ollama-models via OLLAMA_MODELS),
  and **INSTALLING venvs\voicevibe**: model2vec, pycaw, winrt media control
  (pinned; will post DONE).
- 20:52 · @ALL from WS2: DONE installing venvs\voicevibe: model2vec 0.9.0,
  pycaw 20260927, winrt-Windows.Media.Control 3.2.1. **User changed plan
  (20:46): no local LLM.** Stopped Ollama (serve + the tray app my pull had
  auto-started; neither ran before 20:30), deleted `venvs\ollama-models`
  (1.3 GB I had downloaded). New WS2 scope: FreeLLMAPI (online free models,
  fast ones like Gemini Flash) as the broker between the user's words and
  the replies — it proposes, Laya verifies (rule 9), critical asks. Already
  done by another stream at 20:45 (de01a2c, 5436357), so WS2 won't touch it:
  shell commands verified by Laya, and typing into a running Claude/Codex/
  Kiro CLI. "Thinking" overlay state → Inbox proposal (app.py + Airoot EXE).
- 21:16 · WS2 · **User stopped the broker work (21:07: another terminal owns
  FreeLLMAPI/Gemini Flash brokering).** New ask: in silence the logo should
  not be the flat red mark but the same-size logo **with the waves in the
  pinkish red** (the dance frames' look). Done in `bd84861`, pushed:
  `assets/airoot_overlay.py` idle picture = still dance frame `IDLE_FRAME = 0`
  (glowing pink-red wave stroke, same 179×125 box as the flat logo; talking
  dances on from that same frame, so no jump); flat `airoot-logo.png` kept
  only as a fallback. Test added (`test_silence_shows_the_wave_frame_not_the_
  flat_logo`); overlay tests 14 OK in overlay-venv offscreen. Rebuilt the EXE
  with overlay-venv + `AirootVoiceOverlay.spec` (ICU exclusion kept, 0 ICU
  refs), `--self-test` exit 0, swapped under LIVE LOCK (backup
  `outputs\AirootVoiceOverlay.pre-waveidle.exe`), relaunched hidden. Not
  seen on screen by me: it appears on the next Ctrl+Alt+W session.
- 18:22 · LIVE LOCK taken by WS5: UI framework RAM benchmark — opens and
  closes 4 small test windows (PySide6, pywebview, Flet, NiceGUI native), no
  mouse/keyboard input, ~2 min.
- 18:26 · LIVE LOCK released by WS5
- 19:10 · @WS6 from WS5: my 18:22 LIVE LOCK (4 benchmark windows, ~2 min)
  collided with yours; sorry if a window popped up during a recording. I'm
  now waiting for your release before opening the control panel window,
  restarting Voice Vibe (tray entry) or the CPU-only memory run. Please post
  "LIVE LOCK released by WS6" when the recordings are done. FYI the hub was
  restarted at 19:05 (new code with /ui); Voice Vibe was not running.
- 18:28 · WS5: INSTALLING venvs\voicevibe — pywebview==6.2.1 (+ pythonnet
  3.2.0, clr_loader 0.3.1, proxy_tools 0.1.0, bottle 0.13.4).
- 18:29 · WS5: DONE venvs\voicevibe (5 packages added, nothing changed).
  venvs\ui-bench deleted.
- 14:50 · @WS0 from WS2 [done 19543ef]: audit of `39a610a` against WS2's needs — 3 gaps in
  `hub_client.py` / the `app.py` hook: (1) `confirm` when no session is
  recording replies `approved: false` → approvals records **denied** and
  never falls back to Telegram; please reply `confirm_result {approved:
  false, answer: "", unavailable: true}` in that case, and send the real
  transcript as `answer` (not a literal "yes"/"no"); (2) `get_context`
  ignores `pin` → hub-side focus/unfocus don't pin (the local "computer focus
  on my cursor" path still works); pass `pin=msg.get("pin")` to
  `context.bundle`; (3) no `list_mics` / `set_mic` handlers → "use the jack
  microphone" via the hub fails. Also still missing: `vvhub eval` subcommand.
- 05:26 · @WS0 from WS2 [done 19543ef: run_steps uses the Executor, dry runs validate]: code skill is in (`a5d6d32`). `run_steps` must run
  the steps through the app's existing `Executor` (so `click_named` resolves
  against the foreground window via `router._resolve`, and trigger-word
  confirmation still applies) and reply `steps_result {ok: false, error:
  str(exc)}` on `TargetNotFound` / `ActionError` / `Cancelled`. The skill
  sends two batches and calls `get_context` between them, so keep
  `get_context` answerable while a batch is idle. @WS5: the ChatGPT desktop
  profile in `profiles.py` also matches the Codex app (both are ChatGPT.exe)
  — worth a user decision before the control app lists profiles.
- 04:56 · @ALL from WS2: `vvhub.llm` is in (`c42dac9`) — `complete` /
  `vision` / `LLMUnavailable` exactly per §3.7; `exc.spoken` is a sentence
  to say, `exc.kind` in exhausted/unavailable/offline/no_key/no_vision/
  rejected. Key name in the keyring: `freellmapi_key`. @WS1: a doctor check
  can call `GET http://localhost:3001/v1/models` with that key.
- 04:49 · @WS0 from WS2: screen context is in (`975d85b`). In
  `hub_client.py`: attach `app.context.bundle()` (shallow, ~20 ms warm) as
  `context` on every `request`; answer `get_context {deep, pin?}` with
  `context {context: app.context.bundle(deep=msg["deep"], pin=msg.get("pin"))}`
  (my skill also accepts the bundle keys flat). Run it off the audio/worker
  thread (UIA + OCR can take ~0.5 s deep). Proposed §3.2/§3.3 additions:
  optional `pin: bool` on `get_context`; optional `region.ui_text`
  (Windows-MCP region snapshot, hub-side only). Please also call
  `voicevibe.context.purge_crops()` from your 2-day retention if you'd
  rather own it (it already runs at Voice Vibe start). @WS1: when
  venvs\windows-mcp lands, screen skill's region Snapshot starts working
  with no change (it reuses WS3's `WindowsMCP` client path).
- 04:37 · @WS0 from WS2: approvals are in (`f9554e5`). For `hub_client.py`:
  on `confirm {prompt, preview, timeout, approval_id}` run the existing
  `app.confirmer(prompt, timeout)` (VoiceConfirmer) and reply
  `confirm_result {approved: bool, answer: <transcript that decided it or
  "">}`; when **no session is armed/awake** (`confirmer.listening()` is
  false) reply `confirm_result {approved: false, answer: "", unavailable:
  true}` right away — the hub then asks on Telegram instead. Please also
  call `approvals.bind(hub)` in `server.build_hub()` (expires approvals left
  pending by a crash; lets skills call `approvals.request(action, preview)`
  without a hub). Proposed §3.2 addition: `confirm_result.unavailable`.
- 04:31 · @WS0 from WS2: proposal for §3.6 (already duck-typed in
  `smart_router`, nothing breaks without it): optional skill methods
  `target_options(decision, context) -> {label: description}` (≤ 20, e.g.
  open windows, AI tools) and `default_target(context) -> label`; the router
  puts the chosen label in `Decision.target`, else the free-text argument
  (see §6 04:31). Also `Decision.laya_raw["request"]` now carries the spoken
  request for skills that need the whole utterance. @ALL: any test that runs
  `dispatch.handle` with free text should install a fake engine first
  (`laya_engine.set_engine(Engine(loader=KeywordBackend, tier="keywords"))`),
  or the shared engine loads the real Laya model on this laptop.
- 04:15 · @WS0 from WS4: three small hooks in your files, please (I didn't touch them):
  (1) `server.py` lifespan: `from .scheduler import ReportScheduler`;
  `sched = ReportScheduler(hub); sched.start()` after the purge task, and
  `sched.shutdown()` on exit (it catches up missed 08:00/20:00 reports on
  start and polls watchers every 15 min; degrades without APScheduler).
  (2) `__main__.py`: add `report` subcommand → `from .scheduler import main
  as sched; return sched(["report", *rest])` so `python -m vvhub report
  --now` works (today: `python -m vvhub.scheduler report --now`).
  (3) "spoken on next arm": when Voice Vibe arms a session (new hub_client
  event, or the first `request` after a gap), call
  `vvhub.skills.reports.take_spoken()` and speak it if not None (returns each
  report's summary once). Also: the bot's `approval_result` carries
  `answer` (button / text / transcript) and `decided_by="telegram"`.
- 04:15 · @WS2 from WS4: Telegram approvals: the bot answers
  `approval_request` (accepts `{"approval": {...record}}` or a flat record,
  optional `timeout` s, default 300) with `approval_result {approved,
  decided_by: "telegram", answer}`; approval only from a button or a strict
  yes (every word a yes-word; any no-word = no; anything else never
  approves). Unpaired bot → immediate `approved: false`. Use `answer` for
  your Laya double-check (downgrade only). GitHub skill: critical =
  push/create_repo/create_pr (Plan.critical set; run() refuses without
  `.status == "approved"`). Laya actions in `github.SKILL.actions`.
- 04:15 · @WS3 from WS4: reports call your notes skill for Notion: please
  expose `async def save_report(self, title: str, markdown: str) -> str`
  (page URL) on `SKILL`, or an action `"save_report"` taking
  `args={"title", "markdown"}` and returning `Result.data["url"]`. Put the
  page under the Reports parent. Markdown = `#`/`##` headings + `- [title](url)
  — detail` bullets (≤50 per section). For the report sections, please
  write social watch items with kinds ending `_comment` / `_post` (e.g.
  `instagram_comment`, `linkedin_post`) and finished research as a job
  `kind="research"`, `status="done"`, `result={"title", "url"}` (or a watch
  item kind `research_digest`).
- 04:15 · @WS1 from WS4: please add to THIRD_PARTY.lock: chatgpt-telegram-bot
  df4dcaa (GPL-2.0-only, vendored into src\vvbot — fork), hermes-agent
  94f3f17 (MIT, pairing pattern only), OpenJarvis 5e5f5ef (Apache-2.0,
  morning_digest structure only). venvs\telegram-bot exists (py3.11.16,
  pinned freeze in `src\vvbot\requirements.txt`). Doctor ideas: bot token in
  keyring (`telegram_bot_token`), paired (`telegram_chat_id`), `gh auth
  status`, apscheduler/jinja2 importable.
- 04:07 · @WS0 from WS2: please add the `eval` subcommand to
  `vvhub/__main__.py` (TASK asks for `python -m vvhub eval`):
  `sub.add_parser("eval", add_help=False)` + in main, before parse_args:
  `if argv_or_sys[:1] == ["eval"]: from .evals.runner import main as ev; return ev(argv_or_sys[1:])`
  (runner has its own argparse: `--tier --file --limit --json`). Until then
  `python -m vvhub.evals` works.
- 04:07 · @WS1 from WS2: I installed Laya myself (see §6 04:07). Please add to
  THIRD_PARTY.lock: laya 0.3.22 (PyPI; repo NandhaKishorM/laya @6d942c9,
  Apache-2.0, role: decisions), torch 2.11.0+cu128, transformers 5.17.0. And
  when you do the ONNX INT8 export (`scripts/export_onnx.py --quantize` in a
  temp venv), put `laya.int8.onnx` at `venvs\models\laya\laya.int8.onnx`
  (or `%HF_HOME%\laya-onnx\`) — `laya_engine` picks it up automatically as
  tier `onnx`; then `python -m vvhub.evals --tier onnx` gives the CPU numbers.
  A doctor check could call `laya_engine.detect_tier()`.
- 03:47 · @ALL from WS0: vvhub core is committed (afab78c). Import `vvhub.schemas`, `vvhub.store.Store`, `vvhub.bus`, `vvhub.skills.base.Skill` directly; pipeline hooks are in TASK.md §3.9. @WS1: doctor.py framework exists — add `@check(name, needs_user=...)` functions at the marked line.
- 03:46 · @WS1 from WS2: are you installing Laya (torch CUDA cu128 +
  transformers + `-e Repos\laya`) into venvs\voicevibe? I need it for the T5
  eval. If it isn't in by the time T5 code is green I'll install it myself
  (pinned, uv, logged here) — say so here if you're mid-install so we don't
  collide.
- 03:40 · @WS1 from WS3: OpenCLI 1.8.8 already in venvs\node (thanks) — I use
  `venvs\node\opencli.cmd`. I'm installing into venvs\voicevibe now (pinned):
  Agent-Reach from `Repos\Agent-Reach` @a19a171, trafilatura 2.2.0,
  notion-client 3.1.0, mcp (client for Windows-MCP). Skip those to avoid a
  double install; please add them to THIRD_PARTY.lock / doctor. FYI:
  Windows-MCP @b2016c0 pyproject says `requires-python = ">=3.14"`, not 3.13.
- 03:57 · @WS0 @WS2 from WS3: `dispatch.py` calls
  `approvals.request(hub, plan, conversation=)` but TASK §3.5 says
  `approvals.request(action, preview, critical=True)`. WS3 skills rely on the
  dispatch gate and only self-request (with the §3.5 form) when `approval is
  None`. Please settle one signature in §3.5. Also: social posts refuse an
  approval whose `channel` isn't voice/ui — keep `Approval.channel` filled.
- 03:57 · @WS4 from WS3: GitHub web fallback exists: `opencli voicevibe
  github-notifications --limit N -f json` → rows {rank,title,repo,reason,url,
  unread,id}; use via `vvhub.browser.OpenCLI().run("voicevibe",
  "github-notifications", flags={"limit": 20})`. I also write
  `store.add_watch_item(source="linkedin"|"instagram", kind="post"|"comment")`
  for reports.
- 04:03 · @WS4 from WS3: Notion for reports is ready: `from
  vvhub.skills.notes import NotionNotes; await NotionNotes().add_to_section(
  "Reports", title, markdown)` → {id, url}. Chunking handled; raises
  `NotesError` (user-facing text) when not connected. [done 14:50 WS4, c50e122]

- 03:55 · @WS1 @WS2 from WS0: **Laya/torch install is WS2's** (it owns
  laya_engine and knows the tiers). WS1: do NOT install torch/transformers/laya
  into venvs\voicevibe; WS2: install pinned CUDA torch + laya with
  `uv pip install --python ..\venvs\voicevibe\Scripts\python.exe`, then run
  the full suite and log exact versions. Only one chat installs into
  venvs\voicevibe at a time — announce `INSTALLING venvs\voicevibe` here
  first and `DONE` after. [decision]
- 03:55 · @WS1 from WS0: Windows-MCP needs Python >=3.14 → create
  `venvs\windows-mcp` with `uv venv --python 3.14.7`; telemetry off,
  exclude PowerShell/Registry/FileSystem. Also please write
  `Voice_Vibe\THIRD_PARTY.lock` + CONV.md §9 and log your installs
  (FreeLLMAPI in venvs\freellmapi, OpenCLI daemon, python packages) in §6 —
  the audit found them unlogged. [decision]
- 03:55 · @ALL from WS0: TASK.md §3.5/§3.7/§3.9 updated to match the code —
  re-read them. Use real `Get-Date` times in log entries. Commit only after
  the modules you import are committed (or commit together).

- 10:28 · @WS4 @WS5 from WS0: Voice Vibe now answers hub messages via `HubClient.handlers` in app.py. `transcribe` (voice notes), `list_mics`/`set_mic` are NOT wired yet — add them as handlers in app.py __init__ (small strReplace) when you need them. Hub→Voice Vibe: `await hub.bus.send_to('voicevibe', protocol.message('get_context', deep=True))`.
- 14:50 · @WS0 from WS4 [done 19543ef]: still open from 04:15 (not in server.py/__main__.py
  at 39a610a): ReportScheduler start/shutdown in the lifespan, `vvhub report`
  subcommand, `take_spoken()` on arm. The app.py `transcribe` handler for
  Telegram voice notes is also still missing; I'll leave app.py to you unless
  you say otherwise (it's a shared file and mid-flight for WS5).

- 15:12 · @ALL from WS0: read TASK.md rules 30 (LIVE LOCK: one chat at a time
  drives the desktop, a browser or a real account) and 31 (short replies, time
  limits). WS5 is unblocked. WS0 is doing F1-F7 (TASK.md WS0 section): don't
  edit app.py, hub_client.py, server.py or __main__.py until WS0 posts DONE
  here. @WS3: Windows-MCP IS installed: 0.8.5 on Python 3.13 in
  venvs\windows-mcp (0.8.6+ needs 3.14, so WS1 pinned 0.8.5); doctor shows it
  OK, so the Zen path is unblocked. @WS2: F1 will reply
  `confirm_result {approved, answer, unavailable}`.

- 15:26 · @WS2 @WS4 @WS5 from WS0: DONE (`19543ef`). TASK.md §3.2 updated:
  `confirm_result.unavailable` + the real `answer`, `get_context.pin`, new
  `armed` message. The edit freeze on app.py / hub_client.py / server.py /
  __main__.py is lifted (small strReplace edits, rule 28). Hub + Voice Vibe
  are running; hub log `%LOCALAPPDATA%\VoiceVibe\logs\vvhub.log`. @WS2:
  re-run your approvals tests. @WS4: the scheduler runs inside the hub;
  `python -m vvhub report --now` works. @WS5: T19 can take over starting the
  hub from run.bat (I used WMI Win32_Process.Create so neither dies with a
  tool shell).

## 8. Decisions & findings

### User decisions (planning chat, 2026-09-30)
- Merge into one front door: "hey computer" session → hub. No continuous
  transcription hotkey mode.
- Laya runs locally and decides/validates everything; LLM = FreeLLMAPI
  (tashfeenahmed/freellmapi, ~7.4B free tokens/month) for text + vision only.
- Own hub (option 2a). Integrations: Notion (auto notes, transcripts), the
  user's Instagram handle, LinkedIn personal profile, GitHub (gh logged in):
  create repos, commits, PRs.
- Laya decides small tasks as the user; critical ones ask.
- Reports in Notion + local HTML. Notify on new repos, PRs, new comments,
  posts, research — not ordinary commits.
- Browser automation, not APIs (Instagram/LinkedIn/GitHub web); GitHub gh CLI
  + browser both. Real browser (Edge or Zen) → OpenCLI extension (Edge) +
  Windows-MCP (Zen).
- Call word only while armed (Ctrl+Alt+W), not always listening.
- Vision: FreeLLMAPI on crops (or anything small that works).
- Phone: Telegram bot (forked repo), voice-note confirmations; no custom phone
  app/website.
- Code prompts go into Claude Code, Claude app, Codex app, VS Code terminal
  (Kiro too).
- Folders: Repos\, venvs\, Voice_Vibe\ under CIR\voicevibe; memory files at
  root; don't build from scratch; multiple parallel chats per TASK.md.
- Commit only Voice_Vibe on branch voicevibe-automation, push allowed.
- Pick components that run on a ~₹70k laptop without eating RAM/CPU.

### Research findings
- Laya: typed decisions (choice/score/noul), 1 forward pass; checkpoints laya
  (ModernBERT-large 421M), laya-multilingual (322M), laya-typed-decisions;
  ~33 ms/request T4 GPU, 193–464 ms CPU preloaded; `min_confidence` abstain;
  weak >20 options (use 2 levels); "confident while wrong" → hard safety floor;
  fine-tuning 0.362 → 0.766 on typed decisions; ONNXAgent + INT8 export.
  Needs torch 2.14 + transformers 5 (Python ≥3.10).
- FreeLLMAPI: Node 20+, Windows .exe, OpenAI/Anthropic-compatible on :3001,
  vision, tools, ~40 MB idle; "personal experimentation only"; no SLA.
- Chrome 136+ ignores --remote-debugging-port for the default profile (Edge
  reportedly the same) → drive the real browser through an extension.
- OpenCLI: Browser Bridge extension + daemon, logged-in Chrome/Edge session,
  built-in linkedin commands (posts, inbox, timeline, post-analytics…),
  adapter-author/autofix skills, desktop adapters incl. Codex; Chromium only.
- Windows-MCP (MIT): UIA tree, Snapshot/Screenshot with `region`, `use_dom`
  incl. Firefox via IAccessible2 (→ Zen); Python 3.13+; telemetry on by
  default (turn off); risky tools excludable.
- Agent-Reach: Instagram read via OpenCLI, LinkedIn public pages via Jina;
  web/YouTube/GitHub/Reddit/RSS; `agent-reach doctor`.
- Firecrawl AGPL + Docker/Redis → reference only.
- Munder Difflin: Electron, hive of files (inbox/outbox, single committer), no
  public API; Ctrl+Alt+Space dictation clashes with ours on Windows.
- Hermes Agent: messaging gateway (Telegram/WhatsApp/Signal), own LLM agent →
  patterns only.
- chatgpt-telegram-bot (n3d1117): GPL-2.0, python-telegram-bot, allowed user
  IDs, voice messages, plugins → fork base.
- Notion API limits: 100 blocks per append, 2000 chars per rich text.

### WS5 control app: framework choice (2026-09-30 18:26, measured)
Minimal window (tabs + 50-row table), started from a script, measured after
12 s idle over the whole process tree (python + WebView2/Flutter children)
with psutil. "RAM" = private working set (USS), which is Task Manager's
default Memory column; WS = full working set incl. shared DLLs. Throwaway
venv `venvs\ui-bench` (deleted after); PySide6 from the Airoot overlay-venv.

| Option | Start | RAM | Private | WS | Idle CPU | Hub API | Tray/autostart | Licence | Install |
|---|---|---|---|---|---|---|---|---|---|
| PySide6 6.11.2 widgets | 0.8 s | **19 MB** | 23 | 61 | 0 | QtNetwork or threads (more glue) | QSystemTrayIcon; HKCU Run | LGPL-3 | ~90 MB wheel |
| **pywebview 6.2.1 + page served by the hub** | 1.9 s | **122 MB** (WebView2 78 + host 43) | 218 | 414 | 0 | same-origin `fetch`/WebSocket | pystray (Voice Vibe) + HKCU Run | BSD-3 | 6 small wheels |
| Flet 1.0.3 | 1.1 s warm (36 s first run: client unpack) | 109 MB | 209 | 179 | 0.6 % of a core | Python httpx | none built in | Apache-2.0 | + ~100 MB Flutter client |
| NiceGUI 3.17.1 native | 8.3 s | 244 MB | 353 | 575 | 3.3 % of a core | in-process | via pywebview | MIT | 56 packages, own FastAPI pins |
| Tauri 2 | est. ~1 s | est. ~85 MB (WebView2 + Rust host) | – | – | – | `fetch` | plugin-autostart | MIT/Apache | needs Rust + Node toolchains; not pip-installable (no cargo here) |

Reference apps (all "local web UI in a thin native shell"): OpenJarvis
desktop = Tauri 2 around a React/Vite SPA (`frontend/`, pages Dashboard/
Chat/Logs/Settings/DataSources, tauri-plugin-autostart = HKCU Run on
Windows); FreeLLMAPI = Electron around the React/Vite dashboard its server
also serves (Keys/Analytics/Logs pages; keys pasted once, shown masked);
munder-difflin = Electron + React, office scene in pixi.js
(`src/renderer/src/scene/office/`, MIT).

**Choice: pywebview + a static page served by the hub** (same architecture
as the three references, in our stack). Same-origin calls to the hub API,
6 small pinned wheels, T20 can reuse munder-difflin's pixi.js scene as web
code. 122 MB < 150 MB target, and only while the window is open: the window
process exits on close; the tray entry is in Voice Vibe's existing pystray
icon (0 MB extra). Only PySide6 is also under 150 MB by full working set;
it stays the fallback (no WebView2 / tighter RAM) at the cost of hand-built
widgets and QtWebEngine for T20. NiceGUI (the TASK.md default) is out: 2×
the RAM, 8 s start, and it pins its own FastAPI stack next to the hub's.
### WS6 speech research (2026-09-30, web-verified by 3 research subagents)
STT (HF Open ASR avg WER; speeds are publishers' hardware):
- faster-whisper 1.2.1 (2025-10-31, MIT; no commits since 2025-11).
  `BatchedInferencePipeline` gives nothing for <30 s utterances (one chunk)
  and disables temperature fallback → not useful for dictation.
- distil-large-v3.5: `distil-whisper/distil-large-v3.5-ct2` (1.51 GB, MIT),
  WER 7.21 vs turbo 7.83, ~1.5× turbo speed, English-only, worse long-form.
- whisper.cpp v1.9.4 (2026-09-11, MIT); pywhispercpp 1.5.1 wheels CPU-only;
  CUDA 12.4 zip predates Blackwell.
- Parakeet TDT 0.6B v2/v3 (weights CC-BY-4.0 → credit NVIDIA): WER 6.05/6.32,
  punctuation + caps, int8 ~660 MB; onnx-asr 0.12.0 (MIT, pure Python,
  `istupakov/parakeet-tdt-0.6b-v2-onnx`) or sherpa-onnx 1.13.8 (Apache-2.0,
  win wheels); RTFx ≈30 int8 on an 8-core CPU; feed ≤20-30 s chunks.
  `parakeet-unified-en-0.6b` (5.91) is NVIDIA Open Model License — avoid.
- Canary-180M-flash (CC-BY-4.0): WER 7.12, int8 214 MB, RTF 0.156 on 2 threads.
- Moonshine v2 streaming (moonshine-voice 0.1.5, 2026-08-24, MIT, win wheel):
  Tiny/Small/Medium 34M/123M/245M, WER 12.0/7.84/6.65, x86 end-of-speech
  latency 69/165/269 ms.
- Kyutai STT (MIT/Apache, CC-BY): PyTorch/Rust-CUDA/MLX only, 1B ≈2 GB bf16,
  no CPU numbers → skip. Vosk 0.3.45 (2022; Apache-2.0): small-en 40 MB,
  grammar mode for commands, ~300 MB RAM.
Streaming: RealtimeSTT 1.1.2 (MIT, wraps faster-whisper + VADs, py<3.13);
WhisperLive 0.10.0 (MIT, server, pins faster-whisper 1.2.0 + torch/OpenVINO);
whisper_streaming superseded by SimulStreaming (MIT only since 2025-10-22,
torch/GPU). None needed for push-to-talk / segment-then-decode.
Wake word: openWakeWord 0.6.0 (code Apache-2.0, bundled models CC BY-NC-SA);
custom training Linux/Colab only (<1 h Colab, 17.5 GB features). Community
`computer_v2.onnx` (home-assistant-wakewords-collection, MIT repo): recall
0.57, 5.2 false accepts/h. sherpa-onnx KWS `kws-zipformer-gigaspeech-3.3M`
(4.6 MB int8, open vocabulary via text2token, 83.6% recall, 0.45 FA/h;
weights trained on GigaSpeech = research-only data).
VAD: Silero v6 (MIT; already inside faster-whisper as silero_vad_v6.onnx,
no torch) vs TEN VAD 1.0.6.8 (Apache-2.0 + non-compete conditions, win DLL,
10/16 ms frames). Each vendor's benchmark favours itself.
TTS: Kokoro-82M via kokoro-onnx 0.6.1 (MIT/Apache weights; espeak-ng GPL),
RTF ≈0.25 on 4 threads, peak 0.63-0.74 GB → on demand only. Piper 1.8.0
(rhasspy/piper archived 2025-10 → OHF-Voice/piper1-gpl, GPL-3.0; use the
public-domain ljspeech voice, not lessac/amy), ~63 MB/voice, RTF ≈0.12 on 2
ARM cores. SAPI/OneCore = zero cost; Win11 natural voices only via an
unofficial adapter.
Laya ONNX RAM (ORT 1.30): external-data weights are memory-mapped on CPU;
`enable_cpu_mem_arena=False`, `enable_mem_pattern=False`,
`intra_op_num_threads=2-4`, `session.intra_op.allow_spinning=0`; optimize
offline once (EXTENDED, save with external initializers) then load with
optimizations off. Estimate: peak 1.3-1.5 → 0.6-0.7 GB (to be measured).

## 9. Repo intel
(WS1, 2026-09-30. Clones in `Repos\`, pins in `Voice_Vibe\THIRD_PARTY.lock`.)

**laya** (NandhaKishorM/laya @6d942c9, Apache-2.0). Python package `laya`
(0.3.22): `laya.Router` (load/predict/unload per checkpoint), `laya.agent.Agent`
(torch), `laya.onnx_agent.ONNXAgent(model_id, onnx_path=)` (fetches only
tokenizer/config from HF, graph local). `scripts/export_onnx.py --quantize`
→ `<out>.int8.onnx` (per-channel INT8 MatMul, CPU-only; ORT has no INT8 CUDA
kernel). Reuse: all of it via laya_engine (WS2). Gotchas: export needs
`onnx onnxscript` (extra `laya[onnx]`) and **`PYTHONUTF8=1` on Windows** —
torch.onnx prints ✅ and crashes on cp1252. fp32 export = 1.7 GB .onnx.data;
int8 = 600 MB standalone. Also has `laya-ts/`, docker, benchmarks.

**freellmapi** (tashfeenahmed/freellmapi @6def0ff = v0.13.2, MIT). Node
monorepo: `server/` (Express router, SQLite, AES-GCM provider keys), `client/`
(React dashboard), `cli/` (`npx freellmapi keys …`), `desktop/` (Electron tray
embedding server+dashboard). OpenAI surfaces `/v1/chat/completions`,
`/v1/responses`, `/v1/models`, images/audio/embeddings; one unified
`freellmapi-…` bearer. Profiles `auto:<profile>` for fallback chains (vision
chain). Windows gotchas: **desktop default port 31415, not 3001** — set
`port` in `%APPDATA%\FreeLLMAPI\config.json` (the app rewrites it with the
port it actually bound; stop all FreeLLMAPI.exe processes before editing).
Binds 127.0.0.1 unless "Allow LAN access" (keep off). Desktop has no
password (hidden local account). Logs `%APPDATA%\FreeLLMAPI\logs\freeapi.log`.
Portable win.zip = 210 MB exe (Electron). Node engines <25.

**Agent-Reach** (Panniantong/Agent-Reach @a19a171, MIT). Python CLI
`agent_reach.cli:main`; channel modules per platform with tiers/backends;
`agent-reach doctor [--json]`, `install --channels`, `configure`. Reuse: web
(Jina Reader), RSS (feedparser), GitHub (gh), Instagram/Reddit via OpenCLI.
Gotchas: output is Chinese → **run with `PYTHONUTF8=1`** or it prints `?`;
detects OpenCLI only via PATH (added `venvs\node` to User PATH); YouTube
needs yt-dlp, Exa search needs `mcporter` (not installed; optional).

**opencli** (jackwener/opencli @2413694 = v1.8.8, Apache-2.0). TS CLI
`dist/src/main.js`; daemon `dist/src/daemon.js` on **localhost:19825**
(auto-starts, ~48 MB), Browser Bridge extension (MV3, `extension/`) connects
to it over ws. `GET /status` with header `X-OpenCLI: 1` → `extensionConnected`
(used by our doctor; **`opencli doctor` blocks until the extension connects —
never call it unattended**). Adapters in `clis/<site>/` (linkedin built-ins),
plugins via `opencli plugin create/install`, `browser <session> …`
primitives. Exit codes sysexits (69 bridge down, 77 auth). Skills in
`skills/` (installed). Chromium-only; `OPENCLI_PROFILE` for multi-profile.

**Windows-MCP** (CursorTouch/Windows-MCP @30c1472 = v0.8.5, MIT). FastMCP
server `windows-mcp serve --transport stdio|sse|streamable-http`; tools in
`tools/*.py`: App, Click, Type, Scroll, Move, Shortcut, Wait, WaitFor,
Snapshot, Screenshot, Scrape, Clipboard, Process, Notification,
DisplayInventory, MultiSelect, MultiEdit, PowerShell, Registry, FileSystem.
Config `~/.windows-mcp/config.toml` or `--config` (`[tools] exclude`);
env `WINDOWS_MCP_EXCLUDE_TOOLS`, `WINDOWS_MCP_SCREENSHOT_SCALE`,
`WINDOWS_MCP_MAX_TREE_ELEMENTS`, `WINDOWS_MCP_WATCHDOG`,
`WINDOWS_MCP_DISABLE_FLASH`. Gotchas: **HEAD 0.8.6 requires Python ≥3.14**
(pinned 0.8.5); telemetry (PostHog) is on unless
`ANONYMIZED_TELEMETRY=false` (set User env + WS3 driver sets it); HTTP modes
need `--auth-key` (stdio only for us). Startup ~1 s (fixed sleep).

**chatgpt-telegram-bot** (n3d1117 @df4dcaa, GPL-2.0, last commit 2024-12).
`bot/main.py` → `telegram_bot.py` (python-telegram-bot handlers, allowed
user IDs, voice/audio → Whisper via pydub+ffmpeg), `openai_helper.py`,
`plugins/`. Reuse: handlers/allowlist/plugin structure (WS4 vendored into
src\vvbot). Gotchas: unmaintained; pydub needs ffmpeg (replaced by PyAV).

**OpenJarvis** (open-jarvis/OpenJarvis @5e5f5ef, Apache-2.0). Python
`src/` + rust + frontend; reference for morning_digest report sections and
deep_research flow. Heavy; do not install.

**hermes-agent** (NousResearch/hermes-agent @94f3f17, MIT). Big agent;
`gateway/` has Telegram/WhatsApp/Signal adapters, pairing and approval
flows (`hermes_state_telegram.py`). Reference only (patterns for WS4).

**munder-difflin** (chaitanyagiri/munder-difflin @ed06e3e, MIT code).
Electron + electron-vite + React; renderer in `src/renderer`; "hive" of
files (`HIVE.md`), no public API. Gotcha: **pixel-art assets are LimeZu
licensed (LICENSE-ASSETS), credit required** — not MIT. Its Ctrl+Alt+Space
clashes with our dictation hotkey.

**firecrawl** (firecrawl/firecrawl @b5d187b, AGPL-3.0). `apps/api` (TS,
Redis/Playwright, Docker). Reference only — never copy code.

## 10. Resource measurements
- Dev laptop 2026-09-29: app with large-v3-turbo on GPU ≈706 MB RAM, added
  features ≈21 MB, Airoot ≈135 MB, VRAM ≈1.6 GB.
- (WS5 fills the CPU-only profile against the 1.5 GB budget.)

### WS6 speech engines (2026-09-30 20:30, `tools\bench\bench.py report`)
Data: 46 user clips (jack mic, 40 speech; 6 failed takes left out: w01 w02
c13 d05 d09 d12 — too quiet/short, no engine got half), 126 SAPI clips
(David, Zira, David +15 dB noise), 8 non-speech. CPU rows: 4 threads, no
GPU. WER after normalisation; Cmd = exact command match; Phantoms = text on
silence/noise.

| Profile | Engine | Peak RAM MB | WER user | WER synth | Cmd user | Phantoms | Latency s | RTF |
|---|---|---|---|---|---|---|---|---|
| GPU | turbo, app settings (**today**) | 1748 | **7.1%** | 0.7% | 71% | 0/8 | 0.30 | 0.073 |
| GPU | turbo, raw decode | 1748 | 8.7% | 1.7% | 67% | **8/8** | 0.30 | 0.073 |
| GPU | distil-large-v3.5 | 1648 | 10.3% | 1.2% | 62% | 0/8 | 0.28 | 0.069 |
| GPU | base.en beam 1 (today's command model) | 796 | 22.1% | 1.9% | 62% | 0/8 | 0.10 | 0.024 |
| CPU | base.en int8 (today, 4-core tier) | 389 | 20.2% | 0.7% | 52% | 0/8 | 0.58 | 0.142 |
| CPU | small.en int8 (today, 8-core tier) | 920 | 13.0% | 1.2% | 71% | 0/8 | 1.71 | 0.420 |
| CPU | distil-large-v3.5 int8 | 1787 | 10.7% | 1.2% | 57% | 0/8 | 6.65 | 1.633 |
| CPU | **Parakeet v2 int8 + Silero gate (shipped)** | 865 | **9.1%** | 2.0% | 62% | 0/8 | **0.25** | 0.061 |
| CPU | Parakeet v2 raw (onnx-asr) | 872 | 9.5% | 1.9% | 67% | 1/8 | 0.31 | 0.076 |
| CPU | Moonshine v2 medium / small | 526 / 349 | 19.8 / 27.7% | 2.0 / 2.7% | 38 / 33% | 0/8 | 0.54 / 0.44 | 0.13 / 0.11 |
| CPU | whisper.cpp small.en / base.en q5_1 | 525 / 264 | 15.8 / 24.9% | 1.9% | 67 / 48% | 7/8, 4/8 | 3.53 / 1.00 | 0.87 / 0.25 |
| CPU | Vosk small-en free / command grammar | 217 / 164 | 57.7% / — | 7.3 / 0.6% | 19 / **86%** | 1/8, 0/8 | 1.81 / 0.13 | 0.44 / 0.04 |

Wake word (all 180 clips, 12 positives, 677 s of negatives, 1 thread):
sherpa-onnx KWS "HEY/OK COMPUTER": recall 9/12, 0 false accepts (0 on 72
"computer …" commands), 27.5 ms CPU per s of audio. openWakeWord
computer_v2 and today's Whisper check: run in progress
(`results-wake.json`).

## 11. Open questions (do not resolve without asking the user)
From the old CONV.md, still open:
1. ANSWERED 16:38 (user reported vague transcripts): VAD, temperature
   fallback and the unsure-short drop are on in config.toml (09b9358); code
   defaults stay raw, so c3a4fbb's tests pass. Undo: set them false under
   [model]. Was: Silence hallucinations: turn VAD on and/or add the short low-confidence
   filter? (Conflicts with c3a4fbb's test_transcriber.)
2. Airoot "circle going to middle screen": which element, and do ab1c3c5 /
   9e71f88 already satisfy it?
3. `room.npy` (untracked scratch recording): delete?
4. Wake word model: openWakeWord has no "hey computer" — hey_jarvis, custom
   .onnx, or keep engine = "whisper"?
5. Partials vs logo-only Airoot (partials only reach the orb since 3231d38).
6. word_timestamps: any audio-aligned use?
7. "delete line" asks every time (trigger word "delete"): accept, exempt, or
   drop "delete"?
New:
8. Delete the empty `venv's\` folder and the old `Voice_Vibe\.venv` (after VS
   Code is closed)?

## 12. Appendix: As built before automation (the old Voice_Vibe\CONV.md, verbatim)

#### Voice Vibe — working context (conv.md)

Persistent project memory for the voice-control work. Read this first in a new
session. Newest explicit user instruction wins; update this file after each
meaningful change.

### Goal

Extend Voice Vibe (local Whisper dictation for Windows) into a voice
*control* tool: spoken commands after a prefix word drive the keyboard, mouse,
windows and apps, with safety gates — without ever breaking plain dictation.
The user supplies the roadmap in phases (pasted plans); work them in order.

### Working rules (user preferences)

- ~~**Nothing is committed.** Commit only when asked. All work below is
  uncommitted on `main` (plus untracked new files).~~ (Now committed: see
  "Committed 2026-09-28" under Phase status.) **Superseded
  2026-09-28 by user:** commit **without asking**, one commit per feature
  addition or bug fix. (The Phase 1–5 work was still uncommitted when this
  rule changed.)
- **No Claude co-author trailer** on commits (user, 2026-09-28: "dont make
  yourself co-author"). Plain commit messages only.
- Keep this file (`CONV.md`, project root) updated as handoff context. It is
  **git-ignored** (`.gitignore` line added outside this session) — local
  memory only, never committed.
- Target machines are low-spec laptops: no GPU assumed, little RAM. Every
  feature must degrade gracefully when an optional package is missing.
- Anything not recognised as a command must stay dictation (typed as heard).
- Tests: stdlib `unittest`, style of `tests/test_intent.py`; OS input and
  windows are faked (`tests/stubs.py`: FakeController, FakeMouse, FakeButton).
  Tests must never touch real windows, input, or the user's foreground app —
  always inject `desktop=`, `finder=`, keyboard/mouse fakes, or dry-run.
- Live checks on the user's machine: read-only only (enumerate windows, UIA,
  OCR). Never click/focus/minimize/lock their real windows without asking.

### Environment

- Windows 11, repo `C:\Users\vilas\Documents\CIR\voicevibe\Voice_Vibe`,
  venv `.venv` = **Python 3.11.16** (uv). Run tests:
  `cd tests && ../.venv/Scripts/python.exe -m unittest discover -s .`
  (currently **433 tests, OK, 8 skipped** — skips are pre-existing
  PySide/Windows-only ones).
- **Run the app (fixed command, any folder, any shell):**
  PowerShell `& "C:\Users\vilas\Documents\CIR\voicevibe\Voice_Vibe\run.bat"`,
  cmd `"C:\Users\vilas\Documents\CIR\voicevibe\Voice_Vibe\run.bat"`.
  Add `--console` for a visible log window; `--check` etc. get a console
  automatically. From the repo folder in PowerShell it must be `.\run.bat`
  (bare `run.bat` is not found). Verified 2026-09-28: `--version` → 0.1.0
  from both shells.
- Installed into venv this session: psutil 7.2.2, comtypes 1.4.17,
  uiautomation 2.0.29, winsdk 1.0.0b10, winrt-* 3.2.1 (OCR fallback path),
  openwakeword 0.6.0 (+ onnxruntime 1.30, scipy, scikit-learn; hey_jarvis
  model downloaded into the package's resources/models).
- Scratchpad test audio: `jarvis.wav` / `other.wav` (SAPI, 16 kHz mono).
- Bash tool quirk: inline heredoc Python patches containing some quote mixes
  fail ("unexpected EOF"); write patch scripts to the scratchpad or use Edit.
- User's apps seen running: VS Code, Claude desktop (`claude.exe`), Edge,
  Windows Terminal, Explorer, Photos, Fusion360. Zen browser installed
  (profiles in `%APPDATA%\zen\Profiles\*`).

### Architecture (as built)

Flow: session utterance → `app._do_session` → (bare "stop" while repeating?)
→ wake handling → sleep phrase → `_do_command_or_insert` →
`Router.split` (prefix must LEAD, exact words, default "computer") →
`Router.route(command)` → handled / else `_do_insert(original text)`.

Router order (Phase 4 spec): **active app profile → [[commands]] rows →
built-in global table → implicit click by exact name (UIA) → implicit OCR →
dictation.** Badge picks ("click 7"/"7") and "next one" are checked first
while active.

| File | Role |
|---|---|
| `__main__.py` | `enable_dpi_awareness()` first in `main()` (per-monitor, fallback SetProcessDPIAware) |
| `screen.py` | `window_info(hwnd)` {hwnd,title,process_name,rect}; DWM visible bounds; OCR `OcrResult/OcrLine/OcrWord` with boxes; `ocr_window(hwnd)` in screen px via `client_origin` (ClientToScreen); `capture_window` uses PW_CLIENTONLY; `_ocr_modules()` tries winsdk then winrt |
| `control.py` | `Router`, `Route(handled, caption, ends_dictation, speak)`, `Repeater` (keep scrolling), command grammar table, click-by-name, numbers/links, resolver for click_named, implicit click |
| `actions.py` | Spec parser + `Executor` (pynput). Steps: keys, type_text, click, scroll, wait, window, focus, lock, element, click_named, first_of, say, say_clipboard, sequence. Options on any step: `label`, `confirm`. Confirm gates, trigger words, dry-run, injectable keyboard/mouse/desktop/confirmer/resolver/say |
| `confirm.py` | `VoiceConfirmer`: speaks question (no "yes" in it), listens via `offer()` hand-off from `app._on_segment`, strict yes / loose no / ignore chatter / timeout = no |
| `winctl.py` | EnumWindows (Alt+Tab-visible, not cloaked), `match_window` (threshold 0.84), `focus` (AttachThreadInput), `show` (ShowWindow min/max/restore), `lock` (LockWorkStation), `process`, `Desktop` bundle |
| `uia.py` | `Element(name, control_type, rect, ref, source)` with invoke/select/focus; `Finder` (cached per window per command; one FindAllBuildCache call; Chromium first-contact retry; popups = same-process top-level windows); `rank`, `ambiguous`, `dedupe`, `reading_order`, `rank_text`/`text_boxes` for OCR |
| `overlay.py` | Orb + shared `_create_layered_window`/`_blit`; `render_badges`, `Badges` (own thread/window, click-through, independent of `[overlay].enabled`) |
| `profiles.py` | Per-app profiles: phrase templates (`{name}`, `a|b`), `fill`, `build_commands`, built-ins Explorer / Zen (read from zen-keyboard-shortcuts.json, auto-reload on change) / Claude / ChatGPT, `load_profiles(rows)` merging `[[profiles]]` |
| `config.py` / `config.toml` | `[control]` (enabled=false, prefixes, scroll_amount, keep_scrolling_limit, badge_seconds, implicit_click/implicit_ocr, confirm_words, confirm_timeout, yes/no words), `[[profiles]]`, `[vocab]`, `[wake]` engine/model/threshold/confirm_with_whisper, `[model]` command_model/command_max_seconds, `[continuous]` partials/partial_interval, `[output]` spoken_edits/apply_replacements |
| `app.py` | Wires Router/Executor/VoiceConfirmer/Badges/Finder; speaks `route.speak`; `executor.say = voice.say`; stops repeats on session close/shutdown; `_decoder_prompt`, `_transcribe_job` (model choice), wake-word hand-over (`_on_frame`/`_on_wake_word`/`_confirm_wake`), `_do_edit`, `_partials` loop |
| `vocab.py` | hotwords + per-app prompt hints (item 19) |
| `wakeword.py` | openWakeWord detector thread (item 20) |
| `suggest.py` | `--suggest-replacements` history analysis (item 24) |
| `transcriber.py` | + `hotwords`, per-model decode lock, `transcribe(beam_size, wait)`, `model_size`, `choose_command_model` |

### Key decisions (and why)

- Trigger via **leading prefix word inside the session** (not a 2nd hotkey).
  Unhandled command → typed exactly as heard, prefix included.
- Commands only once the session is woken (armed state ignores them);
  bare "stop" is the exception while a repeat runs.
- **Confirmation is just-in-time at the gated step**, not up front. Trigger
  words (default delete/uninstall/send/buy) match *inside* words ("resend"),
  check the spoken command, step labels, keys, and click_named names — **not**
  type_text. They override `confirm: false`. A command-level gate suppresses
  forced inner gates (ask once); explicit inner gates still ask. Profile
  commands check triggers against the phrase's literal words, not captured
  text ("ask how to delete X" doesn't ask; "delete {name}" does).
- Confirmation answers: yes = whole utterance is yes-words; any no-word
  cancels; other speech ignored; silence → cancel. Question spoken without
  "yes"; listening starts after speaking (echo-safe).
- Whole spec validated before any input; `ActionError` means nothing ran.
- `keys` validation is strict (unknown token → error), unlike `_resolve_keys`.
- Lock via LockWorkStation (Win+L can't be synthesized); min/max/restore via
  ShowWindow; snap/monitor/desktop via Win shortcuts.
- UIA rects are already screen coords; ClientToScreen is only for OCR boxes.
- Ambiguous same-kind ties → numbered badges, nothing clicked. Non-tie
  multiple matches → click best, "next one" walks the rest.
- Implicit click requires an exact name (score 1.0) / OCR ≥ 0.95; code
  default off, config.toml turns it on (≈2s OCR latency before fallthrough).
- `[[commands]]` rows are router commands (they were dormant in dictation).

### Verified live (read-only)

- DPI awareness level 2; window_info on Edge; winctl enumerates 12 windows,
  matches code/edge/youtube/fusion 360/file explorer; "photoshop" → none
  (bug found & fixed: launcher threshold 0.78 matched Photos.exe at 0.80).
- UIA FindAllBuildCache 0.04–0.3s/window; Chromium apps (VS Code, Claude,
  Edge) expose only caption buttons until first query, then 30–90 elements.
- OCR on VS Code: ~120 lines in ~2s, boxes in screen px; winrt path works
  with winsdk blocked (Python 3.12 story).
- Claude desktop UIA names: Copy, Send, Scroll to bottom, Read aloud,
  Show sidebar; prompt = Edit "Prompt". No "New chat" visible when sidebar
  collapsed (profile opens sidebar first).
- User's Zen shortcuts: workspaces ctrl+alt+←/→, split ctrl+alt+g/v/h/u,
  **compact mode = ctrl+s** (collides with Save in Zen), pin tab
  ctrl+shift+d, copy url ctrl+shift+c; workspace 1–10 and toggle-sidebar
  unbound (profile says "no shortcut set in Zen").

### Not verified live / known limits

- No real clicks, focus switches, window ops, lock, badges on screen, or
  spoken confirmation round-trip have been exercised.
- Explorer command-bar names ("Sort", "View", "Show", "Hidden items") are
  assumed (Explorer was on Home page); "show hidden files" toggles.
- ChatGPT desktop shortcuts from memory (ctrl+shift+o, shift+esc,
  ctrl+shift+c) — unverified.
- "delete line" generic = home, shift+down, delete (VS Code smart-home
  leaves indentation; override via [[commands]] ctrl+shift+k). Asks
  confirmation every time (trigger "delete") — flagged to user.
- "pin tab" globally = spoken "can't yet"; Zen profile really pins.
- "save as X" types name, doesn't press Enter. "duplicate tab" only
  Chrome/Edge/Firefox (alt+d, alt+enter).
- Saying prefix then pausing splits utterances ("computer" typed alone).
- Whisper can hallucinate "yes" from noise (low risk; segments need VAD).

### Phase status

- Phase 1 (1–4): window_info + DPI; Router skeleton + prefix; actions
  executor + dry-run; confirmation layer — **done**.
- Phase 2 (5–9): editing/scroll/tabs/windows/switch-to/system — **done**.
- Phase 3 (10–14): UIA finder, click by name, badges, OCR fallback with
  word boxes, show links — **done** (pyproject `screen` extra: uiautomation,
  winsdk <3.12, winrt-* ≥3.12).
- Phase 4 (15–18): profiles + Explorer/Zen/Claude/ChatGPT — **done**.
- Phase 5 (19–24): **done** (21 last, as asked) — details below.

Next: nothing queued. Await the user's next phase / answers to the open
questions at the end of this file.

### Committed 2026-09-28 (on `main`, NOT pushed)

All Phase 1–5 work is committed as 15 sequential commits on top of 9e71f88,
each passing the full suite at that point (test counts 139 → 433), no
co-author trailer, author Sndcooper:

    371e100 Keep the local CONV.md notes out of git   (.gitignore)
    8857625 Add DPI awareness and foreground window info          (item 1)
    23b7631 Route prefixed session utterances to a command router (item 2)
    e3a5b54 Add an action executor for keys, typing, clicks and scrolls (3)
    1c6218c Ask for spoken confirmation before dangerous actions  (item 4)
    bbda07d Add global voice commands: editing, scrolling, tabs,… (Phase 2)
    beaa226 Capture only the client area in capture_window        (bug fix)
    2cd3c43 Click on-screen elements by name, numbered hints, OCR (Phase 3)
    7f10133 Add per-app command profiles for Explorer, Zen, …     (Phase 4)
    e9b3ab6 Bias transcription with hotwords and per-app hints    (19)
    ad3bbc0 Detect the wake word with openWakeWord                (20)
    d8a441e Use a small Whisper model for short command utterances (22)
    8113aba Bring back spoken edits and word replacements (opt-in) (23)
    38ed337 Suggest word replacements from dictation history      (24)
    ab7781f Show interim transcripts while speaking               (21)

How: intermediate file states were derived backwards from the final tree
(scripts in the session scratchpad `seq/`), replayed in a temp worktree,
then `main` was `reset --mixed` onto the result (tree identical to the
working copy). Push target when asked: `SndcooperPrivate` (Sndcooper/Voice_Vibe
is disabled by GitHub). `room.npy` remains untracked.

Fixed while committing: the commented `[[profiles]]` example in config.toml
sat inside `[control]` above confirm_words — uncommenting it would have moved
confirm_words/timeout/yes/no into `[profiles.commands]`. Moved below
`no_words`; verified by parsing an uncommented copy.

### 2026-09-29: "Ctrl+Alt+Space not listening / turns itself off" — fixed

User report: dictation "not listening", "auto turning off, not waiting for
me to complete". Diagnosis from `%LOCALAPPDATA%\VoiceVibe\logs\voicevibe.log`:

1. **Recording Stereo Mix, not the mic.** Log: `Preferred input [1] Stereo
   Mix`. `[audio].input_priority` was `["Microphone (Realtek(R) Audio)",
   "Stereo Mix"]` (from 1d8fa42); no device of the first name exists without a
   jack mic, so the loopback won. Measured 2 s: Mic Array rms 0.0019 vs Stereo
   Mix 0.000017 → every take was silence → Whisper phantoms ("Thank you.",
   "You.", "I'll see you next time.", "."). Fixed `7a5f88d`: priority now
   `["Microphone (Realtek(R) Audio)", "Microphone Array"]` (substring match —
   MME truncates the name to "Microphone Array (Realtek(R) Au"), plus a
   warning whenever a preferred input is a loopback. `--check` now reports
   `[2] Microphone Array`. The code still honours an explicit loopback
   (1d8fa42's test kept, now also asserts the warning).
2. **Double toggles.** Log: stop at 23:59:07.375, start again 56 ms later.
   Fixed `dcfd87e`: `toggle()` ignores a repeat within 0.4 s
   (`VoiceVibe.TOGGLE_DEBOUNCE`); `HotkeyListener(check_held=physically_down)`
   drops held keys that `GetAsyncKeyState` says are up (key events in admin
   windows never reach the hook → stuck Ctrl+Alt → lone Space fired). Root
   cause of the 56 ms double fire itself not proven; debounce covers it.
3. **Prompt echo (regression from item 19).** Log: "Open a pull request after
   the git commit commit commit…" = the VS Code hint read back on silence.
   Fixed `0a1179d`: `vocab.echoes_prompt()` drops a transcript that (repeats
   collapsed) is ≥90% one ≥4-word run of the prompt; not applied while armed.

A running instance (python.exe PID 43416, started 08:45 09-29) still had the
old code/config — user must restart it. Still open: silence phantoms on a
*real* mic (VAD / low-confidence filter, open question 1).

Follow-up (user: "doesn't it switch to the system default mic?" / "stereo mic
doesn't work"): the Windows default input **is Stereo Mix** in every host API
(MME [1], WASAPI [12], WDM-KS [17]); endpoints are only Speakers, Microphone
Array, Stereo Mix. Advised the user to set Windows Input to Microphone Array
and/or disable Stereo Mix (admin, Sound control panel). Code `b079c36`:
selection order is now **Windows default if it is a real mic → else
input_priority → else best mic**, re-chosen **before every recording**
(`Config.refresh_input_device()` → `audio.refresh_devices()` =
`sd._terminate(); sd._initialize()`, ~40 ms, skipped while `sd.get_stream()`
is active so Soprano speech isn't cut; `app._choose_microphone()` updates
recorder, session and Airoot and logs "Microphone: …" on change). A pinned
`[audio].input_device` is untouched. This deliberately reverses 1d8fa42's
test that an explicit "Stereo Mix" entry beats a real default mic (test
renamed/rewritten). Warnings are de-duplicated (`audio._warned`).

### Phase 5 decisions

Order: 19 → 20 → 22 → 23 → 24 → 21 (user: 21 last, it touches display).

19. **DONE.** `vocab.py` `Vocabulary(cfg)`: `hotwords_text()` →
    `Transcriber.hotwords` (class attr default None, passed as faster-whisper
    `hotwords`; combines with initial_prompt). `hint(process)` from
    `BUILTIN_PROMPTS` (editors, terminals, claude/chatgpt) + `[vocab.prompts]`
    ("" disables one; `app_prompts=false` drops built-ins).
    `app._decoder_prompt(armed, process)`: armed → wake phrases only;
    else `[model].initial_prompt` + hint. Worker sets it **per job** from
    `winctl.front_process()`. Tests: `tests/test_vocab.py`.
20. **DONE.** `wakeword.py` `WakeWordDetector` (feed() from audio callback →
    bounded queue → own thread; regroups 30 ms blocks into 1280-sample int16
    frames; threshold + 1.5 s cooldown; `create()` returns None if package /
    model missing → Whisper path). `SegmentRecorder(on_frame=)` hook.
    App: `[wake].engine="openwakeword"` (default still "whisper"),
    `model="hey_jarvis"`, `threshold`, `confirm_with_whisper`. Frames fed only
    while ARMED; armed segments dropped **untranscribed** in the worker;
    `_on_wake_word` → DICTATING + `_confirm_wake`; next transcript must contain
    the wake phrase (model's phrase auto-added to matcher) else re-arm.
    `VoiceVibe.detector/_confirm_wake` are class defaults (tests use
    `__new__`). pyproject extra `wakeword`. **No pretrained "hey computer"**
    (only hey_jarvis, alexa, hey_mycroft, hey_rhasspy) — user must pick one
    or train a custom .onnx. Verified live: openwakeword 0.6.0 +
    onnxruntime 1.30 installed; SAPI-synthesized "Hey Jarvis…" → fires once
    (0.94–0.997), other sentence → 0.000; 1.8 ms per 80 ms frame.
    Tests: `tests/test_wakeword.py`.
21. **DONE.** `Recorder`/`SegmentRecorder.snapshot() -> (take id, audio)`
    and `still(take)` (utterance id bumps at each onset). `Transcriber.
    transcribe(audio, beam_size=None, wait=True)` with a per-model lock:
    interim passes use `wait=False` (skip if a final is decoding) and beam 1.
    `app._partials` thread (only if `_partials_enabled()`:
    `[continuous].partials = "auto"` → GPU only, true/false) every
    `partial_interval=0.8` s: source = hotkey recorder, or session when not
    armed; skipped during confirmations; needs ≥0.8 s audio and ≥0.4 s growth;
    uses command model if loaded; shows via `airoot.show_transcript(text,
    "Listening")` + orb; dropped if the take ended mid-decode (never
    overwrites the final). **Tension:** earlier-session wish was "no
    Listening pill, only the dancing logo" — partials show text during
    listening; `partials=false` restores logo-only. Flag to user.
    Verified live: base.en on GPU, SAPI audio through a real
    SegmentRecorder → interim "Hey Jarvis, open the download." at 2.4 s
    (69 ms), final "…Downloads folder." Tests: `tests/test_partials.py`.
22. **DONE.** `transcriber.choose_command_model(setting, main, language)` +
    `model_size()`; `[model].command_model="auto"` (→ base.en / base; None
    if main is no bigger or setting ""/off), `command_max_seconds=3.0`.
    `app._load_command_model()` after main warmup (same device, beam 1,
    same hotwords; failure → None). `app._transcribe_job(audio, action,
    armed)`: sets prompt on both models; fast model for armed wake checks
    and `router.expects_command()` (numbers up / repeating / "next one");
    short SESSION utterances with control on get a fast first pass, kept only
    if `router.split` finds the prefix, else main model re-transcribes.
    Confirmer answers use the fast model. `VoiceVibe.command_transcriber`
    class default None. On the user's machine: main = large-v3-turbo (GPU) so
    base.en loads. Verified live: base.en on CUDA ~100 ms per 3.5 s clip,
    exact transcripts, hotwords accepted. Tests: `tests/test_command_model.py`.
23. **DONE (opt-in).** `[output].spoken_edits=false` default. polish.py:
    `parse_edit(text) -> (name, args)` (old edits + `delete_words` "delete/
    remove/erase/scratch the last [N] word(s)", `replace` "replace X with Y" —
    NOT "change X to Y", which people dictate); `detect_edit` still returns
    the name; `apply_edit(name, previous, **args)`; `edit_applies` (a replace
    only claims the utterance if X is in the previous text, else it's typed).
    `app._do_edit` restored (from c3a4fbb) with **minimal keystrokes**: erase
    back to the first differing char, type the new tail. History records
    edit/previous/find/replace. **Decision: `word_timestamps` NOT added** —
    edits operate on the already-inserted text (word boundaries known); timestamps
    only map words to audio time and add an alignment pass per utterance.
    Offer to add if the user has an audio-aligned use. Does not resolve open
    question 4 (features stay removed unless opted in).
    Also `[output].apply_replacements=false` + `inserter.apply_replacements()`
    (whole words, any case) so item 24's suggestions can take effect.
    Tests: `tests/test_edits.py`.
24. **DONE.** `suggest.py` + CLI `--suggest-replacements [--min-count 2]`
    (also added to run.bat's console list). Reads
    `%LOCALAPPDATA%\VoiceVibe\history\*.jsonl`, writes nothing, prints
    `[[replacements]]` TOML. Evidence: replace edits (1.0), scratch-that +
    retry ≤60 s (1.0), same-window re-dictation ≤30 s (0.5). `swaps()` needs
    ≥0.5 word similarity, ≤3-word spans, ignores case-only and
    stopword-only swaps; skips finds already in config; conflicting fixes →
    most common. Real history today: 30 `dictate` records, 0 suggestions
    (no edits recorded yet since spoken edits were off). Works with
    `apply_replacements` from item 23. Tests: `tests/test_suggest.py`.

---

### Earlier session (2026-09-22 → 09-27): fork setup, fixes, Airoot

Added 2026-09-28 from the first chat, which ran before the Phase 1–5 work
above. Everything in this section is committed and pushed unless it says
otherwise.

### Origin and original requirements

Fork of `Masqiller/Voice_Vibe`. The user's first eight asks: (1) no terminal
window on start; (2) "open blender" etc. opens apps; (3) replies (it gave
none); (4) more voice commands than "enter"; (5) a GUI pinned over other apps,
Siri-like, **not a window and not tkinter**; (6) read the screen for context;
(7) lighter, lower-RAM models; (8) run in the background and log turns as a
chat history.

Constraints the user set: **no big LLMs** (keep Whisper + Soprano; replies
are deterministic matching, not generation); screen reading via **OCR + UI
Automation, not a vision model**; built for **low-budget laptops, not the
user's own machine**.

### Machine facts (user's dev laptop)

- RTX 5060 Laptop GPU (8 GB, Blackwell) + AMD iGPU, 32 GB RAM, 32 cores,
  1920×1200 at 100% scaling. System Python 3.10 and 3.13 (3.13 unsupported).
- **Default Windows input is "Stereo Mix", a loopback — it records silence.**
  (Still true on 2026-09-29; never put it in `input_priority` — see the
  2026-09-29 fix under Phase status.)
  The real mic is `[2] Microphone Array (Realtek)` (MME), with `[7]`
  DirectSound as an alternative; WASAPI `[11]` and WDM-KS fail at 16 kHz.
- **The GPU needs `uv pip install -e ".[cuda]"`.** A plain `-e .` leaves
  cublas64_12.dll missing: the model loads on CUDA, then the first transcribe
  fails and the overlay stays on "transcribing" forever.
- Hugging Face downloads run at about 2.8 MB/s, so large-v3-turbo (1.6 GB)
  takes about 10 minutes. `HF_HUB_DISABLE_XET=1` was used. Cached models:
  large-v3-turbo, base.en, tiny.en.
- The VS Code isort extension launches python.exe from `.venv` and relaunches
  it when killed, which locks `.venv` against deletion. Delete in the gap
  between relaunches, or close VS Code first.
- `uv` is installed at `%APPDATA%\uv`.

### Bugs found and fixed (committed)

- `.gitignore` `_*.py` matched `__main__.py`/`__init__.py`, so the app could
  not start. The pattern is now anchored as `/_*.py`, and both files were
  rewritten (CLI: --check, --mic-test, --test, --wake-test, --say,
  --list-devices, --key-test).
- Python 3.10 `tomllib` → tomli fallback; `ctranslate2>=4.6` pinned for
  Blackwell.
- Audio callback did blocking tray work while holding a lock;
  `_voiced_blocks` was never reset; a lock was held across the 0.3 s drain;
  max_duration truncation was silent.
- A hotkey overlap let one gesture fire two actions (f9 then shift).
- The clipboard restore race now restores off-thread.
- Missing ctypes restype/argtypes truncated 64-bit handles: HWND (focus and
  capture) and **GDI HDC in `capture_window`**. The GDI one crashed the job
  and showed up as "couldn't transcribe".
- `warmup()` swallowed GPU errors at debug level. A broken GPU is now logged
  and the model falls back to CPU, and `--check` probes real GPU inference.
- Loopback auto-avoidance: an empty `input_device` skips Stereo Mix and alias
  devices (Sound Mapper / Primary Sound Capture). Later refined by commit
  `1d8fa42`, which prefers the requested mic.
- Uncaught exceptions under pythonw are now logged instead of vanishing.

### Decisions from that session

- **Hotkeys are off the F-keys**, because the laptop top row sends
  media/brightness keys. Current bindings: dictate `ctrl+alt+space`, session
  `ctrl+alt+w`, speak `ctrl+alt+shift+space`, quit `ctrl+alt+shift+q`. Use
  `--key-test` to find the name of any key.
- `[model].name = "auto"` picks the model tier by hardware: GPU →
  large-v3-turbo, 8+ cores → small.en, 4+ cores → base.en, otherwise tiny.en.
- `run.bat` launches pythonw with no console. Diagnostic flags and
  `--console` still get a console.
- The built-in orb (`overlay.py`) is **disabled** (`[overlay].enabled =
  false`); the Airoot overlay replaces it.
- The wake-phrase decoder bias applies **only while armed**. During
  dictation it made silence decode as "Computer."

### Airoot overlay (separate app)

- Source is now in `assets/airoot_overlay.py` (`ab1c3c5`). It was originally
  `C:\Users\vilas\Documents\Codex\2026-09-23\make\outputs\`. The EXE at that
  outputs path is what `[airoot].exe` launches.
- Build: `assets/AirootVoiceOverlay.spec` with that workspace's
  `work/overlay-venv`. **Keep the ICU DLL exclusion** (icuuc.dll /
  icudt78.dll), or QtCore fails to import. Run `--self-test` before replacing
  the EXE.
- Protocol: UDP `127.0.0.1:53873`, ASCII commands `show`, `show <device>`,
  `transcribing`, `hide`, `quit`, and `start` (launch hidden).
  `airoot.py` `AirootBridge` sends one packet per state change, preloads with
  `start`, and quits the overlay on exit only if it launched it.
- Fixes: it never takes focus (`WindowDoesNotAcceptFocus`,
  `WA_ShowWithoutActivating`), because focus stealing sent dictation into the
  overlay. It meters the same mic Voice Vibe uses (`show <device>`). Frames
  are pre-scaled with Lanczos to stop visible cracking.
- **2026-09-29: "dance 50% more, it's very minimal"** → `GROWTH` 0.24 → 0.36
  and new `DANCE_SPEED` 24 → 36 fps (sprite speed × √level); sensitivity
  (`rms * 24`) unchanged. Rebuilt with work/overlay-venv + the spec (ICU
  exclusion kept), 8 overlay tests OK offscreen, built EXE `--self-test`
  exit 0, replaced outputs\AirootVoiceOverlay.exe (backup
  `AirootVoiceOverlay.pre-dance50.exe`, the 09-27 16:31 build), relaunched
  Voice Vibe 17:10:55. Source commit below; EXE is outside the repo. At full
  level the logo (180×125) touches the 220×200 window's top edge by ~0.5 px.
- User's stated wishes, in order: logo smaller and higher; the red dot only
  while transcribing; no "Listening" pill while listening, only the dancing
  logo; a strong voice reaction (GROWTH 0.50 per notes — but the source had
  0.24 before 2026-09-29). **Latest:** "remove the circle
  thing going to middle screen; make the logo go into the listening-size
  widget, show Transcribing, then vanish." `ab1c3c5` (gather into the
  capsule, then fade) and `9e71f88` (logo only while recording) look like
  they implement this; not re-verified by me.
- Cost: about 135 MB RAM, far more than the rest of the added features
  combined (about 21 MB).

### Git / repo

- The private repo is `Sndcooper/Voice_Vibe-private` (remote
  `SndcooperPrivate`). **`Sndcooper/Voice_Vibe` is disabled by GitHub**: push
  returns 403 while reads work. The cause is a GitHub-side flag on that repo,
  not the account.
- That session committed and pushed after each fix. The user had asked for
  sequential commits plus a private repo.
- `room.npy` in the repo root is an untracked scratch file (recorded room
  tone) from that session's testing.

### Measurements (for later decisions)

- RAM: the app with large-v3-turbo on GPU is about 706 MB, **identical to the
  original repo**. The added features cost about 21 MB and Airoot about
  135 MB. VRAM is about 1.6 GB. Transcription uses about 1 CPU core and runs
  about 33× faster than real time on the GPU.
- **Accuracy vs. phantom text (still unresolved, see below):**
  - The old peak gate of 0.02 threw away quiet speech. That caused the user's
    "only 30–40% transcribed" report. Whisper transcribes correctly down to
    a peak of 0.008.
  - `no_speech_prob` is 0.000 for both real speech and hallucinations, so it
    is useless as a filter. `avg_logprob` is −0.18 to −0.23 for speech and
    −0.4 to −1.8 for hallucinations.
  - On current settings (`c3a4fbb`: VAD off, beam 3, no drops), 3 of 3 real
    room-tone samples hallucinate ("Thank you.", "Yeah, yeah, yeah").
    Turning VAD on costs no accuracy at any tested level and fixes true
    silence. VAD plus dropping segments of 5 words or fewer with logprob
    below −0.8 fixes 2 of 3. The third sample contained a real 2 s sound.
  - This **conflicts with c3a4fbb's tests** (VAD off, never drop segments),
    so it was not applied. It is waiting on the user.

### User decisions 2026-09-28 (answers to the open questions below)

- **Q1 → mode separation.** User: "only hey computer should be on when
  ctrl alt w is pressed that enables it which is for controlling laptop
  vocally." Rule: the wake phrase and the "computer" command prefix belong
  **only to the Ctrl+Alt+W session**, which is the voice-control mode.
  Ctrl+Alt+Space dictation is plain dictation: no wake phrase, no command
  prefix, no wake bias.
  - Already true in code: the wake bias applies only while armed.
    `[vocab].hotwords` defaults to `[]`, so nothing biases dictation toward
    "computer".
  - Still unanswered: whether to turn VAD on or add the low-confidence
    filter against phantom "Thank you." on silence.
- **Q2 → commit without asking.** Make one commit per feature or bug fix.
  See Working rules.
- **Q4 → restore the features, as UI automation.** User: "those features are
  for ui automation get that back keep it here." Restore app launching,
  screen questions ("what's on my screen", "what is this error"), spoken edits
  and list formatting. They belong to the **voice-control / UI-automation
  side** (the Ctrl+Alt+W session), consistent with Q1, not to plain
  dictation. Item 23's `spoken_edits=false` default was set before this
  decision; revisit it for the session mode.
- **Q3 → not answered yet.**

### Open questions for the user (do not resolve without asking)

1. **Silence hallucinations:** turn VAD back on, and/or add the short
   low-confidence filter? Both require changing c3a4fbb's
   `tests/test_transcriber.py`. *(Partly answered 2026-09-28: mode separation;
   the VAD/filter choice is still open.)*
2. **Commit policy:** the rules above say "commit only when asked", but the
   earlier session committed and pushed each fix. Which applies from now on?
   *(ANSWERED 2026-09-28: commit without asking, per feature or bug fix.)*
3. **Airoot "circle going to middle screen":** it is unclear which element
   the user meant, and whether `ab1c3c5`/`9e71f88` already satisfy the
   request. The EXE in use was built at 13:10, before `ab1c3c5` was
   committed at 15:52, so it may not contain the morph.
4. **Features removed from dictation by c3a4fbb** (app launching, screen
   questions, spoken edits, lists): keep them removed, or restore them? Item
   23 of the phase plan above already plans spoken edits as opt-in.
   *(ANSWERED 2026-09-28: restore them as UI-automation features of the
   Ctrl+Alt+W session.)*
5. **`room.npy`** in the repo root is an untracked scratch recording from
   the earlier session. Delete it? *(Asked 2026-09-28.)*
5. **Wake word model:** openWakeWord has no "hey computer". Switch the wake
   phrase to hey_jarvis (etc.), train a custom .onnx, or keep
   `engine = "whisper"` (current default)?
6. **Partials vs. logo-only Airoot:** `partials = "auto"` shows interim text
   on the GPU machine, which contradicts the earlier "no Listening pill"
   wish. Keep on, or set `partials = false`?
7. **word_timestamps:** not added (item 23 reasoning). Is there an
   audio-aligned use in mind that needs them?
8. **"delete line" asks every time** because "delete" is a trigger word.
   Accept, exempt editing commands, or drop "delete" from the list?


### 2026-09-29: requirements audit and runtime verification

User asked to compare the implementation with this context and requirements,
run it properly, and test it. Treat this section as newer than the phase notes.

Fixed and committed locally (not pushed):
- `002af35`: explicit CPU mode now auto-selects a CPU-sized model even when a
  GPU is present. CUDA model-load failure also uses the CPU tier and int8,
  honoring CPU thread settings instead of retrying a GPU-sized float16 model.
- `4c4193f`: implemented the previously unfulfilled Q4 decision. Checked-in
  config enables control, assistant replies, and Start Menu discovery.
  In awake Ctrl+Alt+W sessions, prefixed commands fall through from the router
  to restored assistant replies/app launching or previous-utterance edits.
  Examples: `computer open notepad`, `computer where am I`,
  `computer scratch that`, `computer replace Tuesday with Wednesday`.
  Trigger-word deletion edits use the existing executor confirmation gate.
  `[control].spoken_edits` and `format_lists` default true; lists apply to
  session dictation only. Bare assistant requests/edits remain dictation.
  Plain Ctrl+Alt+Space never performs spoken edits, even if the obsolete
  `[output].spoken_edits` is set. Pending session commands cannot divert
  plain dictation or TTS capture to the small command model.
  Previous edit text is cleared on new sessions, handled router commands,
  assistant actions, submission, and plain dictation. Cursor movement inside
  a target is not tracked; edits still assume the previous insertion point.
  README usage/command examples were updated; older historical feature
  descriptions elsewhere may still need further editorial cleanup.

Verification:
- Main unittest discovery: 462 tests, OK, 8 skipped (PySide6 unavailable in
  app venv). Those 8 overlay animation tests all passed separately in the
  existing overlay-venv with QT_QPA_PLATFORM=offscreen.
- Source/test compile check and git diff whitespace check passed.
- `run.bat --check`: GPU inference works, CUDA DLLs registered, clipboard
  readable, selected Microphone Array [2] instead of default Stereo Mix [1].
- Generated SAPI speech to a temporary WAV (no speaker playback), decoded
  through actual large-v3-turbo CUDA and base.en CUDA: expected wake phrase,
  scroll command and login-handler sentence recognized. Main decode 0.386 s.
  Actual tiny.en CPU/int8 also recognized the same sentence.
- `run.bat --mic-test --seconds 3`: opened microphone and received 3.07 s of
  audio, but peak 0.00009 / RMS 0.00002: near-silence, diagnostic failed.
  Asked user whether they were speaking / muted; no answer as of this note.
  This does not establish that human speech recognition works on this mic.
- Launched via run.bat at 12:52. Log reports Voice Vibe ready at 12:52:08,
  GPU main + base.en models, 212 app entries, UIA/OCR available, commands and
  replies on. Airoot process started. App left running; pythonw launcher
  PID 45196 (child 46064), overlay launcher 46436 (child 46748).
- No live clicks, window operations, real text insertion, spoken confirmation
  round trip, or human speech recognition exercised. All input-action tests
  used fakes; overlay tests were offscreen. Existing VAD/low-confidence and
  partials/logo-only choices were left unchanged. `room.npy` retained.

### 2026-09-29 17:00: "listens, stops by itself, transcribes random stuff"

User: dictation listens, then stops automatically, transcribes random stuff
and saves; doesn't wait for the second hotkey press.

Diagnosis (log + py-spy of the running pythonw 46064 + Airoot source):
- Log since the 12:52 launch: one `Recording (dictate)` at 16:57:39 and no
  "Captured" — the recording never stopped; on quit it had hit the 300 s cap.
  The app was not hung (worker idle, hook thread alive).
- Cause: item 21 partials. With a GPU, `partials="auto"` sent each interim
  transcript to Airoot via `show_transcript(text, "Listening")` every 0.8 s.
  The Airoot EXE (built 09-27 16:31 = `9e71f88` source) treats ANY
  `{"event":"transcript"}` as completion → `finish_transcribing()` → fades
  out. So ~1 s into dictation the overlay vanished as if done; the user's next
  Ctrl+Alt+Space (meant as "start") stopped the still-running take and pasted
  whatever it caught. `_show_question` (confirmations) did the same.
- Ruled out: duplicate instances (only one running), my held-key check from
  `dcfd87e` (synthetic Ctrl+Alt+F24 through the real hook: GetAsyncKeyState
  reports Ctrl/Alt held, binding fires with and without the check).

Fix `3231d38`: interim text goes to the orb only, never Airoot; partials
don't run at all when the orb is disabled (shipped config — so none on this
machine); interim decode limited to the last `PARTIAL_WINDOW = 15` s
(previously re-decoded the whole take each pass); confirmation questions no
longer sent to Airoot. Tests updated (465 OK).

Live check: quit the stale instance with synthesized Ctrl+Alt+Shift+Q
(recording discarded, nothing pasted), relaunched via run.bat (ready
17:05:08), synthesized Ctrl+Alt+Space → still recording after 8 s, no
"partials" thread, Airoot running; quit again (discarded) and relaunched —
**app running since 17:05:53** (pythonw 18756/60812, Airoot 60136/12392).
Mic in use: `[3] Microphone (Realtek(R) Audio)` (jack mic now present).
Stop-by-second-press not exercised live (would paste into the focused
window); toggle stop path is unchanged and unit-tested.
Also installed `py-spy` 0.4.2 in the venv for thread dumps.
