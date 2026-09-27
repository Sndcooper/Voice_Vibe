"""Microphone capture. Records into memory as float32 mono at the model's rate."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Callable

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)


class Recorder:
    """Start/stop microphone capture and hand back a mono float32 numpy array."""

    def __init__(
        self,
        sample_rate: int = 16000,
        device: int | str | None = None,
        max_duration: float = 300.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.device = device
        self.max_frames = int(max_duration * sample_rate)
        self._stream: sd.InputStream | None = None
        # Stream taken out of `_stream` but not yet drained and closed.
        self._closing: sd.InputStream | None = None
        self._chunks: list[np.ndarray] = []
        self._frames = 0
        self._lock = threading.Lock()
        self._overflowed = False

    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    def detach(self) -> None:
        """Mark the recording finished without paying for the drain yet.

        Lets a caller drop its state lock before the ~0.3s close in `stop()`.
        """
        if self._stream is not None:
            self._closing, self._stream = self._stream, None

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        if status:
            log.debug("audio status: %s", status)
        with self._lock:
            if self._frames >= self.max_frames:
                self._overflowed = True
                return
            self._chunks.append(indata[:, 0].copy())
            self._frames += frames

    def start(self) -> None:
        if self._stream is not None:
            return
        with self._lock:
            self._chunks = []
            self._frames = 0
            self._overflowed = False
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            device=self.device,
            channels=1,
            dtype="float32",
            blocksize=0,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        self.detach()
        stream, self._closing = self._closing, None
        if stream is not None:
            try:
                # Frames still sitting in the driver buffer have not reached the
                # callback yet. Without this drain the last ~0.3s is lost, which
                # clips the final word of a dictation.
                latency = float(getattr(stream, "latency", 0.0) or 0.0)
                time.sleep(min(0.3, latency + 0.06))
                stream.stop()
            finally:
                stream.close()
        with self._lock:
            chunks, self._chunks = self._chunks, []
            overflowed, self._overflowed = self._overflowed, False
            self._frames = 0
        if overflowed:
            log.warning(
                "Recording hit the %.0fs cap and was truncated; raise "
                "[audio].max_duration if you need longer takes.",
                self.max_frames / float(self.sample_rate),
            )
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks).astype(np.float32, copy=False)

    def abort(self) -> None:
        self.stop()

    def duration(self, audio: np.ndarray) -> float:
        return len(audio) / float(self.sample_rate)


class SegmentRecorder:
    """Never-ending capture that emits one segment per utterance.

    Speech is detected against an adapting noise floor rather than a fixed
    level, so it works in a quiet room and a noisy one without retuning. A
    segment ends after `silence_duration` of quiet and is handed to
    `on_segment`; recording continues immediately afterwards.

    `on_segment` runs on the PortAudio callback thread, so it must only enqueue
    work and return.
    """

    BLOCK_SECONDS = 0.03

    def __init__(
        self,
        sample_rate: int,
        device: int | str | None,
        on_segment: Callable[[np.ndarray], None],
        silence_duration: float = 1.5,
        speech_ratio: float = 4.0,
        min_rms: float = 0.006,
        min_segment: float = 0.4,
        max_segment: float = 60.0,
        pre_roll: float = 0.35,
    ) -> None:
        self.sample_rate = sample_rate
        self.device = device
        self.on_segment = on_segment
        self.speech_ratio = speech_ratio
        self.min_rms = min_rms

        self.block = max(160, int(sample_rate * self.BLOCK_SECONDS))
        block_seconds = self.block / sample_rate
        self._silence_needed = max(1, int(round(silence_duration / block_seconds)))
        self._min_voiced = max(1, int(round(min_segment / block_seconds)))
        self._max_blocks = max(self._min_voiced, int(round(max_segment / block_seconds)))
        # Silence left on the end of a segment so a final consonant survives.
        self._tail_blocks = max(1, int(round(0.25 / block_seconds)))
        # Keeping a little audio from before onset stops the VAD clipping the
        # first syllable of a sentence.
        self._pre_roll = deque(maxlen=max(1, int(round(pre_roll / block_seconds))))

        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._speech: list[np.ndarray] = []
        self._in_speech = False
        self._silence_blocks = 0
        self._voiced_blocks = 0
        self._voiced_run = 0
        self._noise: float | None = None
        self.segments = 0

    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    def _take_locked(self) -> np.ndarray | None:
        """Close off the current utterance and return it. Caller holds the lock."""
        chunks, self._speech = self._speech, []
        voiced_blocks = self._voiced_blocks
        trailing_silence = self._silence_blocks
        self._in_speech = False
        self._silence_blocks = 0
        self._voiced_blocks = 0
        self._voiced_run = 0
        self._pre_roll.clear()

        # Measured on voiced blocks only. The buffer also holds pre-roll and the
        # trailing pause, so its length is not a usable duration filter.
        if voiced_blocks < self._min_voiced:
            return None

        # Hand Whisper the speech, not the pause that ended it.
        surplus = trailing_silence - self._tail_blocks
        if surplus > 0 and surplus < len(chunks):
            chunks = chunks[:-surplus]
        if not chunks:
            return None

        self.segments += 1
        return np.concatenate(chunks).astype(np.float32, copy=False)

    def _deliver(self, audio: np.ndarray | None) -> None:
        """Hand a finished segment to the consumer. Must run with the lock released."""
        if audio is None:
            return
        try:
            self.on_segment(audio)
        except Exception:
            log.exception("segment handler failed")

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        if status:
            log.debug("audio status: %s", status)
        mono = indata[:, 0].copy()
        rms = float(np.sqrt(np.mean(mono * mono)) + 1e-12)
        finished: np.ndarray | None = None

        with self._lock:
            if self._noise is None:
                self._noise = rms
            threshold = max(self.min_rms, self._noise * self.speech_ratio)
            voiced = rms > threshold

            if self._in_speech:
                self._speech.append(mono)
                if voiced:
                    self._silence_blocks = 0
                    self._voiced_blocks += 1
                else:
                    self._silence_blocks += 1
                if (
                    self._silence_blocks >= self._silence_needed
                    or len(self._speech) >= self._max_blocks
                ):
                    finished = self._take_locked()
            else:
                self._track_onset_locked(mono, voiced, rms)

        # Outside the lock: the handler must not be able to stall the next block.
        self._deliver(finished)

    def _track_onset_locked(self, mono: np.ndarray, voiced: bool, rms: float) -> None:
        # Idle: track the room's noise level and watch for speech onset.
        # Only quiet blocks feed the estimate, otherwise the onset of every
        # sentence drags the floor upward until speech stops registering.
        if not voiced:
            self._noise = 0.95 * self._noise + 0.05 * rms
        self._pre_roll.append(mono)
        if not voiced:
            self._voiced_run = 0
            return
        self._voiced_run += 1
        if self._voiced_run >= 2:  # two blocks avoids keyboard-click triggers
            self._in_speech = True
            self._speech = list(self._pre_roll)
            self._pre_roll.clear()
            self._silence_blocks = 0

    def start(self) -> None:
        if self._stream is not None:
            return
        with self._lock:
            self._speech = []
            self._in_speech = False
            self._silence_blocks = 0
            self._voiced_blocks = 0
            self._voiced_run = 0
            self._noise = None
            self._pre_roll.clear()
            self.segments = 0
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            device=self.device,
            channels=1,
            dtype="float32",
            blocksize=self.block,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        """Stop capture and flush whatever was mid-sentence."""
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            latency = float(getattr(stream, "latency", 0.0) or 0.0)
            time.sleep(min(0.3, latency + 0.06))
            stream.stop()
        finally:
            stream.close()
        finished: np.ndarray | None = None
        with self._lock:
            if self._in_speech:
                finished = self._take_locked()
            else:
                self._speech = []
        self._deliver(finished)


# Loopback inputs record what the speakers are playing, not what is said. Realtek
# drivers ship "Stereo Mix" enabled, and it sometimes ends up as the Windows
# default input, at which point every recording is silence and nothing explains why.
_LOOPBACK_HINTS = (
    "stereo mix",
    "what u hear",
    "wave out",
    "output mix",
    "loopback",
    "rec. playback",
    "pc speaker",
)

# Virtual devices that forward to whatever Windows has set as the default. They
# are useless as a fallback: if the default is a loopback, so are these.
_ALIAS_HINTS = ("sound mapper", "primary sound capture", "primary sound driver")

_MIC_HINTS = ("microphone", "mic ", "mic(", "headset")


def is_loopback(name: str) -> bool:
    lowered = str(name).lower()
    return any(hint in lowered for hint in _LOOPBACK_HINTS)


def _is_alias(name: str) -> bool:
    lowered = str(name).lower()
    return any(hint in lowered for hint in _ALIAS_HINTS)


def _input_devices() -> list[tuple[int, dict]]:
    try:
        return [
            (index, dev)
            for index, dev in enumerate(sd.query_devices())
            if dev.get("max_input_channels", 0) > 0
        ]
    except Exception as exc:
        log.debug("could not query devices: %s", exc)
        return []


def default_input_device(priority: list[str] | None = None) -> int | None:
    """The device to record from when config leaves `input_device` empty.

    Normally the Windows default, but never a loopback: recording the speakers
    produces silence that looks identical to a broken microphone. When the
    default is one, fall back to a real input instead of failing quietly.
    """
    devices = _input_devices()
    if not devices:
        return None

    try:
        default = sd.default.device[0]
    except Exception:
        default = None

    # Explicit preferences can include loopback inputs. Match full names first
    # so "Microphone" never accidentally selects "Microphone Array".
    for preferred in priority or []:
        wanted = preferred.strip().casefold()
        if not wanted:
            continue
        candidates = [(i, d) for i, d in devices
                      if d["name"].strip().casefold() == wanted]
        if not candidates:
            candidates = [(i, d) for i, d in devices
                          if wanted in d["name"].casefold() and not _is_alias(d["name"])]
        if candidates:
            chosen, dev = min(candidates, key=lambda entry: (entry[0] != default, entry[0]))
            log.info("Preferred input [%d] %s.", chosen, dev["name"])
            return chosen

    names = dict(devices)
    if default is not None and default in names and not is_loopback(names[default]["name"]):
        return None  # the system default is fine; let PortAudio use it

    usable = [
        (i, d)
        for i, d in devices
        if not is_loopback(d["name"]) and not _is_alias(d["name"])
    ]
    if not usable:
        log.warning("Every input device looks like a loopback; recordings may be silent.")
        return None

    def rank(entry: tuple[int, dict]) -> tuple[int, int]:
        index, dev = entry
        lowered = dev["name"].lower()
        looks_like_mic = any(hint in lowered for hint in _MIC_HINTS)
        return (0 if looks_like_mic else 1, index)

    chosen = min(usable, key=rank)[0]
    if default is not None and default in names:
        log.warning(
            "Default input [%d] %s is a loopback device and records silence, "
            "not speech. Using [%d] %s instead. Set [audio].input_device to "
            "override.",
            default,
            names[default]["name"],
            chosen,
            names[chosen]["name"],
        )
    return chosen


def describe_devices() -> str:
    lines = ["Input devices:"]
    try:
        default_in = sd.default.device[0]
    except Exception:
        default_in = None
    for index, dev in _input_devices():
        marks = []
        if index == default_in:
            marks.append("default")
        if is_loopback(dev["name"]):
            marks.append("loopback -- records the speakers, not you")
        suffix = f"  ({', '.join(marks)})" if marks else ""
        lines.append(f"  [{index}] {dev['name']}{suffix}")
    return "\n".join(lines)
