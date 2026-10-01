"""Wires the hotkey -> microphone -> transcriber -> text at the cursor.

One hotkey (Ctrl+Alt+Space) turns listening on and off. While it is on, every
time you pause, the sentence you just said is transcribed and typed into the
focused field, and the overlay animates to show what the app is doing.
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
import time

import numpy as np

from .airoot import AirootBridge
from .audio import SegmentRecorder, device_label
from .config import Config
from .feedback import Beeper, Tray
from .hotkey import HotkeyListener, physically_down
from .inserter import Inserter, focused_window
from .logs import data_dir
from .overlay import Overlay

log = logging.getLogger(__name__)

IDLE = "idle"  # not listening
LISTENING = "listening"  # mic open, waiting for you to speak
BUSY = "busy"  # transcribing what you just said


class VoiceVibe:
    # When the toggle hotkey last acted; see toggle().
    _last_toggle = float("-inf")
    TOGGLE_DEBOUNCE = 0.4

    def __init__(self, config: Config) -> None:
        self.config = config
        cont = config.continuous
        self.recorder = SegmentRecorder(
            sample_rate=int(config.audio["sample_rate"]),
            device=config.input_device,
            on_segment=self._on_segment,
            silence_duration=float(cont["silence_duration"]),
            speech_ratio=float(cont["speech_ratio"]),
            min_rms=float(cont["min_rms"]),
            min_segment=float(cont["min_segment"]),
            max_segment=float(cont["max_segment"]),
            pre_roll=float(cont["pre_roll"]),
        )
        self.inserter = Inserter(config.output)
        self.beeper = Beeper(bool(config.feedback.get("sounds", True)))
        self.tray = Tray(bool(config.feedback.get("tray_icon", True)), self.request_stop)

        self.airoot = AirootBridge(config.airoot)
        overlay_cfg = dict(config.overlay)
        # Airoot was asked for but cannot start (no PySide6, no exe): fall back to
        # the built-in orb rather than leaving no on-screen indicator at all.
        if config.airoot.get("enabled", True) and not self.airoot.enabled:
            overlay_cfg["enabled"] = True
        self.overlay = Overlay(overlay_cfg)

        # The overlay meters the same microphone dictation records from, rather
        # than whatever Windows has as the default.
        self._mic: int | str | None = config.input_device
        self.airoot.set_device(self._mic)

        self.transcriber = None
        self._jobs: queue.Queue[np.ndarray | None] = queue.Queue()
        self._job_running = False
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        # Re-checks held keys against Windows, so a release missed in an admin
        # window cannot leave ctrl+alt "held" for a later lone Space.
        self.hotkeys = HotkeyListener(check_held=physically_down)

    # ------------------------------------------------------------- indicators
    @property
    def listening(self) -> bool:
        return self.recorder.is_recording

    def _indicate(self, state: str) -> None:
        """Drive every status indicator from one place."""
        self.tray.set_state(state)
        self.overlay.set_state(state)
        self.airoot.set_state(state)

    def _resting_state(self) -> str:
        """What to show when nothing is being transcribed right now."""
        return LISTENING if self.listening else IDLE

    # -------------------------------------------------------------- listening
    def _choose_microphone(self) -> None:
        """Pick the mic again just before opening it (no stream is open yet).

        Follows the Windows default input whenever it is a real microphone,
        so switching mics in Windows or plugging in a headset takes effect the
        next time listening starts, without a restart -- and a device that
        vanished is not reused. Never a loopback such as Stereo Mix.
        """
        if self.config.input_device_pinned:
            return
        try:
            device = self.config.refresh_input_device()
        except Exception as exc:
            log.debug("could not re-check the microphone: %s", exc)
            return
        if device == self._mic:
            return
        self._mic = device
        self.recorder.device = device
        self.airoot.set_device(device)
        log.info("Microphone: %s.", device_label(device))

    def start_listening(self) -> None:
        with self._state_lock:
            if self.listening:
                return
            self._choose_microphone()
            try:
                self.recorder.start()
            except Exception as exc:
                log.error("Could not open the microphone: %s", exc)
                self.beeper.error()
                return
        self.beeper.listen_start()
        log.info("Listening. Speak, pause %.1fs and it is typed. Tap %s to stop.",
                 float(self.config.continuous["silence_duration"]),
                 self.config.hotkeys.get("toggle", "the hotkey"))
        self._indicate(BUSY if self._job_running else LISTENING)

    def stop_listening(self) -> None:
        with self._state_lock:
            if not self.listening:
                return
            # Flushes a sentence cut off mid-way into the job queue.
            self.recorder.stop()
        log.info("Stopped listening after %d segment(s).", self.recorder.segments)
        self.beeper.listen_end()
        busy = self._job_running or not self._jobs.empty()
        self._indicate(BUSY if busy else IDLE)

    def toggle(self) -> None:
        # One tap, one toggle. A second trigger within a fraction of a second is
        # never a person tapping again: it stopped a dictation and started
        # another 56 ms later in practice, which reads as "it turned itself off".
        now = time.monotonic()
        if now - self._last_toggle < self.TOGGLE_DEBOUNCE:
            log.info("Ignored a repeat of the hotkey %.0f ms after the last.",
                     (now - self._last_toggle) * 1000)
            return
        self._last_toggle = now
        if self.listening:
            self.stop_listening()
        else:
            self.start_listening()

    def _on_segment(self, audio: np.ndarray) -> None:
        """Called from the audio thread once per utterance. Enqueue and return.

        Nothing slow belongs here: rendering the tray icon from this thread
        stalls PortAudio and drops the next block. The worker sets the state.
        """
        self._jobs.put(audio)

    # ----------------------------------------------------------- worker loop
    def _worker(self) -> None:
        while True:
            audio = self._jobs.get()
            if audio is None:
                return
            try:
                self._job_running = True
                self._indicate(BUSY)
                self._transcribe_and_insert(audio)
            except Exception:
                self.airoot.show_transcript("Please try again", "Couldn't transcribe")
                log.exception("Job failed")
                self.beeper.error()
            finally:
                self._job_running = False
                # Don't blank the indicator while the mic is still open.
                self._indicate(self._busy_or_resting())

    def _busy_or_resting(self) -> str:
        return BUSY if not self._jobs.empty() else self._resting_state()

    def _transcribe_and_insert(self, audio: np.ndarray) -> None:
        started = time.perf_counter()
        text = self.transcriber.transcribe(audio)
        elapsed = time.perf_counter() - started
        if not text:
            self.airoot.show_transcript("No speech recognized", "Try again")
            log.info("Nothing recognised (%.2fs).", elapsed)
            self.beeper.empty()
            return
        self.airoot.show_transcript(text)
        target = focused_window() or "unknown window"
        inserted = self.inserter.insert(text)
        if self.config.feedback.get("log_transcripts", True):
            log.info("[%.2fs] -> %s | %s", elapsed, target, inserted.strip())
        else:
            log.info("[%.2fs] -> %s | %d chars", elapsed, target, len(inserted))
        self.overlay.show(inserted.strip())
        self.beeper.done()

    # ---------------------------------------------------------------- control
    def request_stop(self) -> None:
        self._stop.set()
        self.tray.stop()

    def run(self) -> int:
        # [model].engine: whisper | parakeet | auto (voicevibe/engines).
        from .engines import create as create_transcriber

        self.transcriber = create_transcriber(self.config.model)
        self.transcriber.hotwords = None
        self.transcriber.warmup(int(self.config.audio["sample_rate"]))

        self.overlay.start()
        self.airoot.start()
        threading.Thread(target=self._worker, name="worker", daemon=True).start()
        self.hotkeys.bind(self.config.hotkeys.get("toggle", ""), on_activate=self.toggle)
        self.hotkeys.bind(self.config.hotkeys.get("quit", ""), on_activate=self.request_stop)
        self.hotkeys.start()

        banner = self._banner()
        # pythonw.exe has no stdout, so print() would raise. The log always gets it.
        if sys.stdout is not None:
            print(banner, flush=True)
        for line in banner.splitlines():
            if line.strip():
                log.info("%s", line.rstrip())
        self._indicate(IDLE)

        if self.tray.icon is not None:
            threading.Thread(target=self._wait_then_quit, daemon=True).start()
            self.tray.run()
        else:
            try:
                while not self._stop.wait(0.2):
                    pass
            except KeyboardInterrupt:
                pass

        self._shutdown()
        return 0

    def _wait_then_quit(self) -> None:
        self._stop.wait()
        self.tray.stop()

    def _shutdown(self) -> None:
        self._stop.set()
        self.hotkeys.stop()
        if self.listening:
            self.recorder.stop()
        self.overlay.stop()
        self.airoot.stop()
        self._jobs.put(None)
        log.info("Stopped.")

    def _banner(self) -> str:
        keys = self.config.hotkeys
        indicator = "Airoot logo" if self.airoot.enabled else (
            "orb" if self.overlay.enabled else "tray icon only")
        lines = [
            "",
            "  Voice Vibe transcriber - ready",
            f"  model    {self.transcriber.model_name}"
            f"  ({self.transcriber.device}/{self.transcriber.compute_type})",
            f"  output   {self.config.output.get('mode')} into the focused field",
            f"  shows    {indicator}",
            f"  config   {self.config.path or 'defaults'}",
            f"  data     {data_dir()}",
            "",
            f"  {'listen on / off':<18} {keys.get('toggle')}",
            f"  {'quit':<18} {keys.get('quit')}",
            "",
            "  Quit from the tray icon, or with the quit hotkey.",
            "",
        ]
        return "\n".join(lines)
