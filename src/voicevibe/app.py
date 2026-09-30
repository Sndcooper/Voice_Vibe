"""Wires hotkeys -> recorder -> transcriber -> (insert text | speak aloud)."""

from __future__ import annotations

import io
import logging
import queue
import re
import sys
import threading
import time

import numpy as np

from .airoot import AirootBridge
from .audio import Recorder, SegmentRecorder, device_label, is_loopback, refresh_devices
from .actions import Cancelled, DEFAULT_CONFIRM_TIMEOUT, DEFAULT_CONFIRM_WORDS, Executor
from .actions import parse as parse_steps
from .config import Config
from .confirm import DEFAULT_NO, DEFAULT_YES, VoiceConfirmer
from .context import ContextBuilder, LocalScreen, purge_crops
from .control import Router
from .feedback import Beeper, Tray
from .history import History, data_dir, is_save_command
from .hub_client import HubClient
from .hotkey import HotkeyListener, physically_down
from .inserter import Inserter, focused_window
from .intent import Responder
from .launcher import Launcher
from .overlay import Badges, Overlay
from .polish import apply_edit, edit_applies, parse_edit
from .screen import ScreenReader
from .speaker import Speaker, SpeechUnavailable, SystemVoice
from .transcriber import Transcriber, choose_command_model
from .uia import Finder
from .vocab import Vocabulary, echoes_prompt
from .winctl import foreground, front_process
from .wake import PhraseMatcher
from .wakeword import WakeWordDetector, phrase_for

log = logging.getLogger(__name__)

INSERT = "insert"
SPEAK = "speak"
SESSION = "session"

# Session sub-states when a wake phrase is configured.
ARMED = "armed"  # listening, but only for the wake phrase
DICTATING = "dictating"  # wake phrase heard, everything now goes to the cursor

# "open notepad and type hello": after a launch, "type <text>" types the text.
_TYPE_REQUEST = re.compile(r"^(?:please\s+)?type\s+(.+)$", re.IGNORECASE)


class VoiceVibe:
    # Wake word model state; class defaults so a partly built instance (tests
    # construct one piecemeal) behaves as the plain Whisper path.
    detector: WakeWordDetector | None = None
    _confirm_wake = False
    # When a tap-to-toggle hotkey last acted; see toggle().
    _last_toggle = float("-inf")
    TOGGLE_DEBOUNCE = 0.4
    _mic: int | str | None = None
    # Seconds of the latest audio an interim transcript decodes.
    PARTIAL_WINDOW = 15.0
    # Small Whisper for short command-like utterances; None = use the main one.
    command_transcriber: Transcriber | None = None
    # Screen context + local screen phrases; None in a partly built instance.
    local_screen: LocalScreen | None = None
    # Link to vvhub (hub_client.py); None = hub features off, dictation as before.
    hub: HubClient | None = None
    # After "hey computer", the next utterance is a request even without the
    # "computer" prefix; re-arming cancels it.
    _command_pending = False
    # "open terminal and <rest>": how long to wait for the app to come to the
    # front before <rest> is handled (never typed into the old window).
    LAUNCH_FOCUS_SECONDS = 6.0
    LAUNCH_SETTLE_SECONDS = 1.0

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
        # The microphone in use; re-chosen before every recording.
        self._mic = config.input_device
        # Screen context v2 (context.py): the bundle hub requests carry, the
        # "focus on my cursor" pin, the privacy guard, local screen phrases.
        self.context = ContextBuilder(config.screen)
        self.local_screen = LocalScreen(self.context)

        control = config.control
        timeout = float(control.get("confirm_timeout", DEFAULT_CONFIRM_TIMEOUT))
        self.confirmer = VoiceConfirmer(
            # Answers are one or two words: the command model if there is one.
            transcribe=lambda audio: (
                (self.command_transcriber or self.transcriber).transcribe(audio)
                if self.transcriber else ""
            ),
            say=lambda text: self.voice.say(text, block=True),
            show=lambda text: self._show_question(text, timeout),
            # Answers arrive through the session; with it closed, none can.
            listening=lambda: self.session.is_recording,
            yes_words=control.get("yes_words", DEFAULT_YES),
            no_words=control.get("no_words", DEFAULT_NO),
        )
        self.executor = Executor(
            confirmer=self.confirmer,
            confirm_words=control.get("confirm_words", DEFAULT_CONFIRM_WORDS),
            confirm_timeout=timeout,
        )
        self.badges = Badges(float(control.get("badge_seconds", 20.0)))
        self.router = Router(control, executor=self.executor, commands=config.commands,
                             finder=Finder(), badges=self.badges, profiles=config.profiles)
        # "read the answer" and profile replies speak through the SAPI voice.
        self.executor.say = self.voice.say
        if bool(config.hub.get("enabled", True)):
            self.hub = HubClient({
                "confirm": self._hub_confirm,
                "get_context": lambda deep, pin=None: self.context.bundle(deep=deep, pin=pin),
                "run_steps": self._hub_steps,
                "list_mics": self._list_mics,
                "set_mic": self._set_mic,
                "transcribe": self._transcribe_note,
            })
        self.history = History(
            enabled=bool(config.history.get("enabled", True)),
            keep_days=int(config.history.get("keep_days", 2)),
        )
        self.transcriber: Transcriber | None = None
        self.vocab = Vocabulary(config.vocab)

        self._jobs: queue.Queue[tuple[np.ndarray, str] | None] = queue.Queue()
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self._action = INSERT
        # True while a tap-to-toggle recording is running, so the hold-style
        # binding's release does not cut it short.
        self._latched = False
        # Re-checks held keys against Windows, so a release missed in an admin
        # window cannot leave ctrl+alt "held" for a later lone Space.
        self.hotkeys = HotkeyListener(check_held=physically_down)

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
        # Text from the previous utterance, for spoken edits like "scratch that".
        self._last_inserted = ""
        if self.wake_enabled and not self.wake_matcher:
            log.warning("[wake].enabled is true but no phrases are set; disabling.")
            self.wake_enabled = False
        # openWakeWord, when [wake].engine asks for it; built in run().
        self.detector: WakeWordDetector | None = None
        # Set when the model woke the session: the next transcript must still
        # contain the wake phrase, or the wake is treated as a false alarm.
        self._confirm_wake = False

    def _indicate(self, state: str) -> None:
        """Drive every status indicator from one place."""
        self.tray.set_state(state)
        self.overlay.set_state(state)
        self.airoot.set_state(self._airoot_state(state))

    def _airoot_state(self, state: str) -> str:
        """Map the indicator state onto what the overlay should show."""
        if state == "busy":
            return "busy"
        return "listening" if self._is_listening(state) else "idle"

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
    def _choose_microphone(self) -> None:
        """Pick the mic again just before recording (no stream is open yet).

        Follows the Windows default input whenever it is a real microphone,
        so switching mics in Windows or plugging in a headset takes effect on
        the next recording, without a restart -- and a device that vanished
        is not reused. Never a loopback such as Stereo Mix.
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
        self.session.device = device
        self.airoot.set_device(device)
        log.info("Microphone: %s.", device_label(device))

    def _begin(self, action: str) -> None:
        with self._state_lock:
            if self.recorder.is_recording:
                return
            self._choose_microphone()
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
        # Only digital silence is a device failure; quiet speech must be decoded.
        if not audio.size or not np.any(audio):
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
        # While a confirmation is open the worker is blocked waiting for the
        # answer, so the answer has to go to it directly rather than queue
        # behind it -- and must not be typed as dictation.
        if self.confirmer.offer(audio):
            return
        self._jobs.put((audio, SESSION))

    def _on_frame(self, mono: np.ndarray) -> None:
        """Audio callback thread: raw blocks to the wake word model, armed only.

        Once awake there is nothing for it to find, so it stops costing CPU.
        """
        if self.detector is not None and self._wake_state == ARMED:
            self.detector.feed(mono)

    def _on_wake_word(self, name: str, score: float) -> None:
        """Detector thread: the model heard the wake word. Wake without Whisper."""
        if not self.session.is_recording or self._wake_state != ARMED:
            return
        self._wake_state = DICTATING
        self._confirm_wake = True
        self._set_wake_bias(False)
        self._last_activity = time.monotonic()
        self.beeper.wake()
        self._indicate("session")
        log.info("Awake (%s, %.2f). Dictating.", name, score)

    def _start_wake_model(self) -> None:
        wake = self.config.wake
        model = str(wake.get("model", "hey_jarvis"))
        self.detector = WakeWordDetector.create(
            model,
            self._on_wake_word,
            threshold=float(wake.get("threshold", 0.5)),
            sample_rate=int(self.config.audio["sample_rate"]),
        )
        if self.detector is None:
            return
        # The transcript check (and "hey jarvis, open ..." in one breath)
        # needs the model's own phrase among the wake phrases.
        phrase = phrase_for(model)
        if phrase and not self.wake_matcher.matches(phrase):
            phrases = [*wake.get("phrases", []), phrase]
            self.wake_matcher = PhraseMatcher(phrases, fuzzy=float(wake.get("fuzzy", 0.82) or 0))
        self.session.on_frame = self._on_frame
        self.detector.start()

    def _show_question(self, text: str, seconds: float) -> None:
        # Orb only: Airoot never displays text, and a transcript event would
        # make it fade out as if the session had finished.
        self.overlay.show(text, seconds=seconds)

    def _session_tray(self) -> str:
        if not self.session.is_recording:
            return "idle"
        if self.wake_enabled and self._wake_state == ARMED:
            return "armed"
        return "session"

    def toggle_session(self) -> None:
        if self.session.is_recording:
            self.session.stop()
            # With the mic closed nobody can say "stop" any more.
            self.router.stop()
            log.info("Session closed after %d segment(s).", self.session.segments)
            self._wake_state = ARMED
            self._indicate("idle")
            self.beeper.session_end()
            return

        if self.recorder.is_recording:
            log.warning("Finish the current recording before starting a session.")
            self.beeper.error()
            return

        self._choose_microphone()
        try:
            self.session.start()
        except Exception as exc:
            log.error("Could not open the microphone: %s", exc)
            self.beeper.error()
            return

        self._wake_state = ARMED
        self._confirm_wake = False
        self._last_inserted = ""
        if self.detector is not None:
            self.detector.reset()
        self._set_wake_bias(True)
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
        if self.hub is not None:
            # The hub answers with an unspoken report summary, if there is one.
            self.hub.armed(self._say_hub_reply)

    def _command_hint(self) -> str:
        if not self.router.enabled:
            return "off"
        prefixes = [" ".join(p) for p in self.router.prefix.phrases]
        return "in a session, start with " + " / ".join(f'"{p}"' for p in prefixes[:3])

    def _phrase_hint(self) -> str:
        if self.detector is not None:
            return f'"{phrase_for(str(self.config.wake.get("model", "")))}"'
        phrases = list(self.config.wake.get("phrases", []))
        return " / ".join(f'"{p}"' for p in phrases[:3]) or '"arise"'

    def _arm(self, reason: str) -> None:
        """Return a dictating session to the armed state."""
        if self._wake_state == ARMED:
            return
        self._wake_state = ARMED
        self._confirm_wake = False
        self._command_pending = False
        if self.detector is not None:
            self.detector.reset()
        self._set_wake_bias(True)
        log.info("Armed again (%s). Say %s to dictate.", reason, self._phrase_hint())
        self.beeper.sleep()
        self._indicate(self._session_tray())

    # ------------------------------------------------------------- partials
    def _partials_enabled(self) -> bool:
        """[continuous].partials: true, false, or "auto" (GPU only -- on a
        CPU an interim decode competes with the final one for the cores).

        Interim text is shown only on the orb. The Airoot overlay reads any
        transcript as "finished" and fades out, so sending it interim text
        made a running dictation look stopped; with the orb off there is
        nowhere to show it, so none is decoded.
        """
        if not getattr(self.overlay, "enabled", False):
            return False
        setting = str(self.config.continuous.get("partials", "auto")).lower()
        if setting in ("true", "on", "yes", "1"):
            return True
        if setting == "auto":
            return self.transcriber is not None and self.transcriber.device == "cuda"
        return False

    def _partial_source(self):  # noqa: ANN202
        """The recorder currently taking speech meant for the cursor, if any."""
        if self.recorder.is_recording:
            return self.recorder
        if self.session.is_recording and not (self.wake_enabled and self._wake_state == ARMED):
            return self.session
        return None

    def _partial_once(self, last: tuple[int, int]) -> tuple[int, int]:
        """One interim transcript, if there is something new to show.

        Returns the (take, samples) now shown, so the next pass only decodes
        once the take has grown. A result is dropped if its take ended while
        it was decoding: the final transcript is already up by then, and a
        stale partial must not replace it.
        """
        source = self._partial_source()
        if source is None or self.confirmer.pending:
            return last
        snap = source.snapshot()
        if snap is None:
            return last
        take, audio = snap
        rate = int(self.config.audio["sample_rate"])
        if len(audio) < 0.8 * rate or (take == last[0] and len(audio) - last[1] < 0.4 * rate):
            return last
        model = self.command_transcriber or self.transcriber
        if model is None:
            return last
        # Only the latest stretch: re-decoding a whole five-minute take every
        # 0.8 s grows without bound, and the orb shows one line anyway.
        window = audio[-int(self.PARTIAL_WINDOW * rate):]
        text = model.transcribe(window, beam_size=1, wait=False)
        if text is None:  # the model is busy with a final transcript
            return last
        if text and source.still(take):
            # Never to Airoot: it treats a transcript as "done" and fades out
            # while the recording is still running.
            self.overlay.show(text)
        return take, len(audio)

    def _partials(self) -> None:
        """Interim text while speaking, finalised by the normal transcript."""
        interval = max(0.2, float(self.config.continuous.get("partial_interval", 0.8)))
        last = (0, 0)
        while not self._stop.wait(interval):
            try:
                last = self._partial_once(last)
            except Exception:
                log.debug("interim transcript failed", exc_info=True)

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
        # One tap, one toggle. A second trigger within a fraction of a second
        # is never a person tapping again: it stopped a dictation and started
        # another 56 ms later in practice, which reads as "it turned itself off".
        now = time.monotonic()
        if now - self._last_toggle < self.TOGGLE_DEBOUNCE:
            log.info("Ignored a repeat of the %s hotkey %.0f ms after the last.",
                     action, (now - self._last_toggle) * 1000)
            return
        self._last_toggle = now
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
            visible_job = not (action == SESSION and self.wake_enabled and self._wake_state == ARMED)
            if not visible_job and self.detector is not None:
                # The wake word model is listening; an armed utterance it did
                # not fire on is not worth a Whisper decode.
                log.debug("Armed, no wake word: %.1fs dropped untranscribed.",
                          len(audio) / int(self.config.audio["sample_rate"]))
                continue
            try:
                if visible_job:
                    self._indicate("busy")
                armed = not visible_job
                started = time.perf_counter()
                text = self._transcribe_job(audio, action, armed)
                elapsed = time.perf_counter() - started
                if not text:
                    if visible_job:
                        self.airoot.show_transcript("No speech recognized", "Try again")
                    log.info("Nothing recognised (%.2fs).", elapsed)
                    self.beeper.empty()
                    continue
                if visible_job:
                    self.airoot.show_transcript(text)
                if action == SPEAK:
                    self._do_speak(text, elapsed)
                elif action == SESSION:
                    self._do_session(text, elapsed)
                else:
                    self._do_insert(text, elapsed)
            except Exception:
                if visible_job:
                    self.airoot.show_transcript("Please try again", "Couldn't transcribe")
                log.exception("Job failed")
                self.beeper.error()
            finally:
                # Don't blank the indicator while the mic is still open.
                self._indicate(self._session_tray())

    def _transcribe_job(self, audio: np.ndarray, action: str, armed: bool) -> str:
        """Transcribe with the model that fits the utterance.

        The command model takes what is predictably short and command-like:
        wake checks, answers the router is waiting for, and -- as a first
        pass -- short session utterances when commands are on. If that first
        pass does not hear the prefix, the dictation model transcribes it
        again, so dictation is never left with the small model's text.

        On near-silent audio Whisper tends to read its own prompt back; such
        a transcript is dropped rather than typed (not while armed, where the
        prompt *is* the wake phrase and hearing it is the point).
        """
        if self.transcriber is None:
            return ""
        prompt = self._decoder_prompt(armed, "" if armed else front_process())
        text = self._decode_job(audio, action, armed, prompt)
        if text and not armed and echoes_prompt(text, prompt):
            log.info("Dropped a transcript that only repeats the prompt: %r", text[:80])
            return ""
        return text

    def _decode_job(self, audio: np.ndarray, action: str, armed: bool,
                    prompt: str | None) -> str:
        fast = self.command_transcriber
        for model in (self.transcriber, fast):
            if model is not None:
                model.initial_prompt = prompt
        if fast is None:
            return self.transcriber.transcribe(audio)
        if action == SESSION and (armed or self.router.expects_command()):
            return fast.transcribe(audio)
        limit = float(self.config.model.get("command_max_seconds", 3.0) or 0)
        seconds = len(audio) / int(self.config.audio["sample_rate"])
        if action == SESSION and self.router.enabled and seconds <= limit:
            text = fast.transcribe(audio)
            if self.router.split(text) is not None:
                return text
            log.debug("Short utterance was not a command; dictation model retries.")
        return self.transcriber.transcribe(audio)

    def _load_command_model(self) -> None:
        name = choose_command_model(
            str(self.config.model.get("command_model", "auto")),
            self.transcriber.model_name,
            self.config.model.get("language", "en"),
        )
        if name is None:
            return
        try:
            cfg = {**self.config.model, "name": name, "beam_size": 1,
                   "device": self.transcriber.device}
            self.command_transcriber = Transcriber(cfg)
            self.command_transcriber.hotwords = self.transcriber.hotwords
            self.command_transcriber.warmup(int(self.config.audio["sample_rate"]))
        except Exception as exc:
            log.warning("Command model %s unavailable (%s); using %s for everything.",
                        name, exc, self.transcriber.model_name)
            self.command_transcriber = None

    def _do_session(self, text: str, elapsed: float) -> None:
        """One utterance from a session, routed by the wake state."""
        # "stop" must reach a running "keep scrolling" from any state. By the
        # time someone says it, the watchdog may already have re-armed the
        # session, and then it would be ignored for lack of a wake word.
        if self.router.is_stop(text):
            self.router.stop()
            log.info("[%.2fs] -> command | stop", elapsed)
            self.overlay.show("Stopped")
            self.beeper.done()
            return

        if not self.wake_enabled:
            self._do_command_or_insert(text, elapsed)
            return

        if self._wake_state == ARMED:
            woke, remainder = self.wake_matcher.split(text)
            if not woke:
                if self.config.wake.get("log_ignored", True):
                    log.info("(armed, ignored) %s", text.strip())
                return
            self._wake_state = DICTATING
            self._set_wake_bias(False)
            self._last_activity = time.monotonic()
            self.beeper.wake()
            self._indicate("session")
            log.info("Awake. The next request needs no \"computer\"; after it, speech is typed.")
            self._command_pending = True
            # The wake phrase usually arrives in the same breath as the request,
            # so keep going with whatever followed it.
            text = remainder
            if not text.strip():
                return

        if self._confirm_wake:
            # The model woke the session; Whisper gets the final say. The wake
            # phrase is stripped like any other, and a transcript without it
            # means the model fired on something else.
            self._confirm_wake = False
            woke, remainder = self.wake_matcher.split(text)
            if woke:
                self._command_pending = True
                text = remainder
                if not text.strip():
                    return
            elif self.config.wake.get("confirm_with_whisper", True):
                log.info("(wake not confirmed, ignored) %s", text.strip())
                self._arm("wake word not confirmed")
                return

        self._last_activity = time.monotonic()

        if self.sleep_matcher.matches(text):
            self._arm("sleep phrase")
            return

        self._ends_dictation = False
        self._do_command_or_insert(text, elapsed, implicit=self._take_implicit())
        if self._ends_dictation:
            self._arm("submitted")

    def _take_implicit(self) -> bool:
        """True once: for the rest of the wake utterance, or the next
        utterance after it, however long it takes to say. "Hey computer" then
        "open terminal" is a request, as with any voice assistant. Re-arming
        (the silence timeout, a sleep phrase) cancels it."""
        pending, self._command_pending = self._command_pending, False
        return pending

    def _do_command_or_insert(self, text: str, elapsed: float, implicit: bool = False,
                              assistant: bool = True) -> None:
        """Offer a prefixed utterance to the router; type everything else.

        An unhandled command is typed exactly as heard, prefix included, so
        [control] never loses words the user meant as dictation. `implicit`
        (just after the wake phrase) makes the "computer" prefix optional;
        `assistant=False` skips app launching and spoken edits (follow-ups).
        """
        command = self.router.split(text)
        if command is None and implicit and getattr(self.router, "enabled", False) and text.strip():
            command = text
        if command is not None:
            # Before the router: its "save" rule would press Ctrl+S.
            if is_save_command(command):
                self._save_conversation(text, elapsed)
                return
            # Exact screen phrases first: the router's "focus on <window>"
            # rule would otherwise read "focus on my cursor" as a window name.
            local = self.local_screen.handle(command) if self.local_screen else None
            if local is not None:
                self.router.stop()
                self._last_inserted = ""
                log.info("[%.2fs] -> screen | %s", elapsed, command.strip())
                self.history.add(action=local.action, heard=text.strip(), spoken=local.speak,
                                 seconds=round(elapsed, 2))
                self.overlay.show(local.caption or local.speak)
                if local.speak:
                    self.voice.say(local.speak)
                self.beeper.done()
                return
            route = self.router.route(command)
            if route.handled:
                self._last_inserted = ""
                log.info("[%.2fs] -> command | %s", elapsed, command.strip())
                self.history.add(action="command", heard=text.strip(),
                                 seconds=round(elapsed, 2))
                self.overlay.show(route.caption or command.strip())
                if route.speak:
                    self.voice.say(route.speak)
                self._ends_dictation = route.ends_dictation
                self.beeper.done()
                return
            log.debug("Command not handled, dictating instead: %s", command.strip())
            if assistant and self._do_session_extra(command, text, elapsed):
                return
            if self._do_hub(command, text, elapsed):
                return
        self._do_insert(text, elapsed, session=True)

    def _do_hub(self, command: str, heard: str, elapsed: float) -> bool:
        """Last stop before typing: offer the command to vvhub.

        False (so the text is typed as heard) when the hub is off, down, slow,
        or says it is not a hub task (rule 8).
        """
        if self.hub is None or not self.hub.connected:
            return False
        try:
            context = self.context.bundle()
        except Exception as exc:  # noqa: BLE001 - context is best effort
            log.debug("context bundle failed: %s", exc)
            context = {}
        reply = self.hub.request(command.strip(), context)
        if not reply or not reply.get("handled", True):
            return False
        self.router.stop()
        self._last_inserted = ""
        speak = str(reply.get("text") or "")
        log.info("[%.2fs] -> hub | %s | %s", elapsed, command.strip(), speak)
        self.history.add(action="hub", heard=heard.strip(), spoken=speak, ok=reply.get("ok"),
                         seconds=round(elapsed, 2))
        if speak:
            self.overlay.show(speak)
            self.airoot.show_transcript(speak, "Reply")
            if reply.get("speak", True):
                self.voice.say(speak)
        self.beeper.done()
        return True

    # ------------------------------------------------------ the hub asks us
    def _hub_confirm(self, prompt: str, timeout: float) -> dict:
        """A spoken yes/no for a hub approval (TASK.md §3.2 `confirm`).

        With no session mic open nobody can answer, so say `unavailable`:
        the hub then asks on Telegram instead of recording a refusal.
        """
        if not self.session.is_recording:
            return {"approved": False, "answer": "", "unavailable": True}
        approved = self.confirmer(prompt, timeout) is True
        return {"approved": approved, "answer": getattr(self.confirmer, "last_answer", "")}

    def _hub_steps(self, steps: list, dry_run: bool) -> None:
        """Hub steps through the normal executor: confirmation gates and
        click-by-name resolution included. A dry run only validates."""
        if dry_run:
            parse_steps(steps)
            return
        self.executor.run(steps, command="hub")

    def _mic_names(self) -> list[tuple[int, str]]:
        """Input devices as (index, name), once per device across host APIs."""
        from .audio import _input_devices, _is_alias

        seen: set[str] = set()
        found: list[tuple[int, str]] = []
        for index, dev in _input_devices():
            name = str(dev["name"]).strip()
            key = name.casefold()[:31]  # MME cuts names to 31 characters
            if not name or _is_alias(name) or key in seen:
                continue
            seen.add(key)
            found.append((index, name))
        return found

    def _list_mics(self) -> dict:
        # Re-reading devices re-initialises PortAudio: never under an open stream.
        if not (self.session.is_recording or self.recorder.is_recording):
            refresh_devices()
        label = device_label(self._mic if isinstance(self._mic, int) else None)
        current = label.split("] ", 1)[1] if "] " in label else str(self._mic or "")
        return {"devices": [name for _, name in self._mic_names()], "current": current}

    def _set_mic(self, device: object) -> None:
        """Switch microphones for this run (config.toml is not changed).

        Takes effect on the next recording or session; a running one keeps
        its stream. Never a loopback such as Stereo Mix.
        """
        wanted = str(device or "").strip().casefold()
        if not wanted:
            raise LookupError("no microphone was named")
        names = self._mic_names()
        match = next(((i, n) for i, n in names if n.casefold() == wanted), None)
        if match is None:
            match = next(((i, n) for i, n in names
                          if wanted in n.casefold() or n.casefold() in wanted), None)
        if match is None:
            raise LookupError(f"no microphone called {device}")
        index, name = match
        if is_loopback(name):
            raise ValueError(f"{name} records the speakers, not you")
        self.config.audio["input_device"] = index  # pinned until restart
        self._mic = index
        self.recorder.device = index
        self.session.device = index
        self.airoot.set_device(index)
        log.info("Microphone set by the hub: %s.", device_label(index))

    def _transcribe_note(self, data: bytes, fmt: str = "ogg") -> str:
        """A Telegram voice note (ogg/opus, m4a...) through the loaded Whisper."""
        if self.transcriber is None:
            raise RuntimeError("the speech model is still loading")
        # faster-whisper's own PyAV decoder: any container, resampled to 16 kHz mono.
        from faster_whisper.audio import decode_audio

        audio = decode_audio(io.BytesIO(data),
                             sampling_rate=int(self.config.audio["sample_rate"]))
        return self._transcribe_job(audio, INSERT, armed=False).strip()

    def _say_hub_reply(self, reply: dict) -> None:
        """Speak what the hub volunteered on arming (the report summary)."""
        text = str(reply.get("text") or "").strip()
        if not text:
            return
        log.info("-> hub (on arm) | %s", text)
        self.history.add(action="hub_report", spoken=text)
        self.overlay.show(text)
        if reply.get("speak", True):
            self.voice.say(text)

    def _save_conversation(self, heard: str, elapsed: float) -> None:
        """Keep the last two days of turns forever (history/saved/)."""
        self.router.stop()
        self._last_inserted = ""
        self.history.add(action="save_conversation", heard=heard.strip(),
                         seconds=round(elapsed, 2))
        count = self.history.save()
        hub = getattr(self, "hub", None)
        if hub is not None:
            # The hub keeps its own copy (decisions, approvals); best effort.
            hub.request_async("save this conversation")
        speak = "Conversation saved." if count else "There is nothing to save yet."
        log.info("[%.2fs] -> save conversation | %d turns", elapsed, count)
        self.overlay.show(speak)
        self.voice.say(speak)
        self.beeper.done()

    def _do_session_extra(self, command: str, heard: str, elapsed: float) -> bool:
        """Restore assistant actions and edits only behind the session prefix."""
        if self.config.output.get("raw_dictation", False):
            return False
        edit = parse_edit(command)
        if (self.config.control.get("spoken_edits", True) and edit is not None
                and edit_applies(edit[0], self._last_inserted, **edit[1])):
            self.router.stop()
            try:
                # Use the same trigger-word gate as keyboard/UI commands.
                self.executor.run([], command=command)
            except Cancelled:
                self.overlay.show("Cancelled")
                return True
            self._do_edit(edit[0], edit[1], heard, elapsed)
            return True
        before = foreground()
        reply = self.responder.respond(command)
        if not reply.handled:
            return False
        self.router.stop()
        self._last_inserted = ""
        self._ends_dictation = False
        self.history.add(action=reply.action, heard=heard.strip(), spoken=reply.speak,
                         seconds=round(elapsed, 2))
        self.overlay.show(reply.caption or reply.speak)
        self.airoot.show_transcript(reply.caption or reply.speak, "Reply")
        if reply.speak:
            self.voice.say(reply.speak)
        self.beeper.done()
        if reply.follow:
            self._do_follow(before, reply.follow, elapsed)
        return True

    def _do_follow(self, before: int | None, rest: str, elapsed: float) -> None:
        """The rest of "open terminal and <rest>", done in the app just opened.

        Waits for a new window in front first: otherwise the rest would land
        in whatever you were in before (a chat box, a document), so it is
        dropped with a spoken note. Then "type <text>" types the text; anything
        else goes to the router and the hub, and is typed if neither takes it.
        The launcher is not asked again, so "run the tests" never becomes
        "I don't know an app called the tests".
        """
        if not self._wait_for_new_window(before):
            log.info("The new window did not come to the front; not doing: %s", rest)
            self.voice.say("It didn't come to the front, so I stopped there.")
            return
        time.sleep(self.LAUNCH_SETTLE_SECONDS)
        typed = _TYPE_REQUEST.match(rest)
        if typed:
            self._do_insert(typed.group(1), elapsed, session=True)
            return
        self._do_command_or_insert(rest, elapsed, implicit=True, assistant=False)

    def _wait_for_new_window(self, before: int | None) -> bool:
        deadline = time.monotonic() + self.LAUNCH_FOCUS_SECONDS
        while time.monotonic() < deadline:
            now = foreground()
            if now and now != before:
                return True
            time.sleep(0.1)
        return False

    def _do_insert(self, text: str, elapsed: float, *, session: bool = False) -> None:
        target = focused_window() or "unknown window"
        if session and self.config.control.get("format_lists", True):
            inserted, fired = self.inserter.insert(text, format_lists=True)
        else:
            inserted, fired = self.inserter.insert(text)
        self._last_fired = fired
        # Remembered so a following "scratch that" knows what to take back.
        self._last_inserted = inserted if session and not fired else ""
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

    def _do_edit(self, edit: str, args: dict, heard: str, elapsed: float) -> None:
        """Rewrite the previous utterance in place, rather than appending.

        Only the part that changes is touched: backspace to where the new
        text first differs, then type the new ending. "Replace Tuesday with
        Wednesday" near the end of a sentence costs a few keystrokes, not a
        retype of the whole thing. Assumes the cursor is still where the
        previous utterance ended, as "scratch that" always has.
        """
        previous = self._last_inserted
        replacement, spoken = apply_edit(edit, previous, **args)
        same = 0
        for a, b in zip(previous, replacement):
            if a != b:
                break
            same += 1
        self.inserter.erase(len(previous) - same)
        self.inserter.insert_literal(replacement[same:])
        self._last_inserted = replacement
        self._ends_dictation = False

        log.info("[%.2fs] edit %s | %r -> %r", elapsed, edit, previous, replacement)
        self.history.add(action="edit", heard=heard.strip(), edit=edit, **{
            k: v for k, v in args.items() if k in ("find", "replace", "count")
        }, previous=previous, inserted=replacement, seconds=round(elapsed, 2))
        self.overlay.show(spoken or edit)
        if spoken:
            self.voice.say(spoken)
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

    def _decoder_prompt(self, armed: bool, process: str = "") -> str | None:
        """What initial_prompt should be for the next utterance.

        Armed: the wake phrases only. Otherwise the configured prompt plus the
        front app's hint (vocab.py) -- never both, for the reason below.
        """
        if armed:
            return self._wake_biased_prompt()
        existing = str(self.config.model.get("initial_prompt") or "").strip()
        return " ".join(p for p in (existing, self.vocab.hint(process)) if p) or None

    def _set_wake_bias(self, armed: bool) -> None:
        """Bias the decoder toward the wake phrase only while listening for it.

        The bias is what makes a short wake word survive Whisper, but it also
        makes the model emit that phrase when it has nothing to transcribe --
        silence came back as "Computer." during ordinary dictation. So it is
        applied while armed and removed the moment real dictation starts.
        """
        if self.transcriber is None:
            return
        self.transcriber.initial_prompt = self._decoder_prompt(
            armed, "" if armed else front_process()
        )

    def run(self) -> int:
        self.transcriber = Transcriber(self.config.model)
        self.transcriber.hotwords = self.vocab.hotwords_text()
        self._set_wake_bias(False)
        self.transcriber.warmup(int(self.config.audio["sample_rate"]))
        # After warmup: a failed GPU warmup moves the main model to CPU, and
        # the command model should follow it there.
        self._load_command_model()
        if self.wake_enabled and str(self.config.wake.get("engine", "whisper")).lower() == "openwakeword":
            self._start_wake_model()

        if self.config.speech.get("preload") and self.config.hotkeys.get("speak"):
            try:
                self.speaker.load()
            except SpeechUnavailable as exc:
                log.warning("%s", exc)

        self.overlay.start()
        self.airoot.start()
        if self.hub is not None:
            self.hub.start()
        threading.Thread(target=self._warm_context, name="context", daemon=True).start()
        threading.Thread(target=self._worker, name="worker", daemon=True).start()
        threading.Thread(target=self._watchdog, name="watchdog", daemon=True).start()
        if self._partials_enabled():
            threading.Thread(target=self._partials, name="partials", daemon=True).start()
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

    def _warm_context(self) -> None:
        """Drop crops past the 2-day retention; pay UIA's first-call cost now."""
        try:
            purge_crops()
            self.context.warm()
        except Exception as exc:  # noqa: BLE001 - optional, never fatal
            log.debug("context warm-up failed: %s", exc)

    def _shutdown(self) -> None:
        self._stop.set()
        self.overlay.stop()
        self.badges.stop()
        if self.local_screen is not None:
            self.context.pin.stop()
        self.airoot.stop()
        if self.hub is not None:
            self.hub.stop()
        self.hotkeys.stop()
        self.router.stop()
        if self.detector is not None:
            self.detector.stop()
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
            f"  commands {self._command_hint()}",
            f"  config   {self.config.path or 'defaults'}",
            f"  data     {data_dir()}",
            "",
        ]
        lines += [f"  {label:<30} {spec}" for label, spec in rows if spec]
        # There is no console in the normal (background) launch, so point at the
        # things that do exist: the tray icon and the quit hotkey.
        lines += ["  Quit from the tray icon, or with the quit hotkey.", ""]
        return "\n".join(lines)
