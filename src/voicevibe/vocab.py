"""Words Whisper should expect: fixed hotwords, plus a hint for the front app.

Two levers, both free at runtime:

  hotwords        faster-whisper's `hotwords`: names and jargon it would
                  otherwise spell phonetically ("PyTorch", "Kubernetes").
  prompt hints    a short passage in the style of what is dictated into the
                  front app, added to initial_prompt. Whisper continues the
                  style of its prompt, so a code-flavoured hint in VS Code
                  makes "async await" come out as code words, and a
                  conversational one in a chat app keeps normal prose.

The hint is chosen per utterance from the foreground process, so switching
from the editor to the chat window changes it immediately. It is *not* used
while a session is waiting for its wake word: that prompt carries only the
wake phrases (see app._decoder_prompt).

    [vocab]
    hotwords = ["PyTorch", "Voice Vibe", "Kubernetes"]
    [vocab.prompts]
    "code.exe" = "Python, FastAPI, pytest, async def, pull request."
    "claude.exe" = ""          # empty disables the built-in hint
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

_WORDS = re.compile(r"[a-z0-9']+")


def echoes_prompt(text: str, prompt: str | None, min_words: int = 4) -> bool:
    """Whether `text` is just the decoder prompt read back.

    Given silence, Whisper continues its prompt instead of transcribing:
    with the VS Code hint it typed "Open a pull request after the git commit
    commit commit ...". Counted after collapsing repeated words, the
    transcript has to be almost entirely one run copied from the prompt, so
    a real sentence that merely shares a phrase with it is kept.
    """
    if not text or not prompt:
        return False
    words = _WORDS.findall(text.lower())
    collapsed = [w for i, w in enumerate(words) if i == 0 or w != words[i - 1]]
    if len(collapsed) < min_words:
        return False
    hint = _WORDS.findall(prompt.lower())
    run = SequenceMatcher(None, collapsed, hint, autojunk=False).find_longest_match(
        0, len(collapsed), 0, len(hint)
    ).size
    return run >= min_words and run >= 0.9 * len(collapsed)

_EDITOR = (
    "Refactor the async function, return the JSON, then run pytest and npm "
    "install. Open a pull request after the git commit; check the API, the "
    "README, TypeScript types and the Python class."
)
_TERMINAL = (
    "Run git status, git commit, cd into the folder, pip install, npm run "
    "build, ls, grep, and python main.py."
)
_CHAT = (
    "Hi, can you explain this and summarize it? Please rewrite the paragraph, "
    "list the steps, and suggest a better approach."
)

BUILTIN_PROMPTS: dict[str, str] = {
    **{exe: _EDITOR for exe in (
        "code.exe", "cursor.exe", "windsurf.exe", "zed.exe", "devenv.exe",
        "pycharm64.exe", "idea64.exe", "webstorm64.exe", "sublime_text.exe",
        "notepad++.exe",
    )},
    **{exe: _TERMINAL for exe in (
        "windowsterminal.exe", "wt.exe", "powershell.exe", "pwsh.exe", "cmd.exe",
    )},
    **{exe: _CHAT for exe in ("claude.exe", "chatgpt.exe")},
}


class Vocabulary:
    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        cfg = cfg or {}
        words = cfg.get("hotwords", []) or []
        if isinstance(words, str):
            words = [words]
        self.hotwords = [str(w).strip() for w in words if str(w).strip()]
        user = {str(k).strip().lower(): str(v or "").strip()
                for k, v in (cfg.get("prompts") or {}).items()}
        self.prompts = {**BUILTIN_PROMPTS, **user} if cfg.get("app_prompts", True) else user

    def hotwords_text(self) -> str | None:
        """The `hotwords` string for faster-whisper, or None if there are none."""
        return ", ".join(dict.fromkeys(self.hotwords)) or None

    def hint(self, process: str) -> str:
        """The prompt hint for a process name ("" when there is none)."""
        return self.prompts.get((process or "").lower(), "")
