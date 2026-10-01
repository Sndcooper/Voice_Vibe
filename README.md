# Voice Vibe - transcriber

Press **Ctrl+Alt+Space**. It starts listening. Say something, pause, and it is
transcribed on your machine and typed at your cursor. Press **Ctrl+Alt+Space**
again to stop.

That is the whole app: local Whisper transcription plus the animated overlay.
No wake word, no voice commands, no assistant, no hub.

## How it behaves

| You do | It does |
|---|---|
| Tap `Ctrl+Alt+Space` | Opens the mic. The Airoot logo appears and dances with your voice. |
| Speak, then pause (1.5 s) | The logo gathers into a "Transcribing..." pill, then the sentence is pasted into the focused field. |
| Keep talking | Each pause types the next sentence. The mic stays open. |
| Tap `Ctrl+Alt+Space` again | Stops listening. A sentence cut off mid-way is still transcribed and typed. |
| `Ctrl+Alt+Shift+Q` or tray > Quit | Quits. |

Transcription is local (faster-whisper; NVIDIA Parakeet on CPU-only machines if
installed). No account, API key or network is needed after the first model
download. While listening, **everything you say is typed into whatever has
focus**, so tap the hotkey again before you talk to someone else.

Basic punctuation and capitals are applied. Set `raw_dictation = true` under
`[output]` for Whisper's exact words.

The dancing overlay assets, Whisper/Parakeet engines and speech-segmentation
tuning match `Voice_Vibe`. Vocabulary hotwords and per-app decoder hints are
configured under `[vocab]`; transcripts that only echo a decoder hint are
discarded. The desktop launcher prioritizes this project's `src` even when
using the shared environment installed for the full app.

## Quick start (Windows, Python 3.10-3.12)

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1      # add -Cuda for NVIDIA GPUs
.\run.bat --check                                         # environment report
.\run.bat                                                 # starts in the background
```

`setup.ps1` needs [uv](https://docs.astral.sh/uv/). Without it:
`python -m venv .venv`, then `.venv\Scripts\pip install -e .`.

`run.bat --console` keeps a window open for debugging. Diagnostics:
`--list-devices`, `--mic-test`, `--test` (record + transcribe, nothing typed),
`--key-test` (what a key is called, for rebinding).

`tools/verify_transcription.py` scores the existing local voice benchmark
recordings and runs the installed Laya model on reference/transcript pairs.
Laya checks meaning only; the report also records word error rate and controls.
Results stay in `%LOCALAPPDATA%/VoiceVibe/verification/transcriber-laya.json`.

## The animations

- **Airoot logo** (default): `assets/airoot_overlay.py`, a small PySide6 app the
  main process starts and drives over a local UDP port. It never takes keyboard
  focus. If `dist/AirootVoiceOverlay.exe` exists it is used instead (build it
  from `assets/AirootVoiceOverlay.spec` with PyInstaller).
- **Orb**: a dependency-free glowing orb, used automatically if Airoot cannot
  start. Set `[overlay].enabled = true` to show it too.
- **Tray icon**: grey off, red listening, amber transcribing.

## Configuration

Everything is in [config.toml](config.toml) and every key is optional. The
useful ones: `[hotkeys].toggle`, `[continuous].silence_duration` (how long a
pause ends a sentence), `[model].name` / `device`, `[output].mode`
(`paste` or `type`), `[audio].input_device`, `[airoot].enabled`.

## Layout

```
src/voicevibe/
  app.py         hotkey -> mic -> Whisper -> text, and the state shown on screen
  audio.py       microphone capture and pause detection
  transcriber.py faster-whisper wrapper     engines/  optional Parakeet engine
  inserter.py    paste / type into the focused field
  polish.py      capitals, spacing, punctuation
  airoot.py      drives the Airoot overlay    overlay.py  built-in orb
  feedback.py    tray icon and beeps          hotkey.py   global hotkeys
assets/          the Airoot overlay app and its sprites
```

## Troubleshooting

- **Nothing is typed**: run `run.bat --mic-test`. Silence means Windows mic
  privacy is blocking desktop apps, or the wrong input is selected.
- **Hotkey does nothing**: another program owns `Ctrl+Alt+Space` (including the
  full Voice Vibe app, if it is running). Quit it or change `[hotkeys].toggle`.
- **Pastes the old clipboard in a slow app**: raise `[output].restore_delay`.
- **Log**: `%LOCALAPPDATA%\VoiceVibe\logs\voicevibe.log`.
