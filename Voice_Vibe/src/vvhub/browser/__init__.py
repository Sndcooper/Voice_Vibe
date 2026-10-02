"""WS3 browser layer: Edge via OpenCLI, Zen via Windows-MCP (TASK.md T14)."""

from __future__ import annotations

from .drivers import (Browsers, BrowserError, EdgeBrowser, Page, WindowsMCP, ZenBrowser,
                      detect, safe_url)
from .opencli import OpenCLI, OpenCLIError

__all__ = ["Browsers", "BrowserError", "EdgeBrowser", "OpenCLI", "OpenCLIError", "Page",
           "WindowsMCP", "ZenBrowser", "detect", "safe_url"]
