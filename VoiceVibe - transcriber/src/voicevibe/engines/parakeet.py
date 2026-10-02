"""NVIDIA Parakeet TDT 0.6B v2 on CPU through onnx-asr (WS6).

Built on onnx-asr (github.com/istupakov/onnx-asr, MIT, pip onnx-asr 0.12.0)
and its int8 export `istupakov/parakeet-tdt-0.6b-v2-onnx` of
`nvidia/parakeet-tdt-0.6b-v2` (weights CC-BY-4.0: credit NVIDIA). ~660 MB,
downloaded once into HF_HOME on first use, like a Whisper model.

Why: on this laptop at 4 CPU threads it beat Whisper small.en on the user's
own voice while decoding ~2.5x faster (tools/bench, CONV.md §10), and it
writes punctuation and capitals itself. Limits: English only, CPU only here
(onnxruntime-gpu for Blackwell needs CUDA 13), and no hotwords / prompt
biasing -- `hotwords` and `initial_prompt` are accepted and ignored.

Silence handling: faster-whisper's bundled Silero VAD (MIT) runs first, and
only speech reaches the model, so a silent or noisy take decodes to "" (no
invented "I guess..." sentence). Speech is sent in pieces of at most
MAX_CHUNK_S seconds, the length the model was trained on.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable

import numpy as np

log = logging.getLogger(__name__)

DEFAULT_MODEL = "nemo-parakeet-tdt-0.6b-v2"
MAX_CHUNK_S = 25.0
SAMPLE_RATE = 16000

Loader = Callable[[str, int], Any]
Vad = Callable[[np.ndarray, float], list]


def split_long(audio: np.ndarray, max_seconds: float) -> list[np.ndarray]:
    step = int(max_seconds * SAMPLE_RATE)
    return [audio[i:i + step] for i in range(0, audio.size, step)]


def speech_chunks(audio: np.ndarray, max_seconds: float) -> list[np.ndarray]:
    """Silero VAD from faster-whisper: speech only, merged into <= max_seconds."""
    from faster_whisper.vad import VadOptions, collect_chunks, get_speech_timestamps

    stamps = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=500, speech_pad_ms=300))
    if not stamps:
        return []
    chunks, _ = collect_chunks(audio, stamps, max_duration=max_seconds)
    return [c for c in chunks if c.size]


def load_model(name: str, threads: int) -> Any:
    import onnx_asr
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    # Idle ORT threads spin by default, which takes cores from audio capture.
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    return onnx_asr.load_model(name, quantization="int8", sess_options=options,
                               providers=["CPUExecutionProvider"])


class ParakeetTranscriber:
    hotwords: str | None = None       # accepted for interface parity; not used

    def __init__(self, model_cfg: dict[str, Any], loader: Loader | None = None,
                 vad: Vad | None = None) -> None:
        self.cfg = model_cfg
        self.device = "cpu"
        self.compute_type = "int8"
        self.model_name = str(model_cfg.get("parakeet_model") or DEFAULT_MODEL)
        self.initial_prompt: str | None = None
        threads = int(model_cfg.get("cpu_threads", 0) or 0) or max(1, (os.cpu_count() or 2) - 1)
        self._vad = vad or speech_chunks
        self._lock = threading.Lock()
        log.info("Loading %s on CPU (int8, %d threads). First run downloads ~660 MB.",
                 self.model_name, threads)
        self.model = (loader or load_model)(self.model_name, threads)

    def warmup(self, sample_rate: int = SAMPLE_RATE) -> None:
        """One real decode so the first dictation is not slow. Never raises."""
        noise = np.random.default_rng(0).normal(0.0, 1e-3, sample_rate).astype(np.float32)
        try:
            self.model.recognize(noise, sample_rate=SAMPLE_RATE)
        except Exception as exc:  # noqa: BLE001
            log.warning("Parakeet warmup failed: %s", exc)

    def transcribe(self, audio: np.ndarray, beam_size: int | None = None,
                   wait: bool = True) -> str | None:
        """Same contract as Transcriber.transcribe; `beam_size` is ignored."""
        if not self._lock.acquire(blocking=wait):
            return None
        try:
            return self._transcribe(audio)
        finally:
            self._lock.release()

    def _transcribe(self, audio: np.ndarray) -> str:
        if not audio.size:
            return ""
        audio = audio.astype(np.float32, copy=False)
        if self.cfg.get("vad_filter", True):
            pieces = self._vad(audio, MAX_CHUNK_S)
        else:
            pieces = split_long(audio, MAX_CHUNK_S)
        texts = [str(self.model.recognize(p, sample_rate=SAMPLE_RATE)).strip() for p in pieces if p.size]
        return " ".join(t for t in texts if t).strip()
