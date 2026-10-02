"""Drive the Airoot listening overlay, a separate app, while the mic is listening.

Airoot is its own process (assets/airoot_overlay.py, or a PyInstaller build of
it). It listens for plain ASCII datagrams ("show", "transcribing", "hide",
"quit") on a localhost UDP port, so switching it costs one loopback packet
rather than a process launch per recording.

Only one Airoot instance can own the port. That is also how we tell whether it
is running: if we can bind the port ourselves, nobody else has.

Everything here is best effort. A missing overlay or a dead one must never
interrupt dictation, so failures are logged once and otherwise ignored.
"""

from __future__ import annotations

import json
import logging
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

# The overlay unpacks itself and starts Qt before it binds the port. Commands
# sent in that window are lost, so the desired state is re-sent until it lands.
_STARTUP_GRACE = 15.0
_RESEND_INTERVAL = 0.5

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "assets" / "airoot_overlay.py"


def _have_qt() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("PySide6") is not None
    except (ImportError, ValueError):
        return False


def _command(exe: Path | None) -> list[str] | None:
    """What starts the overlay: a built exe if there is one, else the script."""
    for built in (exe, _ROOT / "dist" / "AirootVoiceOverlay.exe"):
        if built is not None and built.is_file():
            return [str(built), "start"]
    if _SCRIPT.is_file() and _have_qt():
        python = Path(sys.executable)
        windowless = python.with_name("pythonw.exe")
        return [str(windowless if windowless.is_file() else python), str(_SCRIPT), "start"]
    return None


class AirootBridge:
    def __init__(self, cfg: dict | None = None) -> None:
        cfg = cfg or {}
        self.port = int(cfg.get("port", 53873))
        self.quit_on_exit = bool(cfg.get("quit_on_exit", True))
        self.preload = bool(cfg.get("preload", True))

        raw = str(cfg.get("exe", "") or "").strip()
        exe = Path(raw).expanduser() if raw else None
        if exe is not None and not exe.is_absolute():
            exe = _ROOT / exe
        self._launch_cmd = _command(exe) if sys.platform == "win32" else None
        self.enabled = bool(cfg.get("enabled", True)) and self._launch_cmd is not None
        if bool(cfg.get("enabled", True)) and self._launch_cmd is None:
            log.warning(
                "[airoot] is enabled but there is nothing to start it with: install "
                "PySide6 (pip install PySide6) or set [airoot].exe to a built overlay."
            )

        self._state = "idle"
        self.device: int | None = None
        self._lock = threading.Lock()
        self._launched_at: float | None = None
        self._owns_process = False
        self._stopped = threading.Event()

    # ------------------------------------------------------------------ public
    def start(self) -> None:
        """Preload the overlay hidden, so the first recording shows it instantly."""
        if self.enabled and self.preload and not self._reachable():
            self._launch()

    def set_device(self, device: object) -> None:
        """Tell the overlay which input to meter.

        The overlay would otherwise use the Windows default, which is the wrong
        one whenever that default is a loopback: its level bars sit still while
        dictation records from a real microphone.
        """
        self.device = device if isinstance(device, int) else None

    def set_state(self, state: str) -> None:
        """Drive the overlay: "listening", "busy" (transcribing), or "idle"."""
        if not self.enabled:
            return
        with self._lock:
            if state == self._state:
                return
            self._state = state
        # Relaunch if someone closed it from its own menu. Skipped during startup,
        # when the probe itself could steal the port from the launching overlay.
        if state != "idle" and not self._in_grace() and not self._reachable():
            self._launch()
        self._send(self._command_for(state))

    def stop(self) -> None:
        self._stopped.set()
        if not self.enabled:
            return
        self._send("hide")
        # Leave an overlay the user started themselves running; only clean up ours.
        if self._owns_process and self.quit_on_exit:
            self._send("quit")

    def show_transcript(self, text: str, label: str = "Recognized") -> None:
        """Tell the overlay a transcription finished (it never shows the text).

        Dropped while the logo is up and listening: the overlay treats any
        transcript as "done", fades the logo out, and set_state() never
        re-sends "show" for a state it thinks is unchanged.
        """
        if not self.enabled:
            return
        with self._lock:
            listening = self._state == "listening"
        if not listening:
            self._send(json.dumps({"event": "transcript", "text": text[:4000],
                                   "label": label}, ensure_ascii=False))

    # --------------------------------------------------------------- internals
    def _command_for(self, state: str) -> str:
        if state == "idle":
            return "hide"
        if state == "busy":
            return "transcribing"
        return "show" if self.device is None else f"show {self.device}"

    def _send(self, command: str) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(command.encode("utf-8"), ("127.0.0.1", self.port))
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
            subprocess.Popen(  # noqa: S603 - fixed local command, shell=False
                self._launch_cmd,
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
        log.info("Started the Airoot overlay (%s).", " ".join(self._launch_cmd))
        threading.Thread(target=self._resend_until_ready, name="airoot", daemon=True).start()

    def _resend_until_ready(self) -> None:
        while self._in_grace() and not self._stopped.wait(_RESEND_INTERVAL):
            with self._lock:
                state = self._state
            self._send(self._command_for(state))
