"""Wires hotkeys -> recorder -> transcriber -> (insert text | speak aloud)."""

from __future__ import annotations

import logging
import queue
import sys
import threading
import time

import numpy as np

from .airoot import AirootBridge
from .audio import Recorder, SegmentRecorder
from .config import Config
from .feedback import Beeper, Tray
from .history import History, data_dir
from .hotkey import HotkeyListener
from .inserter import Inserter, focused_window
from .intent import Responder
from .launcher import Launcher
from .overlay import Overlay
from .screen import ScreenReader
from .speaker import Speaker, SpeechUnavailable, SystemVoice
from .transcriber import Transcriber
from .wake import PhraseMatcher

log = logging.getLogger(__name__)

INSERT = "insert"
SPEAK = "speak"
SESSION = "session"

# Session sub-states when a wake phrase is configured.
ARMED = "armed"  # listening, but only for the wake phrase
DICTATING = "dictating"  # wake phrase heard, everything now goes to the cursor


class VoiceVibe:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.recorder = Recorder(
            sample_rate=int(config.audio["sample_rate"]),
            device=config.input_device,
            max_duration=float(config.audio["max_duration"]),
        )
        cont = config.continuous
        self.session = SegmentRecorder(
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
        self.inserter = Inserter(config.output, config.replacements, config.commands)
        self.speaker = Speaker(config.speech)
        assistant = config.assistant
        # Short confirmations go through the OS voice, not Soprano: a reply
        # is not worth a multi-gigabyte model load on a low-spec machine.
        self.voice = SystemVoice(
            enabled=bool(assistant.get("speak_replies", True)),
            rate=int(assistant.get("voice_rate", 1)),
        )
        self.responder = Responder(
            launcher=Launcher(
                config.apps,
                discover=bool(assistant.get("discover_apps", True)),
                threshold=float(assistant.get("match_threshold", 0.78)),
            ),
            screen=ScreenReader(config.screen),
            cfg=assistant,
        )
        self.beeper = Beeper(bool(config.feedback.get("sounds", True)))
        self.tray = Tray(bool(config.feedback.get("tray_icon", True)), self.request_stop)
        self.overlay = Overlay(config.overlay)
        self.airoot = AirootBridge(config.airoot)
        # The overlay meters the same microphone dictation records from,
        # rather than whatever Windows has as the default.
        self.airoot.set_device(config.input_device)
        self.history = History(
            enabled=bool(config.history.get("enabled", True)),
            keep_days=int(config.history.get("keep_days", 30)),
        )
        self.transcriber: Transcriber | None = None

        self._jobs: queue.Queue[tuple[np.ndarray, str] | None] = queue.Queue()
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self._action = INSERT
        # True while a tap-to-toggle recording is running, so the hold-style
        # binding's release does not cut it short.
        self._latched = False
        self.hotkeys = HotkeyListener()

        wake = config.wake
        self.wake_enabled = bool(wake.get("enabled", True))
        fuzzy = float(wake.get("fuzzy", 0.82) or 0.0)
        self.wake_matcher = PhraseMatcher(list(wake.get("phrases", [])), fuzzy=fuzzy)
        # Sleep phrases are multi-word and less error-prone, and a false positive
        # there silently swallows a dictation, so match them strictly.
        self.sleep_matcher = PhraseMatcher(list(wake.get("sleep_phrases", [])))
        self._wake_state = ARMED
        self._last_activity = 0.0
        self._last_fired: list[dict[str, str]] = []
        # Whether the last handled utterance should send a session back to armed.
        self._ends_dictation = False
        if self.wake_enabled and not self.wake_matcher:
            log.warning("[wake].enabled is true but no phrases are set; disabling.")
            self.wake_enabled = False

    def _indicate(self, state: str) -> None:
        """Drive every status indicator from one place."""
        self.tray.set_state(state)
        self.overlay.set_state(state)
        self.airoot.set_listening(self._is_listening(state))

    def _is_listening(self, state: str) -> bool:
        """Whether the mic is currently taking in speech meant for the cursor.

        Derived from the session state rather than the indicator string: a
        dictating session flips through "busy" on every utterance while the mic
        stays open, and keying off the string would flash the overlay each time.
        An armed session is waiting for the wake word, not listening to you.
        """
        if state == "recording":
            return True
        return self.session.is_recording and (
            not self.wake_enabled or self._wake_state == DICTATING
        )

    # -------------------------------------------------------------- recording
    def _begin(self, action: str) -> None:
        with self._state_lock:
            if self.recorder.is_recording:
                return
            try:
                self.recorder.start()
            except Exception as exc:
                log.error("Could not open the microphone: %s", exc)
                self.beeper.error()
                return
            self._action = action
        self._indicate("recording")
        self.beeper.start()
        log.info("Recording (%s)...", "speak" if action == SPEAK else "dictate")

    def _end(self) -> None:
        with self._state_lock:
            if not self.recorder.is_recording:
                return
            action = self._action
            # `is_recording` goes false as soon as the stream handle is taken, so
            # a second hotkey press returns above rather than blocking here.
            self.recorder.detach()
        # stop() drains the driver buffer for up to 0.3s. Holding the state lock
        # across that stalls every other hotkey.
        audio = self.recorder.stop()

        seconds = self.recorder.duration(audio)
        if seconds < float(self.config.audio["min_duration"]):
            log.info("Discarded %.2fs clip (below min_duration).", seconds)
            self._indicate("idle")
            self.beeper.empty()
            return

        peak = float(np.abs(audio).max()) if audio.size else 0.0
        if peak < 1e-5:
            log.warning(
                "Microphone returned pure silence. Check Windows mic privacy "
                "(Settings > Privacy > Microphone), that the device is unmuted, "
                "and try --list-devices plus [audio].input_device."
            )
            self._indicate("idle")
            self.beeper.error()
            return
        if peak < 0.01:
            log.warning("Input is very quiet (peak %.4f); raise your mic level.", peak)

        log.info("Captured %.2fs, transcribing...", seconds)
        self._indicate("busy")
        self._jobs.put((audio, action))

    # --------------------------------------------------------- session mode
    def _on_segment(self, audio: np.ndarray) -> None:
        """Called from the audio thread once per utterance. Enqueue and return.

        Nothing slow belongs here: rendering the tray icon from this thread
        stalls PortAudio and drops the next block. The worker sets the state.
        """
        self._jobs.put((audio, SESSION))

    def _session_tray(self) -> str:
        if not self.session.is_recording:
            return "idle"
        if self.wake_enabled and self._wake_state == ARMED:
            return "armed"
        return "session"

    def toggle_session(self) -> None:
        if self.session.is_recording:
            self.session.stop()
            log.info("Session closed after %d segment(s).", self.session.segments)
            self._wake_state = ARMED
            self._indicate("idle")
            self.beeper.session_end()
            return

        if self.recorder.is_recording:
            log.warning("Finish the current recording before starting a session.")
            self.beeper.error()
            return

        try:
            self.session.start()
        except Exception as exc:
            log.error("Could not open the microphone: %s", exc)
            self.beeper.error()
            return

        self._wake_state = ARMED
        self._last_activity = time.monotonic()
        self.beeper.session_start()
        key = self.config.hotkeys.get("session", "the session key")
        if self.wake_enabled:
            log.info(
                "Session armed. Say %s to start dictating. Nothing is typed until "
                "you do. Tap %s to close.",
                self._phrase_hint(),
                key,
            )
        else:
            log.info(
                "Session open. Speak, pause %.1fs to send. Tap %s to close.",
                float(self.config.continuous["silence_duration"]),
                key,
            )
        self._indicate(self._session_tray())

    def _phrase_hint(self) -> str:
        phrases = list(self.config.wake.get("phrases", []))
        return " / ".join(f'"{p}"' for p in phrases[:3]) or '"arise"'

    def _arm(self, reason: str) -> None:
        """Return a dictating session to the armed state."""
        if self._wake_state == ARMED:
            return
        self._wake_state = ARMED
        log.info("Armed again (%s). Say %s to dictate.", reason, self._phrase_hint())
        self.beeper.sleep()
        self._indicate(self._session_tray())

    def _watchdog(self) -> None:
        """Drop back to armed if a dictating session goes quiet.

        Without this, walking away mid-dictation means every later utterance,
        including other people talking, gets typed into whatever has focus.
        """
        while not self._stop.wait(0.5):
            timeout = float(self.config.wake.get("active_timeout", 20.0) or 0)
            if timeout <= 0 or not self.wake_enabled:
                continue
            if not self.session.is_recording or self._wake_state != DICTATING:
                continue
            if time.monotonic() - self._last_activity >= timeout:
                self._arm(f"silent for {timeout:g}s")

    # ---------------------------------------------------------------- hotkeys
    def toggle(self, action: str) -> None:
        if self.session.is_recording:
            log.warning("A session is open; tap the session key to close it first.")
            self.beeper.error()
            return
        if self.recorder.is_recording:
            self._latched = False
            self._end()
        else:
            self._latched = True
            self._begin(action)

    def hold_press(self, action: str) -> None:
        if self.session.is_recording:
            return
        self._latched = False
        self._begin(action)

    def hold_release(self) -> None:
        if not self._latched:
            self._end()

    # ----------------------------------------------------------- worker loop
    def _worker(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            audio, action = job
            try:
                if not (action == SESSION and self.wake_enabled and self._wake_state == ARMED):
                    self._indicate("busy")
                started = time.perf_counter()
                text = self.transcriber.transcribe(audio) if self.transcriber else ""
                elapsed = time.perf_counter() - started
                if not text:
                    log.info("Nothing recognised (%.2fs).", elapsed)
                    self.beeper.empty()
                    continue
                if action == SPEAK:
                    self._do_speak(text, elapsed)
                elif action == SESSION:
                    self._do_session(text, elapsed)
                else:
                    self._do_insert(text, elapsed)
            except Exception:
                log.exception("Job failed")
                self.beeper.error()
            finally:
                # Don't blank the indicator while the mic is still open.
                self._indicate(self._session_tray())

    def _do_session(self, text: str, elapsed: float) -> None:
        """One utterance from a session, routed by the wake state."""
        if not self.wake_enabled:
            self._do_insert(text, elapsed)
            return

        if self._wake_state == ARMED:
            woke, remainder = self.wake_matcher.split(text)
            if not woke:
                if self.config.wake.get("log_ignored", True):
                    log.info("(armed, ignored) %s", text.strip())
                return
            self._wake_state = DICTATING
            self._last_activity = time.monotonic()
            self.beeper.wake()
            self._indicate("session")
            log.info("Awake. Dictating.")
            # The wake phrase usually arrives in the same breath as the request,
            # so keep going with whatever followed it.
            text = remainder
            if not text.strip():
                return

        self._last_activity = time.monotonic()

        if self.sleep_matcher.matches(text):
            self._arm("sleep phrase")
            return

        self._ends_dictation = False
        self._do_insert(text, elapsed)
        if self._ends_dictation:
            self._arm("submitted")

    def _do_insert(self, text: str, elapsed: float) -> None:
        reply = self.responder.respond(text)
        if reply.handled:
            self._deliver_reply(reply, text, elapsed)
            return

        target = focused_window() or "unknown window"
        inserted, fired = self.inserter.insert(text)
        self._last_fired = fired
        keys = f"  +[{' '.join(c['keys'] for c in fired)}]" if fired else ""
        if self.config.feedback.get("log_transcripts", True):
            log.info("[%.2fs] -> %s | %s%s", elapsed, target, inserted.strip(), keys)
        else:
            log.info("[%.2fs] -> %s | %d chars%s", elapsed, target, len(inserted), keys)
        self.history.add(
            action="dictate",
            heard=text.strip(),
            inserted=inserted.strip(),
            target=target,
            keys=[c["keys"] for c in fired],
            seconds=round(elapsed, 2),
        )
        self.overlay.show(inserted.strip() or " ".join(c["keys"] for c in fired))
        self._ends_dictation = any(c.get("ends_dictation", True) for c in fired)
        self.beeper.done()

    def _deliver_reply(self, reply, heard: str, elapsed: float) -> None:  # noqa: ANN001
        """An utterance the responder handled: nothing is typed, something is said."""
        self._last_fired = []
        # A completed request ends the turn, so a wake session goes back to armed.
        self._ends_dictation = True
        log.info("[%.2fs] %s | %s", elapsed, reply.action, reply.speak)
        self.history.add(
            action=reply.action,
            heard=heard.strip(),
            reply=reply.speak,
            seconds=round(elapsed, 2),
        )
        self.overlay.show(reply.caption or reply.speak)
        if reply.speak:
            self.voice.say(reply.speak)
        self.beeper.done()

    def _do_speak(self, text: str, elapsed: float) -> None:
        spoken = self.inserter.polish(text).strip()
        log.info("[%.2fs] -> speaking | %s", elapsed, spoken)
        self.history.add(action="speak", heard=text.strip(), spoken=spoken,
                         seconds=round(elapsed, 2))
        self.overlay.show(spoken)
        try:
            started = time.perf_counter()
            self.speaker.speak(spoken)
            log.info("Spoken in %.2fs", time.perf_counter() - started)
            self.beeper.done()
        except SpeechUnavailable as exc:
            log.error("%s", exc)
            self.beeper.error()

    # ---------------------------------------------------------------- control
    def request_stop(self) -> None:
        self._stop.set()
        self.tray.stop()

    def _bind_hotkeys(self) -> None:
        keys = self.config.hotkeys
        # Longest combos are registered first so specificity checks read cleanly.
        self.hotkeys.bind(keys.get("speak", ""), on_activate=lambda: self.toggle(SPEAK))
        self.hotkeys.bind(
            keys.get("speak_hold", ""),
            on_activate=lambda: self.hold_press(SPEAK),
            on_deactivate=self.hold_release,
        )
        self.hotkeys.bind(keys.get("dictate", ""), on_activate=lambda: self.toggle(INSERT))
        self.hotkeys.bind(
            keys.get("dictate_hold", ""),
            on_activate=lambda: self.hold_press(INSERT),
            on_deactivate=self.hold_release,
        )
        self.hotkeys.bind(keys.get("session", ""), on_activate=self.toggle_session)
        self.hotkeys.bind(keys.get("quit", ""), on_activate=self.request_stop)

    def _wake_biased_prompt(self) -> str | None:
        """Seed the decoder with the wake phrases.

        Whisper's initial_prompt shifts token probabilities. Listing the wake
        phrase there makes the model far more likely to emit it verbatim instead
        of a similar-sounding common word, which is the actual failure mode for
        short wake words.
        """
        existing = str(self.config.model.get("initial_prompt") or "").strip()
        if not (self.wake_enabled and self.config.wake.get("bias_prompt", True)):
            return existing or None
        phrases = [str(p).strip() for p in self.config.wake.get("phrases", []) if str(p).strip()]
        if not phrases:
            return existing or None
        hint = ". ".join(dict.fromkeys(phrases))
        log.debug("Decoder prompt biased with: %s", hint)
        return f"{existing} {hint}".strip() if existing else hint

    def run(self) -> int:
        self.transcriber = Transcriber(self.config.model)
        self.transcriber.initial_prompt = self._wake_biased_prompt()
        self.transcriber.warmup(int(self.config.audio["sample_rate"]))

        if self.config.speech.get("preload") and self.config.hotkeys.get("speak"):
            try:
                self.speaker.load()
            except SpeechUnavailable as exc:
                log.warning("%s", exc)

        self.overlay.start()
        self.airoot.start()
        threading.Thread(target=self._worker, name="worker", daemon=True).start()
        threading.Thread(target=self._watchdog, name="watchdog", daemon=True).start()
        self._bind_hotkeys()
        self.hotkeys.start()

        banner = self._banner()
        # pythonw.exe has no stdout, so print() would raise. The log always gets it.
        if sys.stdout is not None:
            print(banner, flush=True)
        for line in banner.splitlines():
            if line.strip():
                log.info("%s", line.rstrip())
        self._indicate("idle")

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
        self.overlay.stop()
        self.airoot.stop()
        self.hotkeys.stop()
        if self.session.is_recording:
            self.session.stop()
        self.recorder.abort()
        self._jobs.put(None)
        log.info("Stopped.")

    def _banner(self) -> str:
        keys = self.config.hotkeys
        pause = float(self.config.continuous["silence_duration"])
        session_label = (
            f"session (wake: {self._phrase_hint()})"
            if self.wake_enabled
            else f"session (pause {pause:g}s)"
        )
        rows = [
            ("dictate (tap on/off)", keys.get("dictate")),
            ("dictate (hold)", keys.get("dictate_hold")),
            (session_label, keys.get("session")),
            ("speak (tap on/off)", keys.get("speak")),
            ("speak (hold)", keys.get("speak_hold")),
            ("quit", keys.get("quit")),
        ]
        sources = ScreenReader.available()
        extras = [name for name in ("uia", "ocr") if sources.get(name)]
        screen = "title + selection" + (f" + {' + '.join(extras)}" if extras else "")
        lines = [
            "",
            "  Voice Vibe - ready",
            f"  whisper  {self.transcriber.model_name}"
            f"  ({self.transcriber.device}/{self.transcriber.compute_type})",
            f"  output   {self.config.output.get('mode')} into the focused field",
            f"  replies  {'on' if self.responder.enabled else 'off'}"
            f"  ({len(self.responder.launcher.names())} apps, screen: {screen})",
            f"  config   {self.config.path or 'defaults'}",
            f"  data     {data_dir()}",
            "",
        ]
        lines += [f"  {label:<30} {spec}" for label, spec in rows if spec]
        # There is no console in the normal (background) launch, so point at the
        # things that do exist: the tray icon and the quit hotkey.
        lines += ["  Quit from the tray icon, or with the quit hotkey.", ""]
        return "\n".join(lines)
