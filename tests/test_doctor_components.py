"""WS1 doctor component checks. Fakes only: no network, keyring or processes."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import stubs

stubs.install()

from vvhub import doctor  # noqa: E402


def fake_get(status, body=""):  # noqa: ANN001, ANN201
    calls = []

    def get(url, headers=None, timeout=3.0):  # noqa: ANN001, ANN202
        calls.append((url, headers or {}))
        return status, body

    get.calls = calls
    return get


class FreeLLMAPITests(unittest.TestCase):
    def test_down(self) -> None:
        ok, detail = doctor.freellmapi_status(get=fake_get(None))
        self.assertFalse(ok)
        self.assertIn("FreeLLMAPI.exe", detail)

    def test_listening_even_when_401(self) -> None:
        self.assertTrue(doctor.freellmapi_status(get=fake_get(401))[0])

    def test_key_missing(self) -> None:
        ok, detail = doctor.freellmapi_key_status(get=fake_get(200), secret=lambda n: None)
        self.assertFalse(ok)
        self.assertIn("freellmapi_key", detail)

    def test_key_sent_and_models_counted(self) -> None:
        get = fake_get(200, json.dumps({"data": [{"id": "a"}, {"id": "b"}]}))
        ok, detail = doctor.freellmapi_key_status(get=get, secret=lambda n: "k1")
        self.assertTrue(ok)
        self.assertEqual(detail, "2 models")
        self.assertEqual(get.calls[0][1]["Authorization"], "Bearer k1")

    def test_key_rejected(self) -> None:
        ok, detail = doctor.freellmapi_key_status(get=fake_get(401), secret=lambda n: "k1")
        self.assertFalse(ok)
        self.assertIn("401", detail)

    def test_no_provider_keys(self) -> None:
        ok, detail = doctor.freellmapi_key_status(get=fake_get(200, '{"data": []}'), secret=lambda n: "k")
        self.assertFalse(ok)
        self.assertIn("provider keys", detail)


class OpenCLITests(unittest.TestCase):
    def test_not_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(doctor.opencli_status(root=Path(tmp), which=lambda n: "node")[0])

    def test_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "venvs" / "node" / "node_modules" / "@jackwener" / "opencli"
            (pkg / "dist" / "src").mkdir(parents=True)
            (pkg / "dist" / "src" / "main.js").write_text("", encoding="utf-8")
            (pkg / "package.json").write_text('{"version": "1.8.8"}', encoding="utf-8")
            self.assertEqual(doctor.opencli_status(root=Path(tmp), which=lambda n: "node"),
                             (True, "opencli 1.8.8"))
            self.assertFalse(doctor.opencli_status(root=Path(tmp), which=lambda n: None)[0])

    def test_extension(self) -> None:
        self.assertFalse(doctor.opencli_extension_status(get=fake_get(None))[0])
        off = fake_get(200, '{"extensionConnected": false}')
        ok, detail = doctor.opencli_extension_status(get=off)
        self.assertFalse(ok)
        self.assertIn("edge://extensions", detail)
        self.assertEqual(off.calls[0][1], {"X-OpenCLI": "1"})
        on = fake_get(200, '{"extensionConnected": true, "daemonVersion": "1.8.8"}')
        self.assertTrue(doctor.opencli_extension_status(get=on)[0])


class WindowsMCPTests(unittest.TestCase):
    def make(self, root: Path, python="3.13.15", version="0.8.5",
             exclude='["PowerShell", "Registry", "FileSystem"]') -> None:  # noqa: ANN001
        venv = root / "venvs" / "windows-mcp"
        (venv / "Scripts").mkdir(parents=True)
        (venv / "Scripts" / "windows-mcp.exe").write_text("", encoding="utf-8")
        (venv / "pyvenv.cfg").write_text(f"home = x\nversion_info = {python}\n", encoding="utf-8")
        (venv / "Lib" / "site-packages" / f"windows_mcp-{version}.dist-info").mkdir(parents=True)
        (venv / "config.toml").write_text(f"[tools]\nexclude = {exclude}\n", encoding="utf-8")

    def test_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.make(Path(tmp))
            self.assertTrue(doctor.windows_mcp_status(Path(tmp))[0])

    def test_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(doctor.windows_mcp_status(Path(tmp))[0])

    def test_wrong_python_version_or_exclusions(self) -> None:
        for kw, word in (({"python": "3.14.0"}, "3.13"), ({"version": "0.8.6"}, "pinned"),
                         ({"exclude": '["Registry"]'}, "PowerShell")):
            with tempfile.TemporaryDirectory() as tmp:
                self.make(Path(tmp), **kw)
                ok, detail = doctor.windows_mcp_status(Path(tmp))
                self.assertFalse(ok)
                self.assertIn(word, detail)


class AgentReachTests(unittest.TestCase):
    def run_with(self, stdout: str) -> tuple[bool, str]:
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("agent-reach.exe", "agent-reach"):
                (Path(tmp) / name).write_text("", encoding="utf-8")
            seen = {}

            def run(args, **kw):  # noqa: ANN001, ANN003, ANN202
                seen["args"], seen["timeout"] = args, kw.get("timeout")
                return subprocess.CompletedProcess(args, 0, stdout, "")

            result = doctor.agent_reach_status(run=run, scripts=Path(tmp))
            self.assertEqual(seen["args"][1:], ["doctor", "--json"])
            self.assertTrue(seen["timeout"])
            return result

    def test_web_ok(self) -> None:
        ok, detail = self.run_with('{"web": {"status": "ok"}, "rss": {"status": "ok"}, "x": {"status": "off"}}')
        self.assertTrue(ok)
        self.assertIn("2/3", detail)

    def test_web_down_or_garbage(self) -> None:
        self.assertFalse(self.run_with('{"web": {"status": "off"}}')[0])
        self.assertFalse(self.run_with("not json")[0])


class LayaTests(unittest.TestCase):
    def test_not_installed(self) -> None:
        self.assertFalse(doctor.laya_status(has=lambda n: None)[0])

    def test_model_missing_then_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ok, _ = doctor.laya_status(has=lambda n: object(), hf_home=tmp,
                                       tier=lambda: "gpu", onnx=lambda: None)
            self.assertFalse(ok)
            (Path(tmp) / "hub" / doctor.LAYA_REPO_DIR / "snapshots" / "abc").mkdir(parents=True)
            ok, detail = doctor.laya_status(has=lambda n: object(), hf_home=tmp,
                                            tier=lambda: "onnx", onnx=lambda: "m.onnx")
            self.assertTrue(ok)
            self.assertIn("tier onnx", detail)


class SecretChecksTests(unittest.TestCase):
    def test_secret_status(self) -> None:
        self.assertEqual(doctor.secret_status("n", "how", secret=lambda n: "v"), (True, "set"))
        self.assertFalse(doctor.secret_status("n", "how", secret=lambda n: None)[0])

    def test_user_checks_flagged(self) -> None:
        user = {c.name for c in doctor.CHECKS if c.needs_user}
        self.assertTrue({"freellmapi key", "opencli edge extension", "notion token",
                         "telegram token"} <= user)
        self.assertNotIn("windows-mcp", user)


if __name__ == "__main__":
    unittest.main()
