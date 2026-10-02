"""Spoken words -> shell text. Stdlib only: Voice Vibe imports this too.

    spoken_to_shell("python app dot py")      -> "python app.py"
    spoken_to_shell("git log dash dash oneline") -> "git log --oneline"
    spoken_to_shell("cd dot dot")             -> "cd .."
    shell_text("Git status.")                  -> "git status"
    strip_submit("list the files and press enter") -> "list the files"
"""

from __future__ import annotations

import re

_SYMBOLS = (
    (r"\b(?:dash dash|double dash)\b", " --"),
    (r"\b(?:dash|hyphen)\b", " -"),
    (r"\bdot dot\b", " .."),
    (r"\bdot\b", "."),
    (r"\bback ?slash\b", "\\"),
    (r"\b(?:forward )?slash\b", " /"),
    (r"\bcolon\b", ":"),
    (r"\bunderscore\b", "_"),
    (r"\bpipe\b", " |"),
    (r"\b(?:star|asterisk)\b", "*"),
    (r"\btilde\b", "~"),
    (r"\bequals\b", "="),
    (r"\bat sign\b", "@"),
)

# A spoken submit at the very end: "..., press enter", "... and run it".
SUBMIT_TAIL = re.compile(
    r"(?:\s*,?\s*(?:(?:and|then|and then)\s+)?(?:press|hit|push)\s+(?:the\s+)?(?:enter|return)"
    r"(?:\s+key)?|\s*,?\s*(?:and|then|and then)\s+(?:enter|return|run it|run that|execute it))"
    r"+\s*[.!?]*\s*$",
    re.IGNORECASE,
)


def spoken_to_shell(text: str) -> str:
    """Spoken symbol names to the symbols, joined the way commands are written."""
    out = f" {text} "
    for pattern, symbol in _SYMBOLS:
        out = re.sub(pattern, lambda _m, s=symbol: s, out, flags=re.IGNORECASE)
    out = re.sub(r"(\w)\s*\.\s*(\w)", r"\1.\2", out)          # app . py -> app.py
    out = re.sub(r"(^|\s)(--?|/)\s+(?=\S)", r"\1\2", out)      # - n -> -n, / a -> /a
    out = re.sub(r"\s*\\\s*", r"\\", out)                       # c:\ users -> c:\users
    out = re.sub(r"(\w)\s*:\s*(?=\\)", r"\1:", out)             # c : \ -> c:\
    out = re.sub(r"\s*_\s*", "_", out)
    return " ".join(out.split())


def shell_text(text: str) -> str:
    """Dictation as a shell expects it: no sentence polish, no final period,
    command word in lower case ("Git status." -> "git status")."""
    out = spoken_to_shell(text.strip()).strip().rstrip(",!?;:")
    if out.endswith(".") and not out.endswith(".."):
        out = out[:-1]          # "Git status." -> "git status"; "cd .." stays
    words = out.split(" ", 1)
    if words and words[0].isalpha():
        words[0] = words[0].lower()
    return " ".join(words)


def strip_submit(text: str) -> str:
    return SUBMIT_TAIL.sub("", text).strip()
