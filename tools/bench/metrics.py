"""Scoring for the speech benchmarks (WS6). Stdlib only, so the app's test
suite can check it and every engine is scored by the same code.

- normalize: lowercase, no punctuation, a few spelling aliases, so engines are
  not penalised for "Okay"/"ok", "Git Hub"/"GitHub" or "7"/"seven".
- wer: corpus word error rate (word-level Levenshtein, like jiwer).
- command_ok: a command only counts when every word matches after
  normalisation, because the local grammar router needs exact words.
- looped: the repetition loop ("...and then write it up and then...") or a
  long invented tail ("... thank you for watching").
"""

from __future__ import annotations

import re
import statistics

_NUMBERS = {str(i): w for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())}
_ALIASES = [  # (regex on normalised text, replacement)
    (r"\bokay\b", "ok"),
    (r"\bo k\b", "ok"),
    (r"\bgit hub\b", "github"),
    (r"\blinked in\b", "linkedin"),
    (r"\bvscode\b", "vs code"),
    (r"\bvisual studio code\b", "vs code"),
    (r"\bcode x\b", "codex"),
    (r"\bnever mind\b", "nevermind"),
]
SPEECH_KINDS = ("wake", "command", "dictation")
COMMAND_KINDS = ("wake", "command")


def normalize(text: str) -> str:
    text = (text or "").lower().replace("\u2019", "'")
    text = re.sub(r"[-_/\u2013\u2014]", " ", text)
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    words = [w.strip("'") for w in text.split()]
    text = " ".join(_NUMBERS.get(w, w) for w in words if w)
    for pattern, replacement in _ALIASES:
        text = re.sub(pattern, replacement, text)
    return text


def edits(ref: str, hyp: str) -> tuple[int, int]:
    """(word edits, reference words) after normalisation."""
    r, h = normalize(ref).split(), normalize(hyp).split()
    previous = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        current = [i]
        for j, hw in enumerate(h, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (rw != hw)))
        previous = current
    return previous[-1], len(r)


def wer(pairs: list[tuple[str, str]]) -> float | None:
    total_edits = total_words = 0
    for ref, hyp in pairs:
        e, n = edits(ref, hyp)
        total_edits, total_words = total_edits + e, total_words + n
    return total_edits / total_words if total_words else None


def command_ok(ref: str, hyp: str) -> bool:
    return normalize(ref) == normalize(hyp)


def looped(ref: str, hyp: str) -> bool:
    words = normalize(hyp).split()
    ref_words = normalize(ref).split()
    for n in (2, 3, 4, 5):
        grams = [tuple(words[i:i + n]) for i in range(len(words) - n + 1)]
        for gram in set(grams):
            if grams.count(gram) >= 3 and ref_words and _count(ref_words, gram) < 3:
                return True
    return len(words) >= len(ref_words) + 4 and len(words) > 1.5 * max(1, len(ref_words))


def _count(words: list[str], gram: tuple[str, ...]) -> int:
    n = len(gram)
    return sum(1 for i in range(len(words) - n + 1) if tuple(words[i:i + n]) == gram)


def summarize(rows: list[dict]) -> dict:
    """Aggregate one engine's rows: {kind, text, hyp, seconds, decode_s}."""
    speech = [r for r in rows if r["kind"] in SPEECH_KINDS]
    commands = [r for r in rows if r["kind"] in COMMAND_KINDS]
    quiet = [r for r in rows if r["kind"] not in SPEECH_KINDS]
    latencies = [float(r["decode_s"]) for r in speech]
    audio = sum(float(r["seconds"]) for r in speech)
    p90 = sorted(latencies)[max(0, int(round(0.9 * len(latencies))) - 1)] if latencies else None
    return {
        "n_speech": len(speech),
        "n_quiet": len(quiet),
        "wer": wer([(r["text"], r["hyp"]) for r in speech]),
        "cmd_acc": (sum(command_ok(r["text"], r["hyp"]) for r in commands) / len(commands)) if commands else None,
        "phantom_rate": (sum(bool(normalize(r["hyp"])) for r in quiet) / len(quiet)) if quiet else None,
        "loops": sum(looped(r["text"], r["hyp"]) for r in speech),
        "lat_mean": statistics.fmean(latencies) if latencies else None,
        "lat_p90": p90,
        "rtf": (sum(latencies) / audio) if audio else None,
    }
