"""Turn a raw transcript into text someone would actually have typed.

Whisper returns reasonable words but inconsistent presentation: a short
utterance often arrives with no closing punctuation, a lowercase first word, a
bare "i", and any punctuation the speaker actually said out loud left as the
word ("add a comma" -> "comma"). Fixing that afterwards is cheap and
deterministic, which matters here: no model, no measurable memory, and the same
result every time for the same input.

Two passes, in order:

  spoken marks   "comma" -> ","     said out loud, so they become real marks
  editing        "scratch that"     acts on what was already written
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


# --------------------------------------------------------------- editing
# Spoken edits that rewrite what was just dictated rather than adding to it.
# Each needs an unambiguous cue: a rule that fires inside ordinary speech
# costs more than it saves.
_EDITS = (
    (re.compile(r"^(?:scratch|strike|delete|forget)\s+that\b[.!?]*$", re.I), "undo"),
    (re.compile(r"^(?:cap|capitalise|capitalize)\s+that\b[.!?]*$", re.I), "capitalise"),
    (re.compile(r"^(?:all\s+caps|upper\s?case)\s+that\b[.!?]*$", re.I), "upper"),
    (re.compile(r"^lower\s?case\s+that\b[.!?]*$", re.I), "lower"),
    (re.compile(r"^new\s+paragraph\b[.!?]*$", re.I), "paragraph"),
)

_COUNT_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "seven": 7, "eight": 8, "nine": 9, "ten": 10, "a": 1, "the": 1}
# "delete the last word", "remove last three words"
_DELETE_WORDS = re.compile(
    r"^(?:delete|remove|scratch|erase)\s+(?:the\s+)?last\s+(?:(\w+)\s+)?words?[.!?]*$", re.I
)
# "replace Tuesday with Wednesday". Not "change X to Y": people dictate that
# ("change the meeting to Friday"). Even this form can be dictation, so it is
# only an edit when X is in the previous utterance -- see edit_applies.
_REPLACE = re.compile(r"^replace\s+(.+?)\s+with\s+(.+?)[.!?]*$", re.I)


def parse_edit(text: str) -> tuple[str, dict] | None:
    """The spoken edit in `text` with its arguments, or None for dictation.

    Whole utterance only, like detect_edit.
    """
    stripped = text.strip()
    for pattern, name in _EDITS:
        if pattern.match(stripped):
            return name, {}
    match = _DELETE_WORDS.match(stripped)
    if match:
        word = (match.group(1) or "1").lower()
        count = int(word) if word.isdigit() else _COUNT_WORDS.get(word)
        if count:
            return "delete_words", {"count": min(count, 50)}
    match = _REPLACE.match(stripped)
    if match:
        return "replace", {"find": match.group(1), "replace": match.group(2)}
    return None


def detect_edit(text: str) -> str | None:
    """Name the spoken edit in `text`, or None if it is ordinary dictation.

    Matched against the whole utterance only. "Scratch that" on its own is an
    instruction; the same words inside a sentence are not.
    """
    edit = parse_edit(text)
    return edit[0] if edit else None


def _delete_words(previous: str, count: int) -> str:
    """`previous` without its last `count` words (punctuation goes with them)."""
    trailing = previous[len(previous.rstrip()):]
    words = previous.rstrip().split(" ")
    kept = " ".join(words[:-count]) if count < len(words) else ""
    return (kept + " ") if kept and trailing else kept


def _replace_last(previous: str, find: str, replacement: str) -> str | None:
    """Replace the last whole-word occurrence of `find`, or None if absent."""
    matches = list(re.finditer(rf"(?<!\w){re.escape(find)}(?!\w)", previous, re.IGNORECASE))
    if not matches:
        return None
    hit = matches[-1]
    return previous[:hit.start()] + replacement + previous[hit.end():]


def edit_applies(name: str, previous: str, **args: object) -> bool:
    """Whether an edit can act on `previous`. A "replace" whose word is not
    there is ordinary speech that happens to start with "replace"."""
    if name == "replace":
        return _replace_last(previous, str(args.get("find", "")), "") is not None
    return bool(previous)


def apply_edit(name: str, previous: str, **args: object) -> tuple[str, str]:
    """Apply an edit to the previously inserted text.

    Returns (replacement, spoken confirmation). The caller is responsible for
    removing `previous` from the target before inserting the replacement.
    """
    if name == "delete_words":
        count = int(args.get("count", 1) or 1)
        return _delete_words(previous, count), "Deleted."
    if name == "replace":
        find, replacement = str(args.get("find", "")), str(args.get("replace", ""))
        result = _replace_last(previous, find, replacement) if find else None
        if result is None:
            return previous, f"I couldn't find {find}."
        return result, "Replaced."
    if name == "undo":
        return "", "Scratched."
    if name == "paragraph":
        return previous.rstrip() + "\n\n", "New paragraph."
    if name == "capitalise":
        return _capitalise(previous), "Capitalised."
    if name == "upper":
        return previous.upper(), "Upper case."
    if name == "lower":
        return previous.lower(), "Lower case."
    return previous, ""


# ----------------------------------------------------------------- lists
# Spoken enumerations. People dictate lists as one breath -- "first do this,
# second do that" -- and expect real lines back.
_ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

# "point two", "number three", "step four" -- an explicit marker, so the item
# number is taken from it rather than guessed.
_NUMBERED = re.compile(
    r"(?:^|[\s,;.])(?:point|number|step|item)\s+"
    r"(\d+|" + "|".join(_NUMBER_WORDS) + r")\b[\s,.:;-]*",
    re.IGNORECASE,
)

# Bare ordinals only count when they open the phrase: "first, do this".
# Bare ordinals are spoken with or without a pause ("first, do this" and
# "first do this"), so the separator is optional. The guard against ordinary
# speech is instead that the ordinal must not be preceded by an article or
# preposition -- "the first shop", "of all" -- and that a list needs two of them.
_ORDINAL = re.compile(
    r"(?:^|[\s,;.]+)"
    r"(?<!the )(?<!a )(?<!of )(?<!my )(?<!our )(?<!their )(?<!its )(?<!his )"
    r"(" + "|".join(_ORDINAL_WORDS) + r")(?:ly)?\b(?!\s+of\b)[\s,:-]+",
    re.IGNORECASE,
)

_BULLET_CUE = re.compile(r"(?:^|[\s,;.])(?:bullet|dash|next item)\b[\s,.:;-]*", re.I)


def _split_items(text: str, pattern: re.Pattern, numbered: bool):
    """Cut `text` at each marker. Returns None when there is no real list."""
    marks = list(pattern.finditer(text))
    if len(marks) < 2:  # one marker is a turn of phrase, not a list
        return None

    lead = text[: marks[0].start()].strip(" ,;:-")
    items = []
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        body = text[mark.end() : end].strip(" ,;:-")
        if not body:
            return None
        number = None
        if numbered:
            token = mark.group(1).lower()
            number = (
                int(token) if token.isdigit()
                else _NUMBER_WORDS.get(token) or _ORDINAL_WORDS.get(token)
            )
        items.append((number, body))

    # Items must run in order, or the words were not markers at all.
    if numbered:
        seen = [n for n, _ in items if n]
        if seen != list(range(seen[0], seen[0] + len(seen))):
            return None
    return lead, items


def format_list(text: str, bullet: str = "-") -> str | None:
    """Rewrite a dictated enumeration as real lines, or None if it is not one."""
    for pattern, numbered in ((_NUMBERED, True), (_ORDINAL, True), (_BULLET_CUE, False)):
        split = _split_items(text, pattern, numbered)
        if not split:
            continue
        lead, items = split
        lines = []
        for position, (number, body) in enumerate(items, start=1):
            marker = f"{number or position}." if numbered else bullet
            lines.append(f"{marker} {_capitalise(_terminate(body.strip()))}")
        block = "\n".join(lines)
        if lead:
            # A lead-in introduces the list rather than ending a thought, so it
            # takes a colon instead of the full stop _terminate would add.
            if lead[-1] not in ".!?:":
                lead += ":"
            block = f"{_capitalise(lead)}\n{block}"
        return block
    return None
