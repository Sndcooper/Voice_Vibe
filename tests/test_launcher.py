"""Launcher (vvhub.ui.launcher): hub before Voice Vibe, detached, opt-in autostart.

What matters: the hub is started only when /health gives no HTTP answer at
all (a 401 still means it's up), it is started before Voice Vibe, both are
created outside the launching shell's job (breakaway, else WMI with the
environment passed along), and login autostart is off until asked for and
writes exactly one HKCU Run value. Nothing here starts a process, opens a
socket or touches the registry: everything is injected.
"""

from __future__ import annotations

import io
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vvhub.ui import launcher  # noqa: E402


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class HealthTests(unittest.TestCase):
    def test_up_with_token(self):
        seen = {}

        def opener(req, timeout):
            seen["auth"] = req.get_header("Authorization")
            seen["url"] = req.full_url
            seen["timeout"] = timeout
            return FakeResponse(b'{"ok": true}')

        self.assertTrue(launcher.hub_up(token="T", opener=opener))
        self.assertEqual(seen["auth"], "Bearer T")
        self.assertEqual(seen["url"], "http://127.0.0.1:53874/health")
        self.assertLessEqual(seen["timeout"], 2.0)

    def test_401_still_counts_as_up(self):
        def opener(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

        self.assertTrue(launcher.hub_up(token=None, opener=opener))

    def test_refused_or_timeout_is_down(self):
        for exc in (urllib.error.URLError(ConnectionRefusedError()), TimeoutError(), OSError("x")):
            def opener(req, timeout, exc=exc):
                raise exc

            self.assertFalse(launcher.hub_up(token="T", opener=opener), exc)


class FakePopen:
    def __init__(self, fail_breakaway=False):
        self.calls = []
        self.fail_breakaway = fail_breakaway
        self.pid = 1000

    def __call__(self, argv, **kw):
        if self.fail_breakaway and kw.get("creationflags", 0) & launcher.CREATE_BREAKAWAY_FROM_JOB:
            err = OSError("Access is denied")
            err.winerror = 5
            raise err
        self.calls.append((argv, kw))
        self.pid += 1
        return self


class SpawnTests(unittest.TestCase):
    def test_breakaway_detached_no_console(self):
        popen = FakePopen()
        pid = launcher.spawn(["pythonw.exe", "-m", "vvhub", "serve"], cwd="C:/repo", env={"A": "1"},
                             popen=popen, wmi=None)
        self.assertEqual(pid, 1001)
        argv, kw = popen.calls[0]
        flags = kw["creationflags"]
        for flag in (launcher.DETACHED_PROCESS, launcher.CREATE_NEW_PROCESS_GROUP,
                     launcher.CREATE_BREAKAWAY_FROM_JOB):
            self.assertTrue(flags & flag, hex(flag))
        self.assertEqual(kw["cwd"], "C:/repo")
        self.assertEqual(kw["env"], {"A": "1"})
        self.assertTrue(kw["close_fds"])
        self.assertNotIn("shell", kw)

    def test_job_without_breakaway_falls_back_to_wmi_with_env(self):
        popen = FakePopen(fail_breakaway=True)
        seen = {}

        def wmi(argv, cwd, env):
            seen.update(argv=argv, cwd=cwd, env=env)
            return 4242

        pid = launcher.spawn(["pythonw.exe", "-m", "voicevibe"], cwd="C:/repo", env={"HF_HOME": "h"},
                             popen=popen, wmi=wmi)
        self.assertEqual(pid, 4242)
        self.assertEqual(seen["env"]["HF_HOME"], "h")
        self.assertEqual(popen.calls, [])

    def test_no_wmi_last_resort_plain_detached(self):
        popen = FakePopen(fail_breakaway=True)

        def wmi(argv, cwd, env):
            raise OSError("no pywin32")

        pid = launcher.spawn(["pythonw.exe"], cwd=None, env={}, popen=popen, wmi=wmi)
        self.assertEqual(pid, 1001)
        self.assertFalse(popen.calls[0][1]["creationflags"] & launcher.CREATE_BREAKAWAY_FROM_JOB)

    def test_wmi_command_line_quotes_paths(self):
        self.assertEqual(launcher.command_line([r"C:\a b\pythonw.exe", "-m", "voicevibe"]),
                         r'"C:\a b\pythonw.exe" -m voicevibe')


class StartTests(unittest.TestCase):
    def setUp(self):
        self.order = []

        def spawn(argv, cwd=None, env=None):
            self.order.append(argv[1:3] if argv[1] == "-m" else argv)
            self.cwd, self.env = cwd, env
            return 7

        self.spawn = spawn

    def test_hub_down_started_before_voicevibe(self):
        rc = launcher.start(["--console-free"], hub_up=lambda **kw: False, spawn=self.spawn, wait=0)
        self.assertEqual(rc, 0)
        self.assertEqual(self.order, [["-m", "vvhub"], ["-m", "voicevibe"]])
        self.assertEqual(Path(self.cwd), launcher.REPO)
        self.assertIn("HF_HOME", self.env)
        self.assertIn("UV_CACHE_DIR", self.env)

    def test_hub_up_not_started_again(self):
        launcher.start([], hub_up=lambda **kw: True, spawn=self.spawn, wait=0)
        self.assertEqual(self.order, [["-m", "voicevibe"]])

    def test_voicevibe_args_passed(self):
        seen = []

        def spawn(argv, cwd=None, env=None):
            seen.append(argv)
            return 1

        launcher.start(["--foo", "bar"], hub_up=lambda **kw: True, spawn=spawn, wait=0)
        self.assertEqual(seen[-1][-2:], ["--foo", "bar"])
        self.assertTrue(seen[-1][0].lower().endswith("pythonw.exe"))

    def test_hub_spawn_failure_still_starts_voicevibe(self):
        calls = []

        def spawn(argv, cwd=None, env=None):
            calls.append(argv)
            if "vvhub" in argv:
                raise OSError("boom")
            return 1

        self.assertEqual(launcher.start([], hub_up=lambda **kw: False, spawn=spawn, wait=0), 0)
        self.assertTrue(any("voicevibe" in a for a in calls))

    def test_voicevibe_spawn_failure_is_nonzero(self):
        def spawn(argv, cwd=None, env=None):
            raise OSError("boom")

        self.assertEqual(launcher.start([], hub_up=lambda **kw: True, spawn=spawn, wait=0), 1)

    def test_existing_env_not_overridden(self):
        env = launcher.child_env({"HF_HOME": "mine", "PATH": "p"})
        self.assertEqual(env["HF_HOME"], "mine")
        self.assertEqual(env["PATH"], "p")
        self.assertTrue(env["UV_CACHE_DIR"].endswith("uv-cache"))


class FakeReg:
    """Just the winreg calls the launcher uses."""

    HKEY_CURRENT_USER = "HKCU"
    KEY_READ, KEY_SET_VALUE, REG_SZ = 1, 2, 1

    def __init__(self):
        self.values: dict[str, str] = {}
        self.opened = []

    class _Key:
        def __init__(self, reg, path):
            self.reg, self.path = reg, path

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def OpenKey(self, root, path, reserved=0, access=0):  # noqa: N802
        self.opened.append((root, path))
        return self._Key(self, path)

    def CreateKey(self, root, path):  # noqa: N802
        return self.OpenKey(root, path)

    def QueryValueEx(self, key, name):  # noqa: N802
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):  # noqa: N802
        self.values[name] = value

    def DeleteValue(self, key, name):  # noqa: N802
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


class AutostartTests(unittest.TestCase):
    def test_off_by_default_then_on_off(self):
        reg = FakeReg()
        self.assertFalse(launcher.autostart_enabled(reg=reg))
        launcher.set_autostart(True, reg=reg)
        self.assertEqual(reg.opened[-1], ("HKCU", launcher.RUN_KEY))
        value = reg.values[launcher.RUN_VALUE]
        self.assertIn("pythonw.exe", value.lower())
        self.assertTrue(value.endswith("-m vvhub.ui.launcher start"))
        self.assertTrue(value.startswith('"'))
        self.assertTrue(launcher.autostart_enabled(reg=reg))
        launcher.set_autostart(False, reg=reg)
        self.assertFalse(launcher.autostart_enabled(reg=reg))
        launcher.set_autostart(False, reg=reg)  # idempotent

    def test_only_our_value_is_touched(self):
        reg = FakeReg()
        reg.values["OneDrive"] = "x"
        launcher.set_autostart(True, reg=reg)
        launcher.set_autostart(False, reg=reg)
        self.assertEqual(reg.values, {"OneDrive": "x"})

    def test_cli(self):
        reg = FakeReg()
        out = []
        self.assertEqual(launcher.main(["autostart", "status"], reg=reg, out=out.append), 0)
        self.assertIn("off", out[-1])
        launcher.main(["autostart", "on"], reg=reg, out=out.append)
        self.assertIn("on", out[-1])
        self.assertTrue(launcher.autostart_enabled(reg=reg))


class SetSecretTests(unittest.TestCase):
    def test_saves_valid_key_without_echoing_it(self):
        from vvhub import secrets

        vault = {}
        secrets.use_backend(vault)
        try:
            out = []
            key = "freellmapi-" + "a1b2c3" * 6
            rc = launcher.main(["set-secret", "freellmapi"], out=out.append, ask=lambda prompt: f"  {key}  ")
            self.assertEqual(rc, 0)
            self.assertEqual(vault["freellmapi_key"], key)
            self.assertIn("saved", out[-1])
            self.assertNotIn(key, " ".join(out))
            rc = launcher.main(["set-secret", "freellmapi"], out=out.append, ask=lambda prompt: "has spaces in it")
            self.assertEqual(rc, 1)
            self.assertEqual(vault["freellmapi_key"], key)
            rc = launcher.main(["set-secret", "telegram"], out=out.append, ask=lambda prompt: "")
            self.assertEqual(rc, 1)
            self.assertNotIn("telegram_bot_token", vault)
        finally:
            secrets.use_backend(None)

    def test_unknown_name(self):
        out = []
        self.assertEqual(launcher.main(["set-secret", "hub"], out=out.append, ask=lambda p: "x"), 2)
        self.assertIn("freellmapi", out[-1])


class RunBatTests(unittest.TestCase):
    """run.bat can't be executed in a unit test; check it calls the launcher."""

    def setUp(self):
        self.bat = (Path(__file__).resolve().parents[1] / "run.bat").read_text(encoding="utf-8")

    def test_background_path_uses_launcher_with_fallback(self):
        self.assertIn("-m vvhub.ui.launcher start", self.bat)
        self.assertIn('start "" "%PYW%" -m voicevibe', self.bat)  # fallback kept

    def test_console_path_ensures_hub(self):
        self.assertIn("-m vvhub.ui.launcher hub", self.bat)

    def test_autostart_flag(self):
        self.assertIn("--autostart", self.bat)

    def test_set_key_flag(self):
        self.assertIn("--set-key", self.bat)
        self.assertIn("-m vvhub.ui.launcher set-secret", self.bat)


if __name__ == "__main__":
    unittest.main()
