"""GitHub skill: gh CLI + git, driven by voice through the hub.

Builds on the `gh` CLI (logged in as the user) and plain git; this module is
glue only. Every command is an argument list handed to the runner -- never a
shell string -- and user-supplied names are validated so they can't turn into
options.

Safety (TASK.md rules 10 and 13):
- create repo, push and PR are critical: `run()` refuses them unless the
  approval passed in is approved. A decision can make any action critical,
  never the reverse.
- commit and push refuse the default branch (and main/master always), so the
  only way to change a default branch is a reviewed PR.
- commit stages tracked changes only (`git add -u`), never `add .`/`-A`, so
  stray untracked files (secrets, scratch files) are never swept in.
- push is never forced.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
from typing import Any, Awaitable, Callable

from ..schemas import Plan, Result
from .base import Skill

Runner = Callable[..., Awaitable[tuple[int, str, str]]]

ALWAYS_PROTECTED = {"main", "master"}
_FALLBACK_DEFAULTS = {"main", "master", "trunk"}
_NAME_PART = re.compile(r"^[a-z0-9_][a-z0-9._-]*$")
_BAD_REF = re.compile(r"[\s~^:?*\[\\\x00-\x1f\x7f]")


async def subprocess_runner(argv: list[str], cwd: str | None = None, *,
                            timeout: float = 90.0, _run=subprocess.run) -> tuple[int, str, str]:
    """Run argv (a list) without a shell; returns (returncode, stdout, stderr)."""
    exe = shutil.which(argv[0])
    if exe is None:
        raise FileNotFoundError(argv[0])
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GH_PROMPT_DISABLED="1", NO_COLOR="1")
    kwargs: dict[str, Any] = dict(cwd=cwd, env=env, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=timeout)
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = await asyncio.to_thread(_run, [exe, *argv[1:]], **kwargs)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def repo_name(spoken: str | None) -> str | None:
    """"My Cool Project" -> "my-cool-project"; "owner/My Repo" -> "owner/my-repo".

    Returns None for anything that isn't a plain GitHub name (options, paths,
    shell metacharacters, empty, too long).
    """
    text = (spoken or "").strip()
    if not text or len(text) > 100:
        return None
    parts = text.split("/")
    if len(parts) > 2:
        return None
    out = []
    for part in parts:
        part = re.sub(r"\s+", "-", part.strip()).lower()
        if not _NAME_PART.match(part) or part in (".", ".."):
            return None
        out.append(part)
    return "/".join(out)


def branch_name(spoken: str | None) -> str | None:
    """Spoken branch -> a valid, option-proof git ref name, or None."""
    text = re.sub(r"\s+", "-", (spoken or "").strip()).lower()
    if (not text or len(text) > 100 or text.startswith(("-", "/", ".")) or text.endswith(("/", ".", ".lock"))
            or ".." in text or "//" in text or "@{" in text or _BAD_REF.search(text) or text == "head"):
        return None
    return text


def _approved(approval: Any) -> bool:
    if approval is None:
        return False
    if isinstance(approval, dict):
        return approval.get("status") == "approved" or approval.get("approved") is True
    status = getattr(approval, "status", None)
    return status == "approved" or (status is None and getattr(approval, "approved", False) is True)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class GitError(Exception):
    pass


class GitHubSkill(Skill):
    name = "github"
    category = "github"
    actions = {
        "status": "say the current branch and changed files of the repo",
        "list_prs": "list open pull requests",
        "list_repos": "list my GitHub repositories",
        "create_branch": "create and switch to a new git branch",
        "commit": "commit tracked changes on the current (non-default) branch",
        "push": "push the current branch to GitHub",
        "create_repo": "create a new GitHub repository",
        "create_pr": "open a pull request from the current branch",
    }
    critical_actions = {"push", "create_repo", "create_pr"}

    def __init__(self, runner: Runner | None = None, repo_path: str | None = None) -> None:
        super().__init__()
        self.runner = runner or subprocess_runner
        self.repo_path = repo_path

    # ---- helpers -------------------------------------------------------
    async def _exec(self, argv: list[str], cwd: str | None = None) -> str:
        try:
            rc, out, err = await self.runner(argv, cwd=cwd)
        except FileNotFoundError:
            raise GitError(f"{argv[0]} is not installed or not on PATH.") from None
        except subprocess.TimeoutExpired:
            raise GitError(f"{argv[0]} timed out.") from None
        if rc != 0:
            detail = (err or out).strip().splitlines()
            raise GitError(f"{' '.join(argv[:3])} failed: {detail[-1] if detail else f'exit {rc}'}")
        return out

    async def _branch(self, cwd: str) -> str:
        return (await self._exec(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)).strip()

    async def _default_branch(self, cwd: str) -> str | None:
        try:
            ref = (await self._exec(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd)).strip()
        except GitError:
            return None
        return ref.split("/", 1)[1] if "/" in ref else ref or None

    async def _remote(self, cwd: str) -> str:
        remotes = (await self._exec(["git", "remote"], cwd)).split()
        if not remotes:
            raise GitError("This repo has no remote to push to.")
        return "origin" if "origin" in remotes else remotes[0]

    async def _feature_branch(self, cwd: str) -> tuple[str, str]:
        """(current branch, default branch); raises if current is protected."""
        branch = await self._branch(cwd)
        default = await self._default_branch(cwd)
        if branch in ("HEAD", ""):
            raise GitError("You're on a detached HEAD; switch to a branch first.")
        protected = ALWAYS_PROTECTED | ({default} if default else _FALLBACK_DEFAULTS)
        if branch in protected:
            raise GitError(f"You're on {branch}, the default branch. Create a branch first; "
                           "I only commit and push on other branches.")
        return branch, default or "main"

    def _path(self, plan: Plan) -> str | None:
        return plan.args.get("path") or self.repo_path

    # ---- Skill API -------------------------------------------------------
    async def plan(self, decision: Any, context: Any = None) -> Plan:
        action = _get(decision, "action", "") or ""
        args = dict(_get(decision, "args", None) or {})
        target = _get(decision, "target", "") or ""
        if target and "target" not in args:
            args["target"] = target
        repo = _get(context or {}, "repo_path", None)
        if repo and "path" not in args:
            args["path"] = repo
        critical = action in self.critical_actions or bool(_get(decision, "critical", False)) \
            or bool(_get(decision, "needs_approval", False))
        plan = Plan(skill=self.name, action=action, args=args, preview="", critical=critical)
        plan.preview = await self._preview(plan)
        return plan

    async def _preview(self, plan: Plan) -> str:
        a, args = plan.action, plan.args
        if a == "create_repo":
            name = repo_name(args.get("target") or args.get("name")) or repr(args.get("target"))
            return f"Create a {self._visibility(args)} GitHub repo {name}"
        branch = ""
        path = self._path(plan)
        if a in ("push", "create_pr") and path:
            try:
                branch = await self._branch(path)
            except GitError:
                branch = ""
        if a == "push":
            return f"Push {branch or 'the current branch'} to GitHub"
        if a == "create_pr":
            title = args.get("title") or args.get("target") or branch
            return f"Open a pull request from {branch or 'the current branch'}: {title}"
        if a == "commit":
            return f"Commit tracked changes: {args.get('message') or '(message from file names)'}"
        if a == "create_branch":
            return f"Create branch {branch_name(args.get('target') or args.get('name')) or '?'}"
        return self.actions.get(a, a)

    @staticmethod
    def _visibility(args: dict) -> str:
        return "public" if str(args.get("visibility", "")).lower() == "public" else "private"

    async def run(self, plan: Plan, approval: Any = None, dry_run: bool = False) -> Result:
        handler = getattr(self, f"_do_{plan.action}", None)
        if plan.action not in self.actions or handler is None:
            return Result(ok=False, text=f"I can't do '{plan.action}' on GitHub.", speak=True, data={})
        critical = plan.critical or plan.action in self.critical_actions
        if critical and not dry_run and not _approved(approval):
            return Result(ok=False, text=f"Not approved, so I didn't: {plan.preview}.", speak=True,
                          data={"needs_approval": True})
        try:
            return await handler(plan, dry_run)
        except GitError as exc:
            return Result(ok=False, text=str(exc), speak=True, data={})

    async def _mutate(self, argv: list[str], cwd: str | None, dry_run: bool, done: str,
                      planned: list[list[str]] | None = None) -> Result:
        planned = (planned or []) + [argv]
        if dry_run:
            return Result(ok=True, text=f"Would run: {' '.join(argv)}", speak=False, data={"argv": planned})
        out = await self._exec(argv, cwd)
        return Result(ok=True, text=done, speak=True, data={"argv": planned, "output": out.strip()})

    def _need_path(self, plan: Plan) -> str:
        path = self._path(plan)
        if not path:
            raise GitError("Which repo? I don't have a repo folder for that.")
        return path

    # ---- actions -----------------------------------------------------------
    async def _do_status(self, plan: Plan, dry_run: bool) -> Result:
        path = self._need_path(plan)
        out = await self._exec(["git", "status", "--porcelain=v1", "--branch"], path)
        lines = out.splitlines()
        head = lines[0][3:] if lines and lines[0].startswith("## ") else "unknown branch"
        changed = len([ln for ln in lines[1:] if ln.strip()])
        return Result(ok=True, text=f"On {head.split('...')[0]}, {changed} changed file{'s' * (changed != 1)}.",
                      speak=True, data={"status": out})

    async def _do_list_prs(self, plan: Plan, dry_run: bool) -> Result:
        fields = "number,title,url,author"
        path = self._path(plan)
        if path:
            argv = ["gh", "pr", "list", "--state", "open", "--limit", "10", "--json", fields]
        else:
            argv = ["gh", "search", "prs", "--author", "@me", "--state", "open", "--limit", "10",
                    "--json", "number,title,url,author,repository"]
        prs = json.loads(await self._exec(argv, path) or "[]")
        if not prs:
            return Result(ok=True, text="No open pull requests.", speak=True, data={"prs": []})
        text = "; ".join(f"#{p.get('number')} {p.get('title')}" for p in prs[:5])
        return Result(ok=True, text=f"{len(prs)} open: {text}", speak=True, data={"prs": prs})

    async def _do_list_repos(self, plan: Plan, dry_run: bool) -> Result:
        repos = json.loads(await self._exec(
            ["gh", "repo", "list", "--limit", "20", "--json", "nameWithOwner,visibility,updatedAt"]) or "[]")
        names = [r.get("nameWithOwner", "") for r in repos]
        return Result(ok=True, text=f"{len(names)} repos: " + ", ".join(names[:8]), speak=True,
                      data={"repos": repos})

    async def _do_create_branch(self, plan: Plan, dry_run: bool) -> Result:
        path = self._need_path(plan)
        name = branch_name(plan.args.get("target") or plan.args.get("name"))
        if not name:
            raise GitError("That isn't a usable branch name.")
        return await self._mutate(["git", "switch", "-c", name], path, dry_run, f"Created branch {name}.")

    async def _do_commit(self, plan: Plan, dry_run: bool) -> Result:
        path = self._need_path(plan)
        branch, _ = await self._feature_branch(path)
        add = ["git", "add", "-u"]
        if dry_run:
            message = plan.args.get("message") or "(from file names)"
            return Result(ok=True, text=f"Would commit on {branch}", speak=False,
                          data={"argv": [add, ["git", "commit", "-m", message]]})
        await self._exec(add, path)
        files = [f for f in (await self._exec(["git", "diff", "--cached", "--name-only"], path)).splitlines() if f]
        if not files:
            raise GitError("Nothing to commit.")
        message = (plan.args.get("message") or "").strip() or _message_from(files)
        return await self._mutate(["git", "commit", "-m", message], path, False,
                                  f"Committed {len(files)} file{'s' * (len(files) != 1)} on {branch}.", [add])

    async def _do_push(self, plan: Plan, dry_run: bool) -> Result:
        path = self._need_path(plan)
        branch, _ = await self._feature_branch(path)
        remote = await self._remote(path)
        return await self._mutate(["git", "push", "-u", remote, branch], path, dry_run,
                                  f"Pushed {branch} to {remote}.")

    async def _do_create_repo(self, plan: Plan, dry_run: bool) -> Result:
        name = repo_name(plan.args.get("target") or plan.args.get("name"))
        if not name:
            raise GitError("That isn't a usable repository name.")
        argv = ["gh", "repo", "create", name, f"--{self._visibility(plan.args)}"]
        if plan.args.get("description"):
            argv += ["--description", str(plan.args["description"])]
        return await self._mutate(argv, None, dry_run, f"Created {self._visibility(plan.args)} repo {name}.")

    async def _do_create_pr(self, plan: Plan, dry_run: bool) -> Result:
        path = self._need_path(plan)
        branch, default = await self._feature_branch(path)
        title = (plan.args.get("title") or plan.args.get("target") or branch).strip()
        body = plan.args.get("body") or ""
        base = plan.args.get("base") or default
        if branch_name(base) != base.lower():
            raise GitError("That isn't a usable base branch.")
        argv = ["gh", "pr", "create", "--base", base, "--head", branch, "--title", title, "--body", body]
        result = await self._mutate(argv, path, dry_run, "Opened the pull request.")
        url = result.data.get("output", "").splitlines()[-1:] if not dry_run else []
        if url:
            result.text = f"Opened the pull request: {url[0]}"
            result.data["url"] = url[0]
        return result


def _message_from(files: list[str]) -> str:
    names = [os.path.basename(f) for f in files]
    head = ", ".join(names[:3])
    return f"Update {head}" + (f" and {len(names) - 3} more" if len(names) > 3 else "")


SKILL = GitHubSkill()
