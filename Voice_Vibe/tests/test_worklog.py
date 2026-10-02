"""Work context for the broker (vvhub.worklog): what the user is coding on.

What matters: the newest Claude Code / Codex sessions are read from their
own transcript files (folder, branch, title, the last prompts and replies,
never tool output or side chains), stale sessions are skipped, git state
comes from argument-list commands with a time limit, the whole text is
capped, and nothing breaks when the folders or git are missing. Temp folders
and a fake git only.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vvhub import worklog  # noqa: E402


def write_jsonl(path: Path, records: list[dict], age_s: float = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    t = time.time() - age_s
    os.utime(path, (t, t))


CLAUDE = [
    {"type": "custom-title", "customTitle": "Parser refactor", "sessionId": "s1"},
    {"type": "user", "cwd": "C:\\work\\parser", "gitBranch": "feature/tests", "isSidechain": False,
     "message": {"role": "user", "content": "refactor the tokenizer into its own module"}, "timestamp": "t1"},
    {"type": "assistant", "cwd": "C:\\work\\parser", "isSidechain": False,
     "message": {"role": "assistant", "content": [
         {"type": "text", "text": "Moved tokenize() to tokenizer.py. Next I'd add tests for empty input."},
         {"type": "tool_use", "name": "Bash", "input": {"command": "pytest"}}]}},
    {"type": "user", "isSidechain": False,
     "message": {"role": "user", "content": [{"type": "tool_result", "content": "SECRET TOOL OUTPUT"}]}},
    {"type": "assistant", "isSidechain": True,
     "message": {"role": "assistant", "content": [{"type": "text", "text": "side chain chatter"}]}},
]

CODEX = [
    {"type": "session_meta", "payload": {"cwd": "C:\\work\\site", "id": "c1"}},
    {"type": "response_item", "payload": {"type": "message", "role": "user",
                                          "content": [{"type": "input_text", "text": "make the header sticky"}]}},
    {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                          "content": [{"type": "output_text", "text": "Done: header is sticky."}]}},
]


class FakeGit:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, cwd, timeout):
        assert isinstance(argv, list)
        self.calls.append((argv, cwd, timeout))
        if argv[1:3] == ["rev-parse", "--abbrev-ref"]:
            return "feature/tests\n"
        if argv[1] == "status":
            return " M tokenizer.py\n?? notes.txt\n"
        if argv[1] == "log":
            return "Split the tokenizer\nAdd parser skeleton\n"
        return ""


class WorklogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.git = FakeGit()
        for folder in ("C:\\work\\parser", "C:\\work\\site"):
            pass
        worklog.clear_cache()

    def tearDown(self):
        self.tmp.cleanup()
        worklog.clear_cache()

    def sessions(self, **kw):
        return worklog.latest_sessions(home=self.home, **kw)

    def test_reads_claude_and_codex(self):
        write_jsonl(self.home / ".claude" / "projects" / "C--work-parser" / "s1.jsonl", CLAUDE, age_s=60)
        write_jsonl(self.home / ".codex" / "sessions" / "2026" / "09" / "30" / "c1.jsonl", CODEX, age_s=120)
        found = self.sessions()
        self.assertEqual([s.agent for s in found], ["Claude Code", "Codex"])
        claude = found[0]
        self.assertEqual((claude.cwd, claude.branch, claude.title), ("C:\\work\\parser", "feature/tests",
                                                                    "Parser refactor"))
        self.assertEqual([t[0] for t in claude.turns], ["you", "agent"])
        self.assertIn("tokenizer", claude.turns[0][1])
        self.assertIn("Next I'd add tests", claude.turns[1][1])
        text = " ".join(t[1] for t in claude.turns)
        self.assertNotIn("SECRET TOOL OUTPUT", text)
        self.assertNotIn("side chain", text)
        self.assertEqual(found[1].cwd, "C:\\work\\site")
        self.assertIn("sticky", found[1].turns[-1][1])

    def test_stale_sessions_skipped(self):
        write_jsonl(self.home / ".claude" / "projects" / "old" / "s.jsonl", CLAUDE, age_s=3 * 86400)
        self.assertEqual(self.sessions(), [])

    def test_missing_folders(self):
        self.assertEqual(self.sessions(), [])
        self.assertEqual(worklog.work_context(home=self.home, git=self.git), "")

    def test_context_text_with_git_and_cap(self):
        repo = self.home / "parser"
        repo.mkdir()
        records = [dict(r) for r in CLAUDE]
        for r in records:
            if "cwd" in r:
                r["cwd"] = str(repo)
        records.append({"type": "user", "cwd": str(repo), "isSidechain": False,
                        "message": {"role": "user", "content": "x" * 5000}})
        write_jsonl(self.home / ".claude" / "projects" / "p" / "s1.jsonl", records)
        text = worklog.work_context(home=self.home, git=self.git, limit=1500)
        self.assertLessEqual(len(text), 1500)
        self.assertIn("Claude Code", text)
        self.assertIn("Parser refactor", text)
        self.assertIn("feature/tests", text)
        self.assertIn("2 changed files", text)
        self.assertIn("Split the tokenizer", text)
        for argv, cwd, timeout in self.git.calls:
            self.assertEqual(argv[0], "git")
            self.assertEqual(cwd, str(repo))
            self.assertLessEqual(timeout, 3)

    def test_git_failure_is_ignored(self):
        repo = self.home / "parser"
        repo.mkdir()
        records = [dict(r, cwd=str(repo)) if "cwd" in r else r for r in CLAUDE]
        write_jsonl(self.home / ".claude" / "projects" / "p" / "s1.jsonl", records)

        def broken(argv, cwd, timeout):
            raise OSError("git missing")

        self.assertIn("Parser refactor", worklog.work_context(home=self.home, git=broken))

    def test_cached(self):
        write_jsonl(self.home / ".claude" / "projects" / "p" / "s1.jsonl", CLAUDE)
        first = worklog.work_context(home=self.home, git=self.git)
        (self.home / ".claude" / "projects" / "p" / "s1.jsonl").unlink()
        self.assertEqual(worklog.work_context(home=self.home, git=self.git), first)


if __name__ == "__main__":
    unittest.main()
