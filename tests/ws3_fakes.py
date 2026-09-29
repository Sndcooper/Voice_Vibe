"""Fakes for WS3 tests: OpenCLI runner, Windows-MCP, LLM, Laya, approvals,
store, Notion. Nothing here touches a real browser, account, or network."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import stubs

stubs.install()

from vvhub.schemas import Approval  # noqa: E402


def run(coro):  # noqa: ANN001, ANN201
    return asyncio.run(coro)


class FakeRunner:
    """Answers OpenCLI argv lists from a table of (predicate, reply) rules."""

    def __init__(self, replies: list | None = None) -> None:
        self.calls: list[list[str]] = []
        self.replies = list(replies or [])

    def on(self, match: str, reply: Any = None, code: int = 0, err: str = "") -> "FakeRunner":
        self.replies.append((match, reply, code, err))
        return self

    async def __call__(self, argv: list[str], timeout: float) -> tuple[int, str, str]:
        self.calls.append(list(argv))
        joined = " ".join(argv)
        for match, reply, code, err in self.replies:
            if match in joined:
                out = reply if isinstance(reply, str) else json.dumps(reply)
                return code, out if reply is not None else "", err
        return 0, "", ""

    def commands(self) -> list[str]:
        """argv without the node/main.js prefix, joined."""
        return [" ".join(c[2:]) for c in self.calls]


PREFIX = ["node", "main.js"]


class FakeMCP:
    def __init__(self, reply: str = "") -> None:
        self.reply = reply
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, tool: str, args: dict) -> str:
        self.calls.append((tool, args))
        return self.reply


class FakeLauncher:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def __call__(self, argv: list[str]) -> None:
        self.calls.append(argv)


class LLMUnavailable(RuntimeError):
    pass


class FakeLLM:
    def __init__(self, reply: str = "ok", unavailable: bool = False) -> None:
        self.reply = reply
        self.unavailable = unavailable
        self.calls: list[list[dict]] = []
        self.LLMUnavailable = LLMUnavailable

    async def complete(self, messages, model="auto", max_tokens=800):  # noqa: ANN001, ANN201
        self.calls.append(messages)
        if self.unavailable:
            raise LLMUnavailable("pool exhausted")
        return self.reply(messages) if callable(self.reply) else self.reply


class FakeLaya:
    """score/yes_no return fixed or keyword-driven values; records states."""

    def __init__(self, yes: float = 0.9, scores: dict | None = None, default: float = 0.1) -> None:
        self.yes = yes
        self.scores = scores or {}
        self.default = default
        self.calls: list[tuple] = []

    def yes_no(self, state, instruction):  # noqa: ANN001, ANN201
        self.calls.append(("yes_no", state, instruction))
        return self.yes

    def score(self, state, instruction, criteria=None):  # noqa: ANN001, ANN201
        self.calls.append(("score", state, instruction))
        for key, value in self.scores.items():
            if key in instruction or key in state:
                return value
        return self.default


class FakeApprovals:
    def __init__(self, status: str = "approved", channel: str = "voice") -> None:
        self.status = status
        self.channel = channel
        self.requests: list[tuple[str, str]] = []

    async def request(self, action, preview, critical=True):  # noqa: ANN001, ANN201
        self.requests.append((action, preview))
        return Approval(action=action, preview=preview, channel=self.channel, status=self.status,
                        decided_by="user" if self.status == "approved" else "")


class FakeStore:
    """Same signatures as WS0's vvhub.store.Store for the calls WS3 makes."""

    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}
        self.watch: list[dict] = []

    def add_job(self, kind, conversation=None, status="queued"):  # noqa: ANN001, ANN201
        job_id = f"job{len(self.jobs) + 1}"
        self.jobs[job_id] = {"kind": kind, "status": status}
        return job_id

    def update_job(self, job_id, status=None, progress=None, result=None):  # noqa: ANN001, ANN201
        job = self.jobs.setdefault(job_id, {})
        for key, value in (("status", status), ("progress", progress), ("result", result)):
            if value is not None:
                job[key] = value

    def add_watch_item(self, source, kind, key, title="", url="", data=None, ts=None):  # noqa: ANN001, ANN201
        if any(w["source"] == source and w["key"] == key for w in self.watch):
            return False
        self.watch.append({"source": source, "kind": kind, "key": key, "title": title, "url": url,
                           "data": data or {}, "ts": ts})
        return True


class FakeNotion:
    """Records Notion REST calls made through notion_client's request()."""

    def __init__(self, search_results: list | None = None, children: list | None = None) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.search_results = search_results or []
        self.children = children or []
        self._n = 0

    async def request(self, path, method, query=None, body=None, **_):  # noqa: ANN001, ANN201
        self.calls.append((method, path, body))
        if path == "search":
            return {"results": self.search_results, "has_more": False}
        if path.startswith("blocks/") and path.endswith("/children") and method == "GET":
            return {"results": self.children, "has_more": False}
        if path == "pages" and method == "POST":
            self._n += 1
            return {"id": f"page{self._n}", "url": f"https://notion.so/page{self._n}"}
        if path.endswith("/markdown"):
            return {"object": "page_markdown", "markdown": ""}
        return {}
