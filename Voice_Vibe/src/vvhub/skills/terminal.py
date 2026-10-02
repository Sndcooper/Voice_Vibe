"""Spoken request -> one shell command, chosen by Laya from tldr-pages.

Only for a plain shell (cmd, PowerShell) in front: dispatch routes here when
Voice Vibe's context says so. An AI CLI in the terminal (Claude Code, Codex,
Kiro) gets the words typed as a prompt instead, by Voice Vibe itself.

    1. Direct: the words already are a command ("git status", "cd dot dot").
    2. Otherwise BM25 over the catalog's descriptions shortlists a few commands
       and Laya answers "Does the user want to <description>?" for each, in
       one pass; the best must clear a floor and a margin (rule 9).
    3. Placeholders ({{path\\to\\directory}}) are filled from the request.
    4. Dangerous commands are critical: the hub asks aloud first (rule 10).
       With a placeholder left open the command is typed, never entered.

Catalog: src/vvhub/data/shell_catalog.json, built by tools/build_shell_catalog.py
from tldr-pages (CC BY 4.0, see its "source" block and THIRD_PARTY.lock).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import laya_engine, protocol
from ..schemas import Plan, Result
from ..shell_words import shell_text, spoken_to_shell, strip_submit
from .base import Skill

log = logging.getLogger(__name__)

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "shell_catalog.json"

SHORTLIST = 10        # Laya is reliable up to ~20 options; fewer is faster
# Tuned on tools/eval_terminal.py (2026-09-30): BM25 over tldr + the spoken
# aliases found the right command in nearly every case; Laya's zero-shot yes
# was noisy (0.2-0.9 for right answers), so it breaks ties and vetoes, and
# BM25 leads.
YES_FLOOR = 0.1       # Laya's yes for the chosen command (a veto, not a vote)
MARGIN = 0.1          # lead over the best command with a different first word
STRONG_YES = 0.85     # a yes this high needs no margin
TOOL_YES = 0.3        # git/npm/pip... pages when the tool is not named
BM25_WEIGHT = 1.0     # combined = yes + BM25_WEIGHT * bm25 / best bm25
BM25_MIN = 6.0        # below this nothing in the catalog is really about it
FILE_BONUS = 0.4      # a file name in the request -> commands that take a file
RISK_YES = 0.7        # Laya's "does this destroy something" escalates only
KEYWORD_MIN = 8.0     # keyword tier (no model): BM25 alone must be this sure
KEYWORD_RATIO = 1.6

NO_COMMAND = "I don't know a command for that. Say type, then the exact words."

# How people say it, per tldr page: joins speech to tldr's wording, for BM25
# and in Laya's question. Hand-written glue; the commands come from tldr.
SPOKEN = {
    "dir": "list files, show files, what's in this folder, show hidden files",
    "cd": "go to a folder, go back a folder, go up a folder, change folder",
    "cls": "clear the screen, clear the terminal",
    "mkdir": "make a folder, create a new folder, new directory",
    "rmdir": "delete a folder, remove a folder", "rd": "delete a folder, remove a folder",
    "del": "delete a file, remove a file", "copy": "copy a file", "move": "move a file",
    "ren": "rename a file", "type": "show what's in a file, read a file",
    "echo": "print text, say something", "tree": "show the folder structure",
    "where": "where is a program, find a program's path",
    "whoami": "who am I, my username, current user",
    "hostname": "computer name, pc name, machine name",
    "ipconfig": "my ip address, network settings", "ping": "ping a website, check the internet",
    "netstat": "network connections, open ports",
    "tasklist": "running programs, running processes, what's running",
    "taskkill": "kill a program, close a program, end a task",
    "systeminfo": "system information, computer specs",
    "shutdown": "shut down the computer, restart the computer, turn off the pc",
    "explorer": "open this folder in explorer, open file explorer",
    "code": "open vs code, open visual studio code", "findstr": "find a word in a file",
    "git status": "git status, what changed, show changes",
    "git log": "commit history, show commits, last commits",
    "git diff": "show the differences, what changed in the files",
    "git branch": "show branches, list branches, create a branch",
    "git add": "stage files, add files", "git commit": "commit changes",
    "git push": "push to github", "git pull": "pull the latest changes",
    "git clone": "clone a repo", "pip install": "install a python package",
    "pip uninstall": "uninstall a python package", "pip list": "installed python packages",
    "npm install": "install npm packages, install dependencies",
    "npm run": "run an npm script, start the app, run dev",
    "python": "run python, python version, run a python script",
    "node": "run node, node version", "ver": "windows version",
    "winget": "install an app with winget",
    "Get-ChildItem": "list files, show hidden files, all files",
    "Set-Location": "go to a folder, go back a folder, change folder",
    "Clear-Host": "clear the screen",
}
# Direct commands: the first word is one of these (not English verbs like
# print, find, sort, type, start, which are read as requests instead).
DIRECT = frozenset("""dir cd cls mkdir md rmdir rd del copy xcopy robocopy move ren tree where
    whoami hostname ipconfig ping tracert nslookup netstat tasklist taskkill systeminfo
    shutdown explorer notepad findstr attrib winget choco curl ssh tar git gh npm npx node
    python py pip uv code exit echo ls dotnet cargo""".split())

AI_CLIS = frozenset({"claude", "codex", "gemini", "kiro-cli", "kiro", "aider", "ollama",
                     "qwen", "opencode", "copilot", "crush"})
EXTRA_COMMANDS = frozenset({"ls", "cls", "exit", "py", "python", "pip", "node", "npm", "npx",
                            "git", "gh", "code", "uv", "winget", "choco", "wt", "explorer",
                            "notepad", "start", "cd", "dir", "mkdir", "echo"}) | AI_CLIS
# Words that make an utterance a sentence, not a command ("find the word x").
GLUE = frozenset("""the a an my me all this that these those please into inside to for what
    which is are files folder folders directory everything something how why can could would
    you i we our some any from""".split())

_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset("""a an the to of on in into for and or is it this that these those my me i
    you your with please can could would will just now here there current currently be do
    does want need let lets""".split())
SYNONYMS = {
    "folder": ["directory"], "show": ["list", "display"], "see": ["list", "display"],
    "view": ["display", "list"], "go": ["change", "directory"], "enter": ["change"],
    "back": ["parent"], "up": ["parent"], "previous": ["parent"], "make": ["create"],
    "new": ["create"], "add": ["create"], "delete": ["delete", "remove"],
    "remove": ["delete", "remove"], "erase": ["delete"], "rid": ["delete"],
    "clear": ["clear", "screen"], "clean": ["clear"], "ip": ["ip", "address", "network"],
    "running": ["running", "process"], "program": ["process"], "app": ["process"],
    "task": ["process", "task"], "kill": ["terminate", "kill", "process"],
    "end": ["terminate"], "stop": ["terminate", "stop"], "username": ["user", "name"],
    "who": ["user", "current", "username"], "pc": ["computer", "system"],
    "machine": ["computer", "system"], "shutdown": ["shut", "down"], "off": ["shut", "down"],
    "reboot": ["restart"], "commit": ["commit", "log"], "history": ["log", "history"],
    "change": ["change", "status", "diff"], "search": ["search", "find"],
    "find": ["find", "search"], "word": ["string"], "text": ["string"],
    "internet": ["ping", "network"], "connection": ["ping", "network"],
    "explorer": ["explorer", "file"], "vs": ["visual", "studio", "code"],
    "hidden": ["hidden"], "space": ["space", "disk"], "wifi": ["wireless", "network", "wlan"],
    "zip": ["compress", "archive"], "unzip": ["extract", "archive"],
    "structure": ["tree"], "content": ["content"], "empty": ["empty", "create"],
    "list": ["show", "display", "list"], "print": ["print", "display", "echo"],
    "version": ["version", "installed"], "branch": ["branch"], "differ": ["diff"],
}
_VERBS = frozenset("""show list display go change make create delete remove erase run open
    install uninstall find search ping check tell give see view start stop kill end get set
    print read write clear clean move copy rename add new put type use""".split())

NUMBER_WORDS = {w: i for i, w in enumerate("""zero one two three four five six seven eight
    nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen
    twenty""".split())}
FOLDERS = {"downloads": "Downloads", "download": "Downloads", "desktop": "Desktop",
           "documents": "Documents", "document": "Documents", "pictures": "Pictures",
           "photos": "Pictures", "music": "Music", "videos": "Videos", "video": "Videos",
           "home": "", "user": ""}

_PH = re.compile(r"\{\{(.*?)\}\}")
_OPTION = re.compile(r"\{\{\[([^\]]*)\]\}\}")
_NAMED = re.compile(r"\b(?:called|named|titled)\s+(.+)$", re.I)
_QUOTED = re.compile(r"[\"\u201c]([^\"\u201d]+)[\"\u201d]")
_WORDISH = re.compile(r"\b(?:word|words|text|string|phrase)\s+(\S+)", re.I)
_PREP = re.compile(r"\b(?:to|into|in|inside|for|at|from|of|on)\s+(?:the\s+|my\s+|a\s+)?"
                   r"(.+?)(?:\s+(?:folder|directory|file))?$", re.I)
_FILEISH = re.compile(r"(?:[a-z]:\\|\\|/)?[\w.-]*\.\w{1,6}\b|[a-z]:\\\S*|\S*[\\/]\S*", re.I)


# ------------------------------------------------------------------ words
def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("sses", "xes", "ches", "shes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokens(text: str) -> list[str]:
    return [_stem(w) for w in _WORD.findall(text.lower()) if w not in _STOP]


def query_tokens(text: str) -> list[str]:
    out: list[str] = []
    for word in tokens(text):
        out.append(word)
        out.extend(SYNONYMS.get(word, ()))
    return out


def _lower_first(desc: str) -> str:
    desc = desc.strip().rstrip(".")
    if len(desc) > 1 and not desc[:2].isupper():
        desc = desc[0].lower() + desc[1:]
    return desc


# ---------------------------------------------------------------- catalog
class Catalog:
    def __init__(self, data: dict) -> None:
        self.source = data.get("source", {})
        self.pages: dict[str, str] = data.get("pages", {})
        self.entries: list[dict] = data.get("entries", [])
        self._index: dict[str, tuple[list[str], dict[str, list[dict]], Any]] = {}
        self.commands = set(DIRECT) | AI_CLIS
        # "git" -> {"status", "log", ...} from pages like "git status".
        self.subcommands: dict[str, set[str]] = {}
        for page in self.pages:
            head, _, sub = page.partition(" ")
            if sub:
                self.subcommands.setdefault(head.lower(), set()).add(sub.split()[0].lower())

    @classmethod
    def load(cls, path: Path = CATALOG_PATH) -> "Catalog":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def _for(self, shell: str) -> tuple[list[str], dict[str, list[dict]], Any]:
        if shell not in self._index:
            from rank_bm25 import BM25Okapi

            by_page: dict[str, list[dict]] = {}
            for entry in self.entries:
                if shell in entry.get("shells", ("cmd", "powershell")):
                    by_page.setdefault(entry["page"], []).append(entry)
            names = sorted(by_page)
            docs = [tokens(f"{p} {p} {self.pages.get(p, '')} {SPOKEN.get(p, '')} "
                           f"{SPOKEN.get(p, '')} " + " ".join(e["desc"] for e in by_page[p]))
                    for p in names]
            self._index[shell] = (names, by_page, BM25Okapi(docs))
        return self._index[shell]

    def variants(self, page: str, shell: str) -> list[dict]:
        return self._for(shell)[1].get(page, [])

    def takes_file(self, page: str) -> bool:
        """Some example of `page` has a file placeholder (not a directory)."""
        return any("file" in m.lower() for e in self.entries if e["page"] == page
                   for m in _PH.findall(e["template"]))

    def question(self, page: str) -> str:
        summary = _lower_first(self.pages.get(page, "") or page)
        spoken = SPOKEN.get(page)
        return (f"Does the user want to {summary}" + (f", like: {spoken}" if spoken else "")
                + f" (the {page} command)?")

    def shortlist(self, text: str, shell: str, k: int = SHORTLIST) -> list[tuple[str, float]]:
        """Best pages for `text`: [(page, bm25)]."""
        names, _by_page, bm25 = self._for(shell)
        query = query_tokens(text)
        if not query:
            return []
        scores = bm25.get_scores(query)
        ranked = sorted(range(len(names)), key=lambda i: -scores[i])
        return [(names[i], float(scores[i])) for i in ranked[:k] if scores[i] > 0]


_catalog: Catalog | None = None


def catalog() -> Catalog:
    global _catalog
    if _catalog is None:
        _catalog = Catalog.load()
    return _catalog


# ----------------------------------------------------------------- choice
@dataclass
class Choice:
    command: str = ""
    desc: str = ""
    confidence: float = 0.0
    source: str = "none"          # direct | catalog | none
    run: bool = False
    critical: bool = False
    reason: str = ""
    scores: dict = field(default_factory=dict)


def direct_command(text: str, known: set[str],
                   subcommands: dict[str, set[str]] | None = None) -> str | None:
    """The words already are a command: "git status", "python app dot py",
    or one follows a verb: "check the git status", "run python app.py"."""
    subcommands = subcommands or {}
    command = shell_text(text)
    words = command.split()
    if not words:
        return None
    if words[0].lower() not in known:
        # A tool with subcommands, later in the sentence ("check the git
        # status"); the next word must really be a subcommand, a file or a flag.
        start = next((i for i, w in enumerate(words) if w.lower() in _FAMILIES), None)
        if start is None or start == len(words) - 1:
            return None
        nxt = words[start + 1].lower()
        if not (nxt in subcommands.get(words[start].lower(), ()) or "." in nxt
                or nxt.startswith("-")):
            return None
        words = words[start:]
        words[0] = words[0].lower()
        command = " ".join(words)
    rest = [w.lower() for w in words[1:]]
    if any(w in GLUE for w in rest) or len(rest) > 6:
        return None
    return command


_FAMILIES = frozenset({"git", "gh", "npm", "npx", "pip", "uv", "python", "py", "node", "winget"})


def _numbers(text: str) -> list[str]:
    found = re.findall(r"\b\d+\b", text)
    found += [str(NUMBER_WORDS[w]) for w in re.findall(r"[a-z]+", text.lower()) if w in NUMBER_WORDS]
    return found


def _folder(value: str, shell: str) -> str | None:
    key = value.lower().strip(" .")
    key = re.sub(r"^(?:the|my)\s+", "", key)
    key = re.sub(r"\s+(?:folder|directory)$", "", key)
    if key not in FOLDERS:
        return None
    base = "%USERPROFILE%" if shell == "cmd" else "$HOME"
    return f"{base}\\{FOLDERS[key]}" if FOLDERS[key] else base


def _quote(value: str) -> str:
    return f'"{value}"' if " " in value and not value.startswith('"') else value


def _kind(content: str) -> str:
    c = content.lower()
    parts = set(re.split(r"[_\s]", c))
    if "|" in c and "/" not in c and "\\" not in c:
        return "choice"
    if re.fullmatch(r"\d+", c) or c in ("n", "number", "count", "num", "lines", "pid") \
            or "id" in parts or "hash" in parts:
        return "number"          # ids and hashes are never guessed from words
    if c.startswith("http") or "url" in c:
        return "url"
    if any(w in c for w in ("path", "file", "dir", "folder")) or re.search(r"\.\w{1,4}$", c):
        return "path"
    if "host" in c or c in ("ip", "ip_address", "domain", "server", "remote_name", "address"):
        return "host"
    if "process" in parts or "image" in parts:
        return "process"
    if "package" in c or "module" in c:
        return "package"
    return "text"


_FILLER = frozenset({"folder", "directory", "file", "files", "one", "here", "there", "please",
                     "command", "terminal", "computer", "thing", "it", "what", "what's", "whats",
                     "which", "how", "do", "have", "am", "are", "was", "is", "show", "tell",
                     "last", "all", "current", "installed"}) | set(NUMBER_WORDS)


def _arguments(request: str, page: str = "") -> list[str]:
    """Words in the request that name something (a file, a package, a host)."""
    said = spoken_to_shell(strip_submit(request))
    known = set(tokens(page)) | set(query_tokens(SPOKEN.get(page, "")))
    words = [w.removesuffix("'s") for w in re.findall(r"[\w.:\\/'-]+", said)]
    return [w for w in words
            if len(w) > 1 and _stem(w.lower()) not in known and w.lower() not in _STOP
            and w.lower() not in _VERBS and _stem(w.lower()) not in SYNONYMS
            and w.lower() not in FOLDERS and w.lower() not in _FILLER]


def fill(template: str, request: str, desc: str, shell: str, page: str = "") -> tuple[str, bool]:
    """(command, complete). Incomplete = cut at the first placeholder it
    could not fill, so it is typed but never run."""
    command = _OPTION.sub(lambda m: m.group(1).split("|")[0], template)
    said = spoken_to_shell(strip_submit(request))
    named = _NAMED.search(said)
    prep = _PREP.search(said)
    quoted = _QUOTED.search(said)
    wordish = _WORDISH.search(said)
    files = [m.group(0) for m in _FILEISH.finditer(said) if "." in m.group(0) or "\\" in m.group(0)]
    numbers = _numbers(said)
    desc_words = set(tokens(desc)) | set(query_tokens(desc))
    leftover = [w for w in _arguments(request, page) if _stem(w.lower()) not in desc_words]
    folder = _folder(prep.group(1), shell) if prep else None
    folder = folder or next((f for w in re.findall(r"[a-z]+", said.lower())
                             if (f := _folder(w, shell))), None)
    used: set[str] = set()

    def take(*candidates: str | None) -> str | None:
        for value in candidates:
            if value and value not in used:
                used.add(value)
                return value
        return None

    out, pos = [], 0
    for match in _PH.finditer(command):
        content = match.group(1)
        kind = _kind(content)
        value: str | None = None
        if kind == "number":
            value = take(*numbers) or (content if content.isdigit() else None)
        elif kind == "choice":
            options = content.split("|")
            value = next((o for o in options if re.search(rf"\b{re.escape(o)}\b", said, re.I)),
                         None)
        elif kind == "path":
            value = take(*(files[:1]), named.group(1).strip(" .") if named else None, folder,
                         *(leftover[:1]))
        elif kind == "host":
            host = take(*(leftover[:1]))
            value = host if not host or "." in host or host == "localhost" else f"{host}.com"
        elif kind == "url":
            value = take(*[f for f in files if "://" in f or f.startswith("www.")])
        elif kind == "process":
            name = take(*(leftover[:1]))
            value = name if not name or name.lower().endswith(".exe") else f"{name}.exe"
        elif kind == "package":
            value = take(" ".join(leftover) if leftover else None)
        else:
            value = take(named.group(1).strip(" .") if named else None,
                         quoted.group(1) if quoted else None,
                         wordish.group(1) if wordish else None,
                         " ".join(leftover) if leftover else None)
        if value is None:
            out.append(command[pos:match.start()])
            return "".join(out).rstrip(' "'), False
        quoted_in_template = command[max(0, match.start() - 1):match.start()] == '"'
        out.append(command[pos:match.start()])
        out.append(value if quoted_in_template or kind in ("number", "choice") else _quote(value))
        pos = match.end()
    out.append(command[pos:])
    result = "".join(out).strip()
    if shell == "cmd" and re.match(r"cd\s+(?:%|[a-z]:)", result, re.I) and "/d" not in result:
        result = "cd /d " + result[3:].strip()
    return result, True


def for_shell(command: str, shell: str) -> str:
    """PowerShell aliases that shadow real programs: where, sc, curl, wget."""
    if shell != "powershell":
        return command
    first, _, rest = command.partition(" ")
    if first.lower() in ("where", "sc", "curl", "wget"):
        return f"{first}.exe {rest}".strip()
    return command


_DANGER_FIRST = frozenset("""del erase rd rmdir format diskpart shutdown taskkill reg sc sc.exe net
    cipher bcdedit takeown icacls remove-item stop-process clear-content format-volume rm
    restart-computer stop-computer wsl robocopy""".split())
_READ_ONLY = frozenset({"query", "view", "help", "/?", "list", "show", "status"})
_DANGER_SUB = {"git": {"push", "reset", "clean", "rebase", "restore", "rm", "filter-branch",
                       "prune", "stash"},
               "npm": {"publish", "uninstall", "unpublish"}, "pip": {"uninstall"},
               "winget": {"uninstall"}, "choco": {"uninstall"}, "uv": {"remove"},
               "gh": {"repo", "release", "pr"}}


def dangerous(command: str) -> str:
    """Why this command needs approval, or ""."""
    words = command.split()
    if not words:
        return ""
    first = words[0].lower()
    second = words[1].lower() if len(words) > 1 else ""
    if first in _DANGER_FIRST and second not in _READ_ONLY:
        return f"{first} can delete or stop things"
    if second in _DANGER_SUB.get(first, ()):
        return f"{first} {second} changes things outside this window"
    if first == "git" and second == "branch" and re.search(r"\s-[dD]\b|--delete", command):
        return "deletes a branch"
    if first == "tar" and re.match(r"-?[a-z]*x", second):
        return "extracting can overwrite files"
    if first == "git" and second in ("checkout", "switch") and " -- " in f" {command} ":
        return "discards changes"
    if re.search(r"(?<!>)>(?!>)", command):
        return "overwrites a file"
    if re.search(r"/s\b.*/q\b|/q\b.*/s\b|-recurse\b.*-force|--force\b|\s-rf\b", command, re.I):
        return "forced or recursive"
    return ""


_SAME = {"list": "show", "display": "show", "print": "show", "view": "show"}


def _canon(words: list[str]) -> set[str]:
    return {_SAME.get(w, w) for w in words}


def pick_variant(variants: list[dict], request: str, shell: str,
                 page: str = "") -> tuple[dict, str, bool] | None:
    """The page's example that fits the request best: (entry, command, complete).

    Words shared with the example's description, plus a bonus when its
    placeholders could be filled from the request (and a small penalty for a
    plain example when the request names something). Ties keep tldr's order,
    which puts the everyday form first.
    """
    # Raw words (no synonyms): "show hidden files" must pick "including hidden ones".
    said = _canon(tokens(request)) - _canon(tokens(page))  # every variant has the page's words
    has_argument = bool(_arguments(request, page))
    best, best_score = None, float("-inf")
    for index, entry in enumerate(variants):
        command, complete = fill(entry["template"], request, entry["desc"], shell, page)
        holes = len(_PH.findall(_OPTION.sub("", entry["template"])))
        score = len(said & _canon(tokens(entry["desc"])))
        if holes and complete:
            score += 0.8
        elif holes:
            score -= 1.5       # typed but not run: only when nothing complete fits
        elif has_argument:
            score -= 0.3
        if index == 0:
            score += 0.8       # tldr lists the everyday form first
        score -= 0.01 * index
        if score > best_score:
            best, best_score = (entry, command, complete), score
    return best


async def choose(text: str, shell: str, cat: Catalog | None = None) -> Choice:
    cat = cat or catalog()
    request = strip_submit(text).strip()
    if not request:
        return Choice(reason="empty")
    direct = direct_command(request, cat.commands, cat.subcommands)
    if direct:
        command = for_shell(_host(direct), shell)
        why = dangerous(command)
        return Choice(command=command, source="direct", confidence=1.0, run=True,
                      critical=bool(why), reason=why or "the words are a command")

    pages = cat.shortlist(request, shell)
    if not pages:
        return Choice(reason="nothing in the catalog matches")
    questions = {f"c{i}": {"type": "noul", "instructions": cat.question(page)}
                 for i, (page, _s) in enumerate(pages)}
    questions["risk"] = {"type": "noul", "instructions":
                         "Does the request ask to delete, remove, kill, stop, shut down, restart, "
                         "format, overwrite or uninstall something?"}
    state = {"request": request, "shell": "Command Prompt" if shell == "cmd" else "PowerShell"}
    try:
        result = await asyncio.to_thread(laya_engine.decide, state, questions, 0.0)
        tier = str(result.get("tier") or "")
        yes = [float(result["answers"][f"c{i}"]["noul"]) for i in range(len(pages))]
        risk = float(result["answers"]["risk"]["noul"])
    except laya_engine.LayaUnavailable:
        tier, yes, risk = "keywords", [0.0] * len(pages), 0.0

    bm25 = [s for _p, s in pages]
    top = max(bm25) or 1.0
    if tier == "keywords":
        second = bm25[1] if len(bm25) > 1 else 0.0
        if bm25[0] < KEYWORD_MIN or bm25[0] < KEYWORD_RATIO * second:
            return Choice(reason="keyword tier: not sure enough", scores={"bm25": bm25})
        best, confidence = 0, min(1.0, bm25[0] / (KEYWORD_RATIO * second or 1.0) - 1.0)
    else:
        if bm25[0] < BM25_MIN:
            return Choice(reason=f"nothing close enough (bm25 {bm25[0]:.1f})",
                          scores={"yes": yes, "pages": pages})
        combined = [y + BM25_WEIGHT * s / top for y, s in zip(yes, bm25)]
        if re.search(r"\b[\w-]+\.\w{1,5}\b", request):
            # "notes.txt" in the request: a command that takes a file.
            combined = [c + (FILE_BONUS if cat.takes_file(p) else 0.0)
                        for c, (p, _s) in zip(combined, pages)]
        best = max(range(len(pages)), key=lambda i: combined[i])
        family = _family(pages[best][0])
        # "pip" vs "pip install", "dir" vs "Get-ChildItem": not a disagreement.
        runner = max((c for i, c in enumerate(combined)
                      if i != best and _family(pages[i][0]) != family), default=0.0)
        confidence = combined[best] - runner
        floor = YES_FLOOR
        head = pages[best][0].split()[0].lower()
        if head in _FAMILIES and head not in tokens(request):
            floor = TOOL_YES   # "switch to chrome" is not `git switch`
        if yes[best] < floor or (confidence < MARGIN and yes[best] < STRONG_YES):
            return Choice(reason=f"laya unsure: {pages[best][0]} yes {yes[best]:.2f}, "
                                 f"margin {confidence:.2f}",
                          confidence=confidence, scores={"yes": yes, "pages": pages})

    page = pages[best][0]
    picked = pick_variant(cat.variants(page, shell), request, shell, page)
    if picked is None:
        return Choice(reason=f"{page}: no example for this shell")
    entry, command, complete = picked
    command = for_shell(command, shell)
    why = dangerous(command) or (f"laya risk {risk:.2f}" if risk >= RISK_YES else "")
    return Choice(command=command, desc=entry["desc"], confidence=confidence, source="catalog",
                  run=complete, critical=bool(why), reason=why or f"{tier}: {page}",
                  scores={"yes": yes, "pages": pages, "risk": risk})


# PowerShell cmdlets and cmd aliases for the same thing count as one command.
_SAME_AS = {"Get-ChildItem": "dir", "Set-Location": "cd", "Get-Location": "cd", "Clear-Host": "cls",
            "Get-Content": "type", "Remove-Item": "del", "Copy-Item": "copy", "Move-Item": "move",
            "Rename-Item": "ren", "New-Item": "mkdir", "Select-String": "findstr",
            "Test-Connection": "ping", "Invoke-WebRequest": "curl", "rd": "rmdir", "md": "mkdir",
            "erase": "del", "py": "python", "xcopy": "copy", "robocopy": "copy"}


def _family(page: str) -> str:
    head = page.split()[0]
    return _SAME_AS.get(page, _SAME_AS.get(head, head.lower()))


def _host(command: str) -> str:
    """ "ping google" -> "ping google.com": spoken hosts have no dot."""
    words = command.split()
    if len(words) == 2 and words[0].lower() in ("ping", "tracert", "nslookup") \
            and "." not in words[1] and words[1].lower() != "localhost":
        return f"{words[0]} {words[1]}.com"
    return command


# ------------------------------------------------------------ gemini
PROPOSE_SYSTEM = (
    "You turn one spoken request into ONE Windows {shell} command line. Reply with JSON only: "
    '{{"command": "<one line>", "does": "<what it does, in plain words, one sentence>"}}. '
    "Prefer built-in commands. If the request is not something a terminal command does "
    '(small talk, a question, dictation), reply {{"command": "NONE", "does": ""}}.')
LAYA_CHECK = ("Does the described command do what the user asked for? "
              "Answer yes only if it matches the request.")
CHECK_YES = 0.55     # Laya on (request, what Gemini says the command does)
VERIFY_YES = 0.25    # Laya on (request, the tldr example's description)
AUTO_YES = 0.75      # a read-only Gemini command runs without asking above this


def _parse_proposal(text: str) -> tuple[str, str]:
    """(command, does) from Gemini's JSON (tolerates ```json fences)."""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return "", ""
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return "", ""
    command = str(data.get("command") or "").strip().strip("`")
    return (command if "\n" not in command else ""), str(data.get("does") or "").strip()


def verify(request: str, desc: str) -> float:
    """Laya: does this described command match the request? (0..1)"""
    try:
        return float(laya_engine.yes_no({"request": request, "command does": desc}, LAYA_CHECK))
    except laya_engine.LayaUnavailable:
        return 0.0


async def propose(request: str, shell: str, previous: Choice, llm=None) -> Choice:  # noqa: ANN001
    """tldr had nothing sure: Gemini drafts one command, Laya checks it matches
    the request, and it is always read out and asked before it runs."""
    if llm is None:
        from .. import llm as _llm

        llm = _llm
    name = "Command Prompt (cmd.exe)" if shell == "cmd" else "PowerShell"
    try:
        draft = await llm.complete([
            {"role": "system", "content": PROPOSE_SYSTEM.format(shell=name)},
            {"role": "user", "content": strip_submit(request)}], max_tokens=1000)
    except Exception as exc:  # noqa: BLE001 - no LLM: keep tldr's "no command"
        log.info("terminal: no Gemini proposal (%s)", getattr(exc, "kind", exc))
        return previous
    command, does = _parse_proposal(draft)
    if not command or command.upper() == "NONE" or len(command) > 300:
        return Choice(reason="gemini: not a command", scores=previous.scores)
    # Rule 9: nothing Gemini proposes runs without Laya agreeing it matches.
    yes = await asyncio.to_thread(verify, request, does or command) if does else 0.0
    if yes < CHECK_YES:
        log.info("terminal: Laya rejected Gemini's %r (%s) for %r (yes %.2f)", command, does,
                 request, yes)
        return Choice(reason=f"laya rejected the proposal (yes {yes:.2f})", scores=previous.scores)
    why = dangerous(command)
    command = for_shell(command, shell)
    if re.search(r"\[[A-Z_ ]+\]|<[a-z_ -]+>|\{\{", command):
        # "[SSID]", "<file>": Gemini left a blank. Typed for you to finish, never run.
        return Choice(command=command, desc=does, confidence=yes, source="gemini", run=False,
                      critical=False, reason="has a blank to fill")
    # Laya acts as you only on small, read-only commands it is sure about;
    # anything else Gemini wrote is read out and asked first (rule 10).
    auto = not why and read_only(command) and yes >= AUTO_YES
    return Choice(command=command, desc=does, confidence=yes, source="gemini", run=True,
                  critical=not auto, reason=why or ("read-only" if auto else "proposed by Gemini"))


_READ_ONLY_FIRST = frozenset("""dir tree type more find findstr where whoami hostname ipconfig ping
    tracert nslookup netstat tasklist systeminfo echo ver getmac get-childitem get-content
    get-process get-location select-string test-connection get-date measure-object""".split())
_READ_ONLY_SUB = {"git": {"status", "log", "diff", "show", "branch", "remote", "tag", "blame"},
                  "npm": {"list", "ls", "view", "outdated"}, "pip": {"list", "show", "freeze"},
                  "netsh": {"wlan"}}


def read_only(command: str) -> bool:
    """A command that only looks: no redirect, no chaining into something else."""
    if re.search(r"(?<![<>])>|\|\s*(?!findstr|find\b|more\b|sort\b|select-string)\w|&&|;", command,
                 re.I):
        return False
    words = command.lower().split()
    if not words:
        return False
    if words[0] in _READ_ONLY_FIRST:
        return True
    if words[0] in ("python", "node", "npm", "pip", "git") and words[1:2] == ["--version"]:
        return True
    return len(words) > 1 and words[1] in _READ_ONLY_SUB.get(words[0], ())


# ------------------------------------------------------------------ skill
class TerminalSkill(Skill):
    name = "terminal"
    category = "code"
    actions = {"shell_command": "run a command in the terminal"}

    async def plan(self, decision: Any, context: dict) -> Plan:
        context = context or {}
        request = str(context.get("request") or decision.target or "")
        raw = str((context.get("terminal") or {}).get("shell") or "cmd").lower()
        shell = "powershell" if raw in ("powershell", "pwsh") else "cmd"
        choice = await choose(request, shell)
        if not choice.command and choice.reason != "empty":
            choice = await propose(request, shell, choice)
        elif choice.source == "catalog" and choice.desc:
            # Laya re-reads the chosen example against the request; a doubtful
            # pick ("zip the folder" -> tar xvf) asks Gemini for a better one.
            fit = await asyncio.to_thread(verify, request, choice.desc)
            if fit < VERIFY_YES:
                better = await propose(request, shell, choice)
                if better.command:
                    choice = better
                elif not read_only(choice.command):
                    # Neither is sure: read it out and ask ("Run tar xvf reports?").
                    log.info("terminal: doubtful %r (fit %.2f); asking first", choice.command, fit)
                    choice.critical = True
        log.info("terminal %r -> %r (%s, %s, conf %.2f, run=%s, critical=%s)", request[:80],
                 choice.command, choice.source, choice.reason[:60], choice.confidence,
                 choice.run, choice.critical)
        args = {"command": choice.command, "run": choice.run, "desc": choice.desc,
                "confidence": round(choice.confidence, 3), "source": choice.source,
                "shell": shell, "reason": choice.reason, "noop": not choice.command}
        return Plan(skill=self.name, action="shell_command", args=args,
                    preview=f"Run {choice.command}?" if choice.command else "",
                    critical=choice.critical)

    async def run(self, plan: Plan, approval: Any = None, dry_run: bool = False) -> Result:
        command = str(plan.args.get("command") or "")
        if not command:
            # Not handled: Voice Vibe tries its own window commands, then says
            # NO_COMMAND. The words are never typed into the shell.
            return Result(ok=False, text=NO_COMMAND, data={"handled": False})
        if plan.critical and getattr(approval, "status", None) != "approved":
            return Result(ok=False, text="Cancelled.")
        enter = bool(plan.args.get("run"))
        # Esc first: cmd and PowerShell both clear a half-typed line with it.
        steps = [{"keys": "esc"}, {"type_text": command}] + ([{"keys": "enter"}] if enter else [])
        if dry_run:
            return Result(ok=True, text=command, speak=False, data={"steps": steps})
        bus = getattr(self.hub, "bus", None)
        if bus is None or not bus.connected("voicevibe"):
            return Result(ok=False, text="Voice Vibe isn't connected.")
        reply = await bus.send_to("voicevibe", protocol.message("run_steps", steps=steps,
                                                                dry_run=False))
        if reply.get("type") == "error" or reply.get("ok") is False:
            return Result(ok=False, text=f"Couldn't type it: {reply.get('error') or reply.get('message')}")
        if not enter:
            spoken = f"Typed {command.split()[0]}. Say the rest, then press enter."
        elif plan.args.get("source") == "catalog":
            spoken = _lower_first(str(plan.args.get("desc") or "")).capitalize()[:90] + "."
        else:
            spoken = ""
        return Result(ok=True, text=spoken or command, speak=bool(spoken),
                      data={"command": command, "ran": enter})


SKILL = TerminalSkill()
