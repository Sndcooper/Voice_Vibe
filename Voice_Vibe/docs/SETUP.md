# Install and set up a fork

## Requirements and clone

Use Windows 10/11, Git, Python 3.10–3.12 (3.11 recommended), a microphone, and
[uv](https://docs.astral.sh/uv/getting-started/installation/). Internet access
is needed for dependencies and first-use model downloads. A GPU is optional.

```powershell
git clone --branch voicevibe-automation https://github.com/Masqiller/Voice_Vibe.git
Set-Location Voice_Vibe
```

For your own fork, substitute your fork URL. You need only this repository;
no original `Repos` or `venvs` directories are required for core use.

## Installation profiles

```powershell
# Recommended: dictation, screen reading, hub, reports, web readers and panel.
powershell -ExecutionPolicy Bypass -File .\setup.ps1

# Smallest installation: core dictation.
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Profile standard

# Add local Laya routing (larger Torch/model downloads).
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Profile assistant

# Optional NVIDIA recognition DLLs and Telegram dependencies.
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Profile assistant -Cuda -Bot
```

The script creates `.venv` inside the clone. It does not configure account
credentials, browser extensions, autostart or optional external services.
Core installation falls back gracefully when hub dependencies are missing.
Without the brain extra, the hub uses its fallback router; advanced local
model decisions require the assistant profile. The CUDA extra supplies speech
recognition DLLs; it does not select a CUDA Torch distribution for Laya.

You can also use Python/pip directly without the script:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-hub.txt
# Choose requirements.txt or requirements-assistant.txt for another profile.
```

Other extras can be installed independently:

```powershell
uv pip install --python .venv\Scripts\python.exe -e ".[cuda]"
uv pip install --python .venv\Scripts\python.exe -e ".[parakeet]"
uv pip install --python .venv\Scripts\python.exe -e ".[wakeword]"
uv pip install --python .venv\Scripts\python.exe -e ".[tts]"
```

## Verify, configure and run

```powershell
.\run.bat --check
.\run.bat --list-devices
.\run.bat
.\run.bat --ui
# Foreground logging:
.\run.bat --console -v
# Check optional integrations:
.\.venv\Scripts\python.exe -m vvhub doctor
```

Edit `config.toml` and restart after changing it. Select your microphone and
model settings; avoid Stereo Mix for dictation. Default hotkeys are
Ctrl+Alt+Space for dictation, Ctrl+Alt+W for voice control, and
Ctrl+Alt+Shift+Q to quit. The first model use downloads weights. The control
panel requires the ui extra and the Microsoft Edge WebView2 runtime.
The original sibling `..\venvs\voicevibe` layout remains supported when no
local `.venv` exists. Missing optional integrations in `doctor` are expected
until you install and configure them.

## Optional account integrations

The core does not need account credentials. FreeLLMAPI/LLM answers, Notion,
Telegram and browser services need their own installation or login.

- **FreeLLMAPI:** install the desktop service from the URL in `THIRD_PARTY.lock`.
  The current hub expects a local endpoint at `127.0.0.1:3001`; configure the
  service accordingly and set up your provider. Store its key with
  `.\run.bat --set-key freellmapi`.
- **Notion:** share the target page with your integration; store its token
  with `.\run.bat --set-key notion` and configure the page through the panel.
- **GitHub:** install `gh` and Git, then use `gh auth login` for your account.
- **Telegram:** install the bot extra, create your bot with BotFather, then:

```powershell
.\.venv\Scripts\python.exe -m vvbot set-token
.\.venv\Scripts\python.exe -m vvbot pair
# Send the displayed /pair CODE to your bot from your phone, then run:
.\.venv\Scripts\python.exe -m vvbot run
```

Run the hub before expecting Telegram commands or approval cards to work.
`src\vvbot\run.bat` also supports the local `.venv`. Tokens and pairing belong
to each user; never copy another developer's credential store or hub token.

## Optional browser and research tools

Node.js and OpenCLI are separate from Python dependencies. The pinned upstream
versions and commits are in `THIRD_PARTY.lock`. A local tool prefix works:

```powershell
# Keep external tool environments inside the clone.
$env:VVHUB_WORKSPACE = Join-Path $PWD '.tools'
npm install --prefix .tools\venvs\node @jackwener/opencli@1.8.8
& .tools\venvs\node\node_modules\.bin\opencli.cmd plugin install ('file://' + (Join-Path $PWD 'integrations\opencli-plugins\voicevibe'))
```

Install and connect the matching Browser Bridge extension in Edge from the
OpenCLI upstream release. Log in to the sites you want to use. Keep
`VVHUB_WORKSPACE` in the environment used to start the hub (set it again in
new shells, or persist it for your user). This tells the adapters and doctor
where to find optional tool environments. `VVHUB_OPENCLI_MAIN` is also available
if you need to point directly at a different OpenCLI main.js.
Browser/social selectors still need live validation on your account.

For Windows-MCP, the current driver expects a separate Python 3.13 environment
under the tool workspace (it cannot share Voice Vibe's Python 3.11 environment):

```powershell
$env:VVHUB_WORKSPACE = Join-Path $PWD '.tools'
uv venv --python 3.13 .tools\venvs\windows-mcp
uv pip install --python .tools\venvs\windows-mcp\Scripts\python.exe windows-mcp==0.8.5
```

Create `.tools/venvs/windows-mcp/config.toml` with the exclusions expected by
doctor (the driver also supplies them to its subprocess):

```toml
[tools]
exclude = ["PowerShell", "Registry", "FileSystem"]
```

Research works with installed readers; optionally install the pinned
Agent-Reach source (do not substitute the unrelated old PyPI package):

```powershell
uv pip install --python .venv\Scripts\python.exe "git+https://github.com/Panniantong/Agent-Reach.git@a19a171fa980a0785849596492e0af4db800c82f"
```

Reference repositories in `THIRD_PARTY.lock` do not all need cloning. The shell
catalog is included. A CPU ONNX export for Laya is optional advanced setup;
the assistant profile can use Torch without copying the original developer's
model export.

## Optional Airoot overlay

The built-in orb works without the separate Airoot executable. To build it:

```powershell
uv pip install --python .venv\Scripts\python.exe -e ".[overlay]"
.\.venv\Scripts\python.exe -m PyInstaller assets\AirootVoiceOverlay.spec
```

The checked-in config points to `dist/AirootVoiceOverlay.exe`. Run launchers
from the repository root; set `[airoot].exe` to an absolute path if needed.
The build spec retains the Qt ICU DLL exclusions. Generated executables are
ignored by Git. To turn it off, set `[airoot].enabled = false`.

## Troubleshooting and development

Check logs under `%LOCALAPPDATA%\VoiceVibe\logs` and consult the main README.
Use `--check` for hardware diagnostics and `vvhub doctor` for integration
status. Tests cover logic with fakes; they do not prove microphone quality,
site selectors or account access. See [CONTRIBUTING.md](../CONTRIBUTING.md).
