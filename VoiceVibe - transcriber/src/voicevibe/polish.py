"""Turn a raw transcript into text someone would actually have typed.

Whisper returns reasonable words but inconsistent presentation: a short
utterance often arrives with no closing punctuation, a lowercase first word, a
bare "i", and any punctuation the speaker actually said out loud left as the
word ("add a comma" -> "comma"). Fixing that afterwards is cheap and
deterministic, which matters here: no model, no measurable memory, and the same
result every time for the same input.

Two passes, in order:

  spoken marks   "comma" -> ","     said out loud, so they become real marks
  presentation   capitals, spacing, a closing stop

Everything is conservative. A rule that would fire inside ordinary speech is
not worth the words it saves, so each one needs an explicit cue, and anything
unrecognised is left exactly as dictated.
"""

from __future__ import annotations

import re

# Punctuation people dictate by name. Matched only as whole words, and only
# where a mark can legally go, so "comma" in "comma separated" survives.
_SPOKEN_MARKS = (
    (r"\bcomma\b", ","),
    (r"\b(?:full stop|period)\b", "."),
    (r"\bquestion mark\b", "?"),
    (r"\bexclamation (?:mark|point)\b", "!"),
    (r"\bsemicolon\b", ";"),
    (r"\bcolon\b", ":"),
    (r"\b(?:dash|hyphen)\b", "-"),
    (r"\bellipsis\b", "..."),
    (r"\bopen paren(?:thesis)?\b", "("),
    (r"\bclose paren(?:thesis)?\b", ")"),
)

_MARK_NAMES = (
    r"comma|full stop|period|question mark|exclamation (?:mark|point)"
    r"|semicolon|colon|dash|hyphen|ellipsis|open paren(?:thesis)?"
    r"|close paren(?:thesis)?"
)

# Only a trailing run of dictated marks is substituted. "Add a comma" mid
# sentence is something people genuinely say ("I will add a comma here"); at
# the end of an utterance it is an instruction.
_MARK_CUE = re.compile(
    rf"\s*\b(?:add|insert|put)\s+(?:an?\s+)?(?:{_MARK_NAMES})\b"
    rf"(?:\s*(?:and\s+)?(?:add|insert|put)\s+(?:an?\s+)?(?:{_MARK_NAMES})\b)*"
    rf"\s*[.!?]*\s*$",
    re.IGNORECASE,
)

# Stands in for a dot inside an abbreviation while splitting sentences.
_DOT = chr(0xF8FF)

_SENTENCE_END = re.compile(r"([.!?])(\s+|$)")
_ABBREVIATIONS = ("e.g.", "i.e.", "etc.", "vs.", "mr.", "mrs.", "dr.", "no.")

# Words that make a sentence a question even without a spoken question mark.
_QUESTION_OPENERS = (
    "who", "what", "when", "where", "why", "how", "which", "whose",
    "is", "are", "was", "were", "do", "does", "did", "can", "could",
    "should", "would", "will", "shall", "have", "has", "am",
)

_ALWAYS_CAPITAL = {"i", "i'm", "i'll", "i've", "i'd"}


def _apply_spoken_marks(text: str) -> str:
    """Replace a trailing run of dictated punctuation names with real marks."""
    match = _MARK_CUE.search(text)
    # Nothing before the cue means the whole utterance was punctuation names,
    # which is far more likely to be a mishearing than an instruction.
    if not match or not text[: match.start()].strip():
        return text

    marks = ""
    for spoken in re.finditer(rf"\b(?:{_MARK_NAMES})\b", match.group(0), re.IGNORECASE):
        word = spoken.group(0).lower()
        for pattern, mark in _SPOKEN_MARKS:
            if re.fullmatch(pattern, word, re.IGNORECASE):
                marks += mark
                break
    return text[: match.start()].rstrip() + marks


def _fix_spacing(text: str) -> str:
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)          # no space before a mark
    text = re.sub(r"([,;:])(?=\S)", r"\1 ", text)          # one space after
    # A dot between single letters is an abbreviation, not a sentence break.
    text = re.sub(r"(?<![A-Za-z])([.!?])(?=[A-Za-z])", r"\1 ", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _capitalise(text: str) -> str:
    """Upper-case sentence starts and the standalone pronoun I."""
    if not text:
        return text

    def upper_first(chunk: str) -> str:
        for index, char in enumerate(chunk):
            if char.isalpha():
                return chunk[:index] + char.upper() + chunk[index + 1 :]
            if char not in " \t\"'([":
                break
        return chunk

    # "e.g." ends in a period without ending a sentence, so hide those dots
    # from the splitter and restore them afterwards.
    masked = text
    for abbr in _ABBREVIATIONS:
        masked = re.sub(
            re.escape(abbr), abbr.replace(".", "\uf8ff"), masked, flags=re.IGNORECASE
        )

    pieces, last = [], 0
    for match in _SENTENCE_END.finditer(masked):
        pieces.append(masked[last : match.end()])
        last = match.end()
    pieces.append(masked[last:])
    text = "".join(upper_first(piece) for piece in pieces).replace("\uf8ff", ".")

    return re.sub(
        r"\b(i|i'm|i'll|i've|i'd)\b",
        lambda m: m.group(1)[0].upper() + m.group(1)[1:],
        text,
    )


def _terminate(text: str) -> str:
    """Give a sentence a closing mark, choosing ? when it reads as a question."""
    if not text or text[-1] in ".!?:;,-—" or text.endswith("..."):
        return text
    last = text.split(".")[-1].split("!")[-1].split("?")[-1].strip()
    opener = last.split()[0].lower().rstrip("'") if last.split() else ""
    return text + ("?" if opener in _QUESTION_OPENERS else ".")


def polish(text: str, terminate: bool = True, spoken_marks: bool = True) -> str:
    """Clean up one utterance. Safe to call on text that needs nothing."""
    if not text or not text.strip():
        return ""
    if spoken_marks:
        text = _apply_spoken_marks(text)
    text = _fix_spacing(text)
    text = _capitalise(text)
    if terminate:
        text = _terminate(text)
    return text
