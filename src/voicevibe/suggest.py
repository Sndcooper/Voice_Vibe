"""Propose [[replacements]] from what you corrected. Offline, read-only.

    python -m voicevibe --suggest-replacements [--min-count 2]

Scans the history files and counts word swaps that look like corrections of
a misrecognition, strongest evidence first:

  replace edit     "replace pie torch with PyTorch" -- the fix, verbatim
  scratch & retry  "scratch that", then the same sentence again within a
                   minute: whatever words changed are the fix
  quick retry      the same sentence dictated twice within 30 s into the same
                   window, no edit between (weaker: half weight)

Nothing is written anywhere. The output is TOML to paste into config.toml
after reading it; [output].apply_replacements = true then applies it.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

_WORD = re.compile(r"[\w'-]+")
# Swapping one of these for another is grammar, not a misrecognised name.
_STOPWORDS = frozenset(
    "a an the to too two of in on at for and or but is are was were be it its "
    "this that these those i you he she we they me my your our their".split()
)
WEIGHTS = {"replace edit": 1.0, "scratch & retry": 1.0, "quick retry": 0.5}


@dataclass
class Suggestion:
    find: str
    replace: str
    score: float = 0.0
    evidence: dict[str, int] = field(default_factory=dict)

    def toml(self) -> str:
        how = ", ".join(f"{n} {kind}" for kind, n in self.evidence.items())
        return (f"# seen {self.score:g}x ({how})\n[[replacements]]\n"
                f"find = {json.dumps(self.find)}\nreplace = {json.dumps(self.replace)}\n")


def load_history(directory: Path) -> list[dict]:
    """Every record from every day's file, oldest first. Bad lines are skipped."""
    records: list[dict] = []
    for path in sorted(directory.glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def _when(record: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(str(record.get("ts", "")))
    except ValueError:
        return None


def _words(text: str) -> list[str]:
    return _WORD.findall(text or "")


def swaps(before: str, after: str, max_words: int = 3) -> list[tuple[str, str]]:
    """Short word runs that changed between two takes of the same sentence.

    Only when the takes are mostly the same (a retry, not a new sentence),
    and only small substitutions -- a whole rephrased clause is not a
    misheard word.
    """
    a, b = _words(before), _words(after)
    lower_a, lower_b = [w.lower() for w in a], [w.lower() for w in b]
    matcher = SequenceMatcher(None, lower_a, lower_b, autojunk=False)
    if matcher.ratio() < 0.5:
        return []
    out = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op != "replace" or i2 - i1 > max_words or j2 - j1 > max_words:
            continue
        find, replace = " ".join(a[i1:i2]), " ".join(b[j1:j2])
        if find.lower() == replace.lower():
            continue  # a capitalisation change is polish's job
        if all(w in _STOPWORDS for w in lower_a[i1:i2]):
            continue
        out.append((find, replace))
    return out


def _evidence(records: list[dict]) -> Iterable[tuple[str, str, str]]:
    """(find, replace, kind) for every correction-shaped event."""
    for index, record in enumerate(records):
        if record.get("action") == "edit" and record.get("edit") == "replace":
            find, replace = str(record.get("find", "")), str(record.get("replace", ""))
            if find and replace and find.lower() != replace.lower():
                yield find, replace, "replace edit"
            continue
        if record.get("action") != "dictate" or index + 1 >= len(records):
            continue
        nxt = records[index + 1]
        then, later = _when(record), _when(nxt)
        if then is None or later is None:
            continue
        # scratch & retry: dictate, "scratch that", dictate again
        if (nxt.get("action") == "edit" and nxt.get("edit") == "undo"
                and index + 2 < len(records) and records[index + 2].get("action") == "dictate"):
            retry = records[index + 2]
            when = _when(retry)
            if when is not None and (when - then).total_seconds() <= 60:
                for find, replace in swaps(str(record.get("heard", "")), str(retry.get("heard", ""))):
                    yield find, replace, "scratch & retry"
            continue
        # quick retry: the same thing again, straight away, into the same window
        if (nxt.get("action") == "dictate" and (later - then).total_seconds() <= 30
                and nxt.get("target") == record.get("target")):
            for find, replace in swaps(str(record.get("heard", "")), str(nxt.get("heard", ""))):
                yield find, replace, "quick retry"


def suggest(records: list[dict], existing: Iterable[dict] = (),
            min_count: float = 2) -> list[Suggestion]:
    """Corrections seen at least `min_count` times (weighted), best first."""
    known = {str(r.get("find", "")).strip().lower() for r in existing}
    found: dict[tuple[str, str], Suggestion] = {}
    for find, replace, kind in _evidence(records):
        key = (find.lower(), replace)
        if key[0] in known:
            continue
        item = found.setdefault(key, Suggestion(find.lower(), replace))
        item.score += WEIGHTS[kind]
        item.evidence[kind] = item.evidence.get(kind, 0) + 1
    # One misheard phrase fixed two different ways: keep the more common fix.
    best: dict[str, Suggestion] = defaultdict(lambda: Suggestion("", "", -1))
    for item in found.values():
        if item.score > best[item.find].score:
            best[item.find] = item
    ranked = sorted((s for s in best.values() if s.score >= min_count),
                    key=lambda s: (-s.score, s.find))
    return ranked


def report(directory: Path, existing: Iterable[dict], min_count: float = 2) -> str:
    records = load_history(directory)
    suggestions = suggest(records, existing, min_count)
    head = (f"# {len(records)} history records in {directory}\n"
            f"# {len(suggestions)} suggested replacement(s), seen at least {min_count:g} times.\n")
    if not suggestions:
        return head + ("# Nothing yet. Corrections are learned from \"replace X with Y\"\n"
                       "# and \"scratch that\" edits ([output].spoken_edits = true) and\n"
                       "# from sentences you dictate twice in a row.\n")
    body = "\n".join(s.toml() for s in suggestions)
    return (head + "# Review before pasting into config.toml, then set\n"
            "# [output].apply_replacements = true.\n\n" + body)
