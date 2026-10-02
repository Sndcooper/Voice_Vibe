"""Build src/vvhub/data/shell_catalog.json from tldr-pages (CC BY 4.0).

    ..\\venvs\\voicevibe\\Scripts\\python.exe tools\\build_shell_catalog.py [path\\to\\tldr]

Reads every page in pages/windows and the developer-tool pages of pages/common
(git, npm, python, pip, gh, code, ...). Each "- Description:" line with the
command after it becomes one entry the terminal skill can offer to Laya.
Default source: ..\\Repos\\tldr (a sparse clone; see THIRD_PARTY.lock).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_TLDR = REPO.parent / "Repos" / "tldr"
OUT = REPO / "src" / "vvhub" / "data" / "shell_catalog.json"

# Everyday pages only: with all 800 tldr pages Laya was offered mimikatz and
# vcvarsall for "show system information" and "scroll up" (eval 15/42).
WINDOWS_PAGES = set("""dir cd cls mkdir md rmdir rd del erase copy xcopy robocopy move ren
    type echo tree where whoami hostname ipconfig ping tracert nslookup netstat tasklist
    taskkill systeminfo shutdown start explorer notepad findstr more sort fc attrib ver time
    date winget choco curl ssh tar exit pushd popd getmac clip powershell pwsh cmd
    get-childitem set-location get-location get-process stop-process remove-item new-item
    get-content clear-host copy-item move-item rename-item select-string test-connection
    get-date invoke-webrequest get-command""".split())
COMMON_PAGES = set("""git git-status git-log git-diff git-branch git-add git-commit git-push
    git-pull git-clone git-checkout git-switch git-stash git-init git-remote git-fetch
    git-merge git-reset git-restore git-show git-tag npm npm-install npm-run npm-init
    npm-list npm-uninstall npx node python pip pip-install pip-uninstall pip-freeze pip-list
    uv uv-venv uv-run uv-pip uv-add gh gh-pr gh-repo gh-issue gh-auth code curl ssh tar
    ollama claude codex gemini hostname echo""".split())
# Everyday asks tldr has no example for; marked source "voicevibe" in the JSON.
EXTRA = [
    ("python", "Show the installed Python version", "python --version"),
    ("node", "Show the installed Node.js version", "node --version"),
    ("npm", "Show the installed npm version", "npm --version"),
    ("git", "Show the installed Git version", "git --version"),
    ("pip", "Show the installed pip version", "pip --version"),
    ("cls", "Clear the screen", "cls"),
    ("git log", "Show the last n commits, one line each", "git log --oneline -n {{5}}"),
    ("code", "Open the current folder in Visual Studio Code", "code ."),
]

# cmd built-ins PowerShell also knows as aliases, but with PowerShell syntax:
# "dir /a" fails there, "dir" works.
ALIASED_BUILTINS = {"dir", "cd", "chdir", "cls", "copy", "del", "erase", "move", "ren",
                    "rename", "rmdir", "rd", "md", "mkdir", "type", "echo", "popd",
                    "pushd", "start"}
# cmd only: no PowerShell equivalent under the same name.
CMD_ONLY = {"set", "ver", "vol", "assoc", "ftype", "title", "color", "prompt", "path",
            "call", "goto", "if", "for", "mklink", "rem", "pause", "break", "verify",
            "date", "time", "cmd"}
PS_VERBS = {"get", "set", "new", "remove", "start", "stop", "invoke", "test", "add", "clear",
            "out", "select", "where", "sort", "measure", "write", "read", "import", "export",
            "convert", "convertto", "convertfrom", "copy", "move", "rename", "resolve", "show",
            "wait", "update", "install", "uninstall", "enable", "disable", "restart", "resume",
            "suspend", "format", "split", "join", "compare", "group", "push", "pop", "find",
            "save", "register", "unregister", "tee", "expand", "compress", "mount",
            "dismount", "connect", "disconnect", "send", "receive", "use", "trace", "debug"}

_EXAMPLE = re.compile(r"^- (.+?):?\s*$")
_CODE = re.compile(r"^`(.+)`\s*$")


def shells_for(page: str, template: str, summary: str) -> list[str]:
    first = page.split()[0].lower()
    if "powershell" in summary.lower() and "only" in summary.lower():
        return ["powershell"]
    if "$env:" in template.lower() or "$home" in template.lower():
        return ["powershell"]
    head = first.split("-")[0]
    if "-" in first and head in PS_VERBS:
        return ["powershell"]
    if first in CMD_ONLY or re.search(r"%\w+%", template):
        return ["cmd"]
    if first in ALIASED_BUILTINS and re.search(r"\s/[A-Za-z?]", template):
        return ["cmd"]
    return ["cmd", "powershell"]


def clean_desc(desc: str) -> str:
    """tldr marks mnemonics as "[d]rive" and code as `x`: plain words for Laya."""
    desc = re.sub(r"\[(\w+)\]", r"\1", desc)
    return desc.replace("`", "").strip()


def parse_page(path: Path) -> tuple[str, str, list[tuple[str, str]]]:
    """(page name, one-line summary, [(example description, template)])."""
    name, summary, examples = path.stem.replace("-", " "), "", []
    pending = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("# "):
            name = line[2:].strip()
        elif line.startswith("> ") and not summary and "More information" not in line:
            summary = line[2:].strip()
        elif (match := _EXAMPLE.match(line)):
            pending = match.group(1).strip().rstrip(":")
        elif pending and (match := _CODE.match(line)):
            examples.append((pending, match.group(1).strip()))
            pending = None
    return name, summary, examples


def commit_of(tldr: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(tldr), "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def build(tldr: Path) -> dict:
    pages: dict[str, str] = {}
    entries: list[dict] = []
    files = [p for p in sorted((tldr / "pages" / "windows").glob("*.md"))
             if p.stem in WINDOWS_PAGES]
    files += [p for p in sorted((tldr / "pages" / "common").glob("*.md"))
              if p.stem in COMMON_PAGES]
    seen: set[tuple[str, str]] = set()
    for path in files:
        name, summary, examples = parse_page(path)
        if name in pages and path.parent.name == "common":
            continue  # a pages/windows page with the same name wins
        pages[name] = summary
        for desc, template in examples:
            if template.startswith("tldr ") or "documentation" in desc.lower():
                continue  # tldr's pointers to other pages, not commands
            desc = clean_desc(desc)
            key = (desc.lower(), template)
            if key in seen:
                continue
            seen.add(key)
            entries.append({"page": name, "desc": desc, "template": template,
                            "shells": shells_for(name, template, summary)})
    for page, desc, template in EXTRA:
        if page in pages:
            entries.append({"page": page, "desc": desc, "template": template,
                            "shells": ["cmd", "powershell"], "source": "voicevibe"})
    return {
        "source": {
            "repo": "https://github.com/tldr-pages/tldr",
            "commit": commit_of(tldr),
            "license": "CC BY 4.0",
            "attribution": "Command examples from tldr-pages, (c) the tldr-pages contributors, "
                           "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). "
                           "Converted to JSON; unchanged otherwise.",
        },
        "pages": pages,
        "entries": entries,
    }


def main(argv: list[str]) -> int:
    tldr = Path(argv[1]) if len(argv) > 1 else DEFAULT_TLDR
    if not (tldr / "pages" / "windows").is_dir():
        print(f"tldr-pages not found at {tldr}", file=sys.stderr)
        return 1
    catalog = build(tldr)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(catalog['entries'])} entries from {len(catalog['pages'])} pages -> {OUT} "
          f"({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
