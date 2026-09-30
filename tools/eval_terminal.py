"""Read-only check of the terminal skill with the real Laya: nothing is typed.

    set HF_HOME=..\\venvs\\hf-cache & set HF_HUB_OFFLINE=1
    ..\\venvs\\voicevibe\\Scripts\\python.exe tools\\eval_terminal.py [cmd|powershell]

Prints what each phrase would become. EXPECT marks the command's first words
(or "none" / "critical"); the last line is the accuracy.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vvhub import laya_engine  # noqa: E402
from vvhub.skills.terminal import choose  # noqa: E402

EXPECT = [
    ("list the files", "dir|Get-ChildItem"), ("show me what's in this folder", "dir"),
    ("show hidden files", "dir /a|Get-ChildItem -Force|Get-ChildItem -Hidden"), ("go to the downloads folder", "cd|Set-Location"),
    ("go back one folder", "cd ..|Set-Location .."), ("go up a folder", "cd ..|Set-Location .."),
    ("make a folder called test", "mkdir test"), ("create a new folder named reports", "mkdir reports"),
    ("clear the screen", "cls|Clear-Host"), ("what's my ip address", "ipconfig"),
    ("show running programs", "tasklist"), ("show the running processes", "tasklist"),
    ("check the git status", "git status"), ("git status", "git status"),
    ("show the commit history", "git log"), ("show the last five commits", "git log"),
    ("install requests with pip", "pip install requests"), ("ping google", "ping google.com"),
    ("who am i", "whoami"), ("what is my username", "whoami"),
    ("open this folder in explorer", "explorer"), ("open vs code here", "code ."),
    ("show the folder structure", "tree"), ("what version of python do i have", "python"),
    ("show the contents of notes.txt", "type notes.txt"), ("print hello world", "echo"),
    ("what's the computer name", "hostname"), ("show system information", "systeminfo"),
    ("show network connections", "netstat"), ("claude", "claude"),
    ("python app dot py", "python app.py"), ("cd dot dot", "cd .."),
    ("show the git branches", "git branch"), ("show what changed", "git"),
    ("delete notes.txt", "critical"), ("kill notepad", "critical"),
    ("shut down the computer", "critical"), ("remove the folder called build", "critical"),
    ("hello how are you", "none"), ("the weather is nice today", "none"),
    ("i like pizza a lot", "none"), ("switch to chrome", "none"),
    ("run the tests with npm", "npm"), ("show installed python packages", "pip"),
    ("go home", "cd|Set-Location"), ("open notepad", "none"),
]


async def main(shell: str) -> int:
    started = time.perf_counter()
    laya_engine.engine().warm()
    print(f"laya tier {laya_engine.engine().tier} warm in {time.perf_counter() - started:.1f}s")
    good = 0
    for phrase, expect in EXPECT:
        t0 = time.perf_counter()
        c = await choose(phrase, shell)
        ms = (time.perf_counter() - t0) * 1000
        if expect == "none":
            ok = not c.command
        elif expect == "critical":
            ok = bool(c.command) and c.critical
        else:
            ok = any(c.command.lower().startswith(x.lower()) for x in expect.split("|"))
        good += ok
        print(f"{'OK ' if ok else 'BAD'} {phrase!r:42} -> {c.command!r:40} {c.source:7} "
              f"run={c.run!s:5} crit={c.critical!s:5} conf={c.confidence:.2f} {ms:5.0f}ms  {c.reason[:50]}")
        pages, yes = c.scores.get("pages") or [], c.scores.get("yes") or []
        if pages and "-v" in sys.argv:
            top = sorted(zip(pages, yes), key=lambda t: -t[0][1])[:4]
            print("      " + "  ".join(f"{p}:bm{b:.1f}/y{y:.2f}" for (p, b), y in top)
                  + "  | laya best " + max(zip(pages, yes), key=lambda t: t[1])[0][0])
    print(f"{good}/{len(EXPECT)} as expected")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "cmd")))
