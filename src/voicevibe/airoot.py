"""Drive the Airoot listening overlay, a separate app, while the mic is listening.

Airoot is its own executable. It listens for plain ASCII datagrams
("show", "hide", "quit") on a localhost UDP port, so switching it costs one
loopback packet rather than a process launch per recording.

Only one Airoot instance can own the port. That is also how we tell whether it
is running: if we can bind the port ourselves, nobody else has.

Everything here is best effort. A missing executable or a dead overlay must
never interrupt dictation, so failures are logged once and otherwise ignored.
"""

from __future__ import annotations

import logging
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

# The onefile EXE unpacks itself and starts Qt before it binds the port. Commands
# sent in that window are lost, so the desired state is re-sent until it lands.
_STARTUP_GRACE = 15.0
_RESEND_INTERVAL = 0.5


class AirootBridge:
    def __init__(self, cfg: dict | None = None) -> None:
        cfg = cfg or {}
        self.port = int(cfg.get("port", 53873))
        self.quit_on_exit = bool(cfg.get("quit_on_exit", True))
        self.preload = bool(cfg.get("preload", True))

        raw = str(cfg.get("exe", "") or "").strip()
        self.exe = Path(raw).expanduser() if raw else None
        self.enabled = bool(cfg.get("enabled", False)) and sys.platform == "win32"
        if self.enabled and (self.exe is None or not self.exe.is_file()):
            log.warning(
                "[airoot] is enabled but the overlay was not found at %s; disabling it.",
                self.exe or "(no exe set)",
            )
            self.enabled = False

        self._listening = False
        self._lock = threading.Lock()
        self._launched_at: float | None = None
        self._owns_process = False
        self._stopped = threading.Event()

    # ------------------------------------------------------------------ public
    def start(self) -> None:
        """Preload the overlay hidden, so the first recording shows it instantly."""
        if self.enabled and self.preload and not self._reachable():
            self._launch()

    def set_listening(self, listening: bool) -> None:
        """Show or hide the overlay. Repeated calls with the same value are free."""
        if not self.enabled:
            return
        with self._lock:
            if listening == self._listening:
                return
            self._listening = listening
        # Relaunch if someone closed it from its own menu. Skipped during startup,
        # when the probe itself could steal the port from the launching overlay.
        if listening and not self._in_grace() and not self._reachable():
            self._launch()
        self._send("show" if listening else "hide")

    def stop(self) -> None:
        self._stopped.set()
        if not self.enabled:
            return
        self._send("hide")
        # Leave an overlay the user started themselves running; only clean up ours.
        if self._owns_process and self.quit_on_exit:
            self._send("quit")

    # --------------------------------------------------------------- internals
    def _send(self, command: str) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(command.encode("ascii"), ("127.0.0.1", self.port))
        except OSError as exc:
            log.debug("airoot %s failed: %s", command, exc)

    def _reachable(self) -> bool:
        """True if some process already owns the overlay's port."""
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.bind(("127.0.0.1", self.port))
        except OSError:
            return True
        finally:
            probe.close()
        return False

    def _in_grace(self) -> bool:
        return (
            self._launched_at is not None
            and time.monotonic() - self._launched_at < _STARTUP_GRACE
        )

    def _launch(self) -> None:
        # "start" comes up hidden; the resend loop then delivers whatever state
        # we actually want. Launching straight into "show" could leave it
        # visible if we had gone idle by the time it finished starting.
        try:
            subprocess.Popen(  # noqa: S603 - fixed configured path, shell=False
                [str(self.exe), "start"],
                shell=False,
                close_fds=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0),
            )
        except OSError as exc:
            log.warning("Could not start the Airoot overlay: %s", exc)
            self.enabled = False
            return
        self._launched_at = time.monotonic()
        self._owns_process = True
        log.info("Started the Airoot overlay (%s).", self.exe)
        threading.Thread(target=self._resend_until_ready, name="airoot", daemon=True).start()

    def _resend_until_ready(self) -> None:
        while self._in_grace() and not self._stopped.wait(_RESEND_INTERVAL):
            with self._lock:
                listening = self._listening
            self._send("show" if listening else "hide")
