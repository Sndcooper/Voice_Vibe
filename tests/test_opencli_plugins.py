"""Runs the OpenCLI plugin's own node:test suite (fake page, no browser).

Skipped when Node isn't on PATH (rule 19: optional parts degrade)."""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent / "integrations" / "opencli-plugins" / "voicevibe"


@unittest.skipIf(shutil.which("node") is None, "node not installed")
class OpenCLIPluginTest(unittest.TestCase):
    def test_node_suite_passes(self):
        proc = subprocess.run(["node", "--test", str(HERE / "opencli_plugins" / "lib.test.mjs")],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout[-3000:] + proc.stderr[-2000:])

    def test_command_files_register_under_the_voicevibe_site(self):
        for name in ("linkedin-post", "instagram-notifications", "github-notifications"):
            source = (PLUGIN / f"{name}.js").read_text(encoding="utf-8")
            self.assertIn("site: 'voicevibe'", source)
            self.assertIn(f"name: '{name}'", source)
        self.assertIn("access: 'write'", (PLUGIN / "linkedin-post.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
