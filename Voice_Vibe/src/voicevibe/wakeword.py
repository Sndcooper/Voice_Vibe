"""Listen for the wake word with a tiny dedicated model, not Whisper.

With the Whisper engine, an armed session transcribes *everything* it hears
just to look for the wake phrase: a full decode per utterance, all day, for
speech that is almost never meant for it. openWakeWord scores 80 ms frames
with a small ONNX model instead -- about 2 ms of CPU per frame -- and Whisper
runs only once the wake word has actually been heard.

Pretrained models: hey_jarvis, alexa, hey_mycroft, hey_rhasspy. There is no
pretrained "hey computer"; a custom phrase needs a model trained with
openWakeWord's tooling, passed here as a path to its .onnx file.

Frames arrive from the audio callback through `feed()`, which only enqueues.
Scoring runs on this module's own thread, so a slow frame can never stall
PortAudio. Optional: needs `openwakeword` (and onnxruntime). Without it,
`WakeWordDetector.create()` returns None and the app keeps the Whisper path.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

log = logging.getLogger(__name__)

FRAME = 1280  # 80 ms at 16 kHz: the chunk openWakeWord scores
SAMPLE_RATE = 16000


def phrase_for(model: str) -> str:
    """The words a model listens for: "hey_jarvis" or ".../hey_jarvis_v0.1.onnx"."""
    stem = Path(model).stem if model.endswith((".onnx", ".tflite")) else model
    stem = stem.split("_v0")[0]
    return " ".join(stem.replace("-", "_").split("_")).strip()


class WakeWordDetector:
    """Scores audio frames; calls `on_detect(name, score)` when one fires.

    `model` is anything with openWakeWord's `predict(int16 frame) -> {name:
    score}` and `reset()`. `create()` builds the real one.
    """

    def __init__(
        self,
        model: Any,
        on_detect: Callable[[str, float], None],
        threshold: float = 0.5,
        cooldown: float = 1.5,
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        self.model = model
        self.on_detect = on_detect
        self.threshold = threshold
        self.cooldown = cooldown
        self.sample_rate = sample_rate
        # Bounded: if scoring ever falls behind, old audio is dropped rather
        # than memory growing without limit.
        self._frames: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=200)
        self._pending = np.zeros(0, dtype=np.int16)
        self._last_fire = 0.0
        self._thread: threading.Thread | None = None

    @classmethod
    def create(cls, model: str, on_detect: Callable[[str, float], None],
               threshold: float = 0.5, sample_rate: int = SAMPLE_RATE) -> WakeWordDetector | None:
        """A detector for a pretrained name or an .onnx path, or None if the
        package or model is unavailable (the caller then stays on Whisper)."""
        if sample_rate != SAMPLE_RATE:
            log.warning("openWakeWord needs 16 kHz audio; [audio].sample_rate is %s.", sample_rate)
            return None
        try:
            from openwakeword import utils
            from openwakeword.model import Model
        except Exception as exc:
            log.warning("openWakeWord is not installed (%s); using Whisper for the wake word.", exc)
            return None
        try:
            if not model.endswith((".onnx", ".tflite")):
                # One-time download of the named model and the shared
                # feature models, a few MB, into the package's folder.
                utils.download_models([model])
            loaded = Model(wakeword_models=[model], inference_framework="onnx")
        except Exception as exc:
            log.warning("Wake word model %r failed to load (%s); using Whisper.", model, exc)
            return None
        log.info("Wake word model ready: %s (say %r).", model, phrase_for(model))
        return cls(loaded, on_detect, threshold=threshold)

    # --------------------------------------------------------------- input
    def feed(self, frame: np.ndarray) -> None:
        """From the audio callback: enqueue a block of float32 samples."""
        try:
            self._frames.put_nowait(frame)
        except queue.Full:
            pass

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="wakeword", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        thread, self._thread = self._thread, None
        if thread is not None:
            self._frames.put(None)
            thread.join(1.0)

    def reset(self) -> None:
        """Forget buffered audio, e.g. when a session is opened or re-armed,
        so a word from minutes ago cannot combine with a new sound."""
        self._pending = np.zeros(0, dtype=np.int16)
        try:
            self.model.reset()
        except Exception:
            pass

    # ------------------------------------------------------------ scoring
    def _run(self) -> None:
        while True:
            frame = self._frames.get()
            if frame is None:
                return
            try:
                self.process(frame)
            except Exception:
                log.exception("Wake word scoring failed; frame skipped.")

    def process(self, frame: np.ndarray) -> None:
        """Score a block (any length); fires at most once per cooldown."""
        pcm = (np.clip(frame, -1.0, 1.0) * 32767).astype(np.int16)
        self._pending = np.concatenate([self._pending, pcm])
        while len(self._pending) >= FRAME:
            chunk, self._pending = self._pending[:FRAME], self._pending[FRAME:]
            scores = self.model.predict(chunk)
            name, score = max(scores.items(), key=lambda kv: kv[1], default=("", 0.0))
            now = time.monotonic()
            if score >= self.threshold and now - self._last_fire >= self.cooldown:
                self._last_fire = now
                log.info("Wake word %r heard (score %.2f).", name, score)
                self.on_detect(name, float(score))
