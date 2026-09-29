"""GitHub skill (vvhub.skills.github).

What matters: every command is an argument list (never a shell string), the
critical actions (create repo, push, PR) never run without an approved
approval, commits and pushes refuse the default branch, and user-supplied
names can't smuggle in options. Nothing here runs git or gh: a fake runner
records the argv lists and replays canned output.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vvhub.skills import github  # noqa: E402


class FakeRunner:
    """Replays canned (rc, stdout, stderr) keyed by an argv prefix."""

    def __init__(self, replies: dict[tuple[str, ...], tuple[int, str, str]] | None = None):
        self.replies = dict(replies or {})
        self.calls: list[tuple[list[str], str | None]] = []

    async def __call__(self, argv, cwd=None):
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv), argv
        self.calls.append((list(argv), cwd))
        best = None
        for prefix, reply in self.replies.items():
            if tuple(argv[: len(prefix)]) == prefix and (best is None or len(prefix) > len(best[0])):
                best = (prefix, reply)
        return best[1] if best else (0, "", "")

    def argvs(self):
        return [argv for argv, _ in self.calls]


def repo_runner(branch="feature/x", default="main", extra=None):
    replies = {
        ("git", "rev-parse", "--abbrev-ref", "HEAD"): (0, branch + "\n", ""),
        ("git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"): (0, f"origin/{default}\n", ""),
        ("git", "remote"): (0, "origin\n", ""),
        ("git", "diff", "--cached", "--name-only"): (0, "a.py\nb.py\n", ""),
        ("git", "status", "--porcelain=v1", "--branch"): (0, f"## {branch}\n M a.py\n", ""),
    }
    replies.update(extra or {})
    return FakeRunner(replies)


def run(coro):
    return asyncio.run(coro)


def approved():
    return SimpleNamespace(status="approved", approved=True)


def denied():
    return SimpleNamespace(status="denied", approved=False)


def decision(action, target="", **args):
    return {"category": "github", "action": action, "target": target, "args": args,
            "confidence": 0.9, "risk": 0.1, "critical": False, "needs_approval": False}


class InterfaceTests(unittest.TestCase):
    def test_skill_shape(self):
        skill = github.SKILL
        self.assertEqual(skill.name, "github")
        self.assertEqual(skill.category, "github")
        for action in ("status", "list_prs", "list_repos", "create_branch", "commit",
                       "push", "create_repo", "create_pr"):
            self.assertIn(action, skill.actions)
        self.assertEqual(skill.critical_actions, {"push", "create_repo", "create_pr"})

    def test_no_shell_strings_in_source(self):
        source = Path(github.__file__).read_text(encoding="utf-8")
        self.assertNotIn("shell=True", source)
        self.assertNotIn("os.system", source)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.skill = github.GitHubSkill(runner=repo_runner(), repo_path="C:/work/demo")

    def test_critical_plans_are_marked(self):
        for action in ("push", "create_pr"):
            plan = run(self.skill.plan(decision(action, title="T"), {}))
            self.assertTrue(plan.critical, action)
        plan = run(self.skill.plan(decision("create_repo", "demo-repo"), {}))
        self.assertTrue(plan.critical)
        self.assertIn("demo-repo", plan.preview)
        self.assertIn("private", plan.preview)

    def test_decision_cannot_downgrade_critical(self):
        d = decision("push")
        d["critical"] = False
        d["needs_approval"] = False
        self.assertTrue(run(self.skill.plan(d, {})).critical)

    def test_decision_can_escalate(self):
        d = decision("status")
        d["critical"] = True
        self.assertTrue(run(self.skill.plan(d, {})).critical)

    def test_small_actions_not_critical(self):
        for action in ("status", "list_prs", "list_repos", "commit", "create_branch"):
            plan = run(self.skill.plan(decision(action, "topic", message="m"), {}))
            self.assertFalse(plan.critical, action)

    def test_plan_accepts_object_decision(self):
        d = SimpleNamespace(action="status", target="", critical=False, args={})
        plan = run(self.skill.plan(d, {}))
        self.assertEqual(plan.action, "status")

    def test_plan_accepts_schema_decision_and_context_repo(self):
        from vvhub.schemas import Decision

        skill = github.GitHubSkill(runner=repo_runner())
        plan = run(skill.plan(Decision(category="github", action="push"), {"repo_path": "C:/ctx"}))
        self.assertTrue(plan.critical)
        self.assertEqual(plan.args["path"], "C:/ctx")

    def test_discovered(self):
        from vvhub.skills import discover

        found = discover()
        self.assertIn("github", found)
        self.assertIn("watchers", found)

    def test_unknown_action(self):
        plan = run(self.skill.plan(decision("delete_repo", "x"), {}))
        result = run(self.skill.run(plan))
        self.assertFalse(result.ok)


class CriticalGateTests(unittest.TestCase):
    def test_push_without_approval_does_nothing(self):
        runner = repo_runner()
        skill = github.GitHubSkill(runner=runner, repo_path="C:/r")
        plan = run(skill.plan(decision("push"), {}))
        for approval in (None, denied()):
            result = run(skill.run(plan, approval=approval))
            self.assertFalse(result.ok)
        self.assertFalse(any(a[:2] == ["git", "push"] for a in runner.argvs()))

    def test_push_with_approval(self):
        runner = repo_runner()
        skill = github.GitHubSkill(runner=runner, repo_path="C:/r")
        plan = run(skill.plan(decision("push"), {}))
        result = run(skill.run(plan, approval=approved()))
        self.assertTrue(result.ok, result.text)
        pushes = [a for a in runner.argvs() if a[:2] == ["git", "push"]]
        self.assertEqual(pushes, [["git", "push", "-u", "origin", "feature/x"]])
        self.assertTrue(all("--force" not in a and "-f" not in a for a in pushes))

    def test_push_refuses_default_branch_even_approved(self):
        runner = repo_runner(branch="main")
        skill = github.GitHubSkill(runner=runner, repo_path="C:/r")
        plan = run(skill.plan(decision("push"), {}))
        result = run(skill.run(plan, approval=approved()))
        self.assertFalse(result.ok)
        self.assertIn("main", result.text)
        self.assertFalse(any(a[:2] == ["git", "push"] for a in runner.argvs()))

    def test_approval_status_string_only(self):
        runner = repo_runner()
        skill = github.GitHubSkill(runner=runner, repo_path="C:/r")
        plan = run(skill.plan(decision("push"), {}))
        self.assertTrue(run(skill.run(plan, approval={"status": "approved"})).ok)
        self.assertFalse(run(skill.run(plan, approval={"status": "expired"})).ok)

    def test_create_repo_private_by_default(self):
        runner = FakeRunner({("gh", "repo", "create"): (0, "https://github.com/me/demo\n", "")})
        skill = github.GitHubSkill(runner=runner, repo_path=None)
        plan = run(skill.plan(decision("create_repo", "demo"), {}))
        self.assertFalse(run(skill.run(plan)).ok)
        self.assertEqual(runner.calls, [])
        result = run(skill.run(plan, approval=approved()))
        self.assertTrue(result.ok, result.text)
        self.assertEqual(runner.argvs()[-1], ["gh", "repo", "create", "demo", "--private"])

    def test_create_repo_public_only_when_asked(self):
        runner = FakeRunner()
        skill = github.GitHubSkill(runner=runner)
        plan = run(skill.plan(decision("create_repo", "demo", visibility="public"), {}))
        self.assertIn("public", plan.preview)
        run(skill.run(plan, approval=approved()))
        self.assertEqual(runner.argvs()[-1], ["gh", "repo", "create", "demo", "--public"])

    def test_create_pr(self):
        runner = repo_runner(extra={("gh", "pr", "create"): (0, "https://github.com/me/r/pull/3\n", "")})
        skill = github.GitHubSkill(runner=runner, repo_path="C:/r")
        plan = run(skill.plan(decision("create_pr", title="Add thing", body="Body"), {}))
        result = run(skill.run(plan, approval=approved()))
        self.assertTrue(result.ok, result.text)
        pr = [a for a in runner.argvs() if a[:3] == ["gh", "pr", "create"]][0]
        self.assertEqual(pr, ["gh", "pr", "create", "--base", "main", "--head", "feature/x",
                              "--title", "Add thing", "--body", "Body"])
        self.assertIn("pull/3", result.text)

    def test_create_pr_from_default_branch_refused(self):
        runner = repo_runner(branch="main")
        skill = github.GitHubSkill(runner=runner, repo_path="C:/r")
        plan = run(skill.plan(decision("create_pr", title="x"), {}))
        self.assertFalse(run(skill.run(plan, approval=approved())).ok)

    def test_dry_run_never_executes_mutations(self):
        runner = repo_runner()
        skill = github.GitHubSkill(runner=runner, repo_path="C:/r")
        plan = run(skill.plan(decision("push"), {}))
        result = run(skill.run(plan, dry_run=True))
        self.assertTrue(result.ok)
        self.assertIn(["git", "push", "-u", "origin", "feature/x"], result.data["argv"])
        self.assertFalse(any(a[:2] == ["git", "push"] for a in runner.argvs()))


class CommitTests(unittest.TestCase):
    def test_commit_on_feature_branch(self):
        runner = repo_runner()
        skill = github.GitHubSkill(runner=runner, repo_path="C:/r")
        plan = run(skill.plan(decision("commit", message="Fix the parser"), {}))
        result = run(skill.run(plan))
        self.assertTrue(result.ok, result.text)
        argvs = runner.argvs()
        self.assertIn(["git", "add", "-u"], argvs)
        self.assertIn(["git", "commit", "-m", "Fix the parser"], argvs)
        self.assertTrue(all(cwd == "C:/r" for _, cwd in runner.calls))
        self.assertNotIn(["git", "add", "."], argvs)
        self.assertNotIn(["git", "add", "-A"], argvs)

    def test_commit_refused_on_default_branch(self):
        for branch, default in (("main", "main"), ("master", "master"), ("trunk", "trunk")):
            runner = repo_runner(branch=branch, default=default)
            skill = github.GitHubSkill(runner=runner, repo_path="C:/r")
            plan = run(skill.plan(decision("commit", message="m"), {}))
            result = run(skill.run(plan))
            self.assertFalse(result.ok, branch)
            self.assertFalse(any(a[:2] == ["git", "commit"] for a in runner.argvs()))

    def test_default_branch_fallback_when_no_origin_head(self):
        runner = repo_runner(branch="master", extra={
            ("git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"): (1, "", "not a symbolic ref")})
        skill = github.GitHubSkill(runner=runner, repo_path="C:/r")
        plan = run(skill.plan(decision("commit", message="m"), {}))
        self.assertFalse(run(skill.run(plan)).ok)

    def test_commit_refused_detached_head(self):
        runner = repo_runner(branch="HEAD")
        skill = github.GitHubSkill(runner=runner, repo_path="C:/r")
        plan = run(skill.plan(decision("commit", message="m"), {}))
        self.assertFalse(run(skill.run(plan)).ok)

    def test_commit_default_message_from_files(self):
        runner = repo_runner()
        skill = github.GitHubSkill(runner=runner, repo_path="C:/r")
        plan = run(skill.plan(decision("commit"), {}))
        run(skill.run(plan))
        commit = [a for a in runner.argvs() if a[:2] == ["git", "commit"]][0]
        self.assertEqual(commit, ["git", "commit", "-m", "Update a.py, b.py"])

    def test_commit_nothing_staged(self):
        runner = repo_runner(extra={("git", "diff", "--cached", "--name-only"): (0, "", "")})
        skill = github.GitHubSkill(runner=runner, repo_path="C:/r")
        result = run(skill.run(run(skill.plan(decision("commit", message="m"), {}))))
        self.assertFalse(result.ok)
        self.assertIn("nothing", result.text.lower())

    def test_no_repo_path(self):
        skill = github.GitHubSkill(runner=FakeRunner(), repo_path=None)
        result = run(skill.run(run(skill.plan(decision("commit", message="m"), {}))))
        self.assertFalse(result.ok)
        self.assertIn("repo", result.text.lower())

    def test_create_branch(self):
        runner = repo_runner(branch="main")
        skill = github.GitHubSkill(runner=runner, repo_path="C:/r")
        result = run(skill.run(run(skill.plan(decision("create_branch", "fix/login bug"), {}))))
        self.assertTrue(result.ok, result.text)
        self.assertIn(["git", "switch", "-c", "fix/login-bug"], runner.argvs())


class ValidationTests(unittest.TestCase):
    def test_names_cannot_be_options(self):
        runner = FakeRunner()
        skill = github.GitHubSkill(runner=runner, repo_path="C:/r")
        for bad in ("--help", "-rf", "a b;c", "../x", "", "x" * 200):
            plan = run(skill.plan(decision("create_repo", bad), {}))
            result = run(skill.run(plan, approval=approved()))
            self.assertFalse(result.ok, bad)
        self.assertEqual(runner.calls, [])

    def test_spoken_repo_name_normalised(self):
        self.assertEqual(github.repo_name("My Cool Project"), "my-cool-project")
        self.assertEqual(github.repo_name("owner/My Repo"), "owner/my-repo")
        self.assertIsNone(github.repo_name("-x"))

    def test_branch_name(self):
        self.assertEqual(github.branch_name("fix login bug"), "fix-login-bug")
        self.assertIsNone(github.branch_name("--force"))
        self.assertIsNone(github.branch_name("a..b"))
        self.assertIsNone(github.branch_name("x.lock"))

    def test_commit_message_starting_with_dash_is_safe(self):
        runner = repo_runner()
        skill = github.GitHubSkill(runner=runner, repo_path="C:/r")
        run(skill.run(run(skill.plan(decision("commit", message="-am oops"), {}))))
        commit = [a for a in runner.argvs() if a[:2] == ["git", "commit"]][0]
        # -m takes the next argv as its value, so a leading dash is inert.
        self.assertEqual(commit, ["git", "commit", "-m", "-am oops"])


class ReadOnlyTests(unittest.TestCase):
    def test_list_prs(self):
        runner = FakeRunner({("gh", "pr", "list"): (
            0, '[{"number": 4, "title": "Add X", "url": "u", "author": {"login": "bob"}}]', "")})
        skill = github.GitHubSkill(runner=runner, repo_path="C:/r")
        result = run(skill.run(run(skill.plan(decision("list_prs"), {}))))
        self.assertTrue(result.ok)
        self.assertIn("Add X", result.text)
        self.assertEqual(runner.argvs()[0][:3], ["gh", "pr", "list"])

    def test_list_repos(self):
        runner = FakeRunner({("gh", "repo", "list"): (0, '[{"nameWithOwner": "me/a"}, {"nameWithOwner": "me/b"}]', "")})
        skill = github.GitHubSkill(runner=runner)
        result = run(skill.run(run(skill.plan(decision("list_repos"), {}))))
        self.assertTrue(result.ok)
        self.assertIn("me/a", result.text)

    def test_status(self):
        skill = github.GitHubSkill(runner=repo_runner(), repo_path="C:/r")
        result = run(skill.run(run(skill.plan(decision("status"), {}))))
        self.assertTrue(result.ok)
        self.assertIn("feature/x", result.text)

    def test_gh_failure_reported(self):
        runner = FakeRunner({("gh", "repo", "list"): (1, "", "HTTP 401: Bad credentials")})
        skill = github.GitHubSkill(runner=runner)
        result = run(skill.run(run(skill.plan(decision("list_repos"), {}))))
        self.assertFalse(result.ok)
        self.assertIn("401", result.text)

    def test_missing_tool_degrades(self):
        async def missing(argv, cwd=None):
            raise FileNotFoundError(argv[0])

        skill = github.GitHubSkill(runner=missing)
        result = run(skill.run(run(skill.plan(decision("list_repos"), {}))))
        self.assertFalse(result.ok)
        self.assertIn("gh", result.text)


class RunnerTests(unittest.TestCase):
    def test_default_runner_uses_arg_list(self):
        seen = {}

        def fake_run(argv, **kwargs):
            seen["argv"] = argv
            seen.update(kwargs)
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        rc, out, _ = run(github.subprocess_runner(["git", "status"], cwd="C:/r", _run=fake_run))
        self.assertEqual((rc, out), (0, "ok"))
        self.assertEqual(seen["argv"][1:], ["status"])
        self.assertNotIn("shell", seen)
        self.assertEqual(seen["env"]["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(seen["env"]["GH_PROMPT_DISABLED"], "1")


if __name__ == "__main__":
    unittest.main()
