"""faster-whisper wrapper. Picks a sane device/compute_type and falls back to CPU."""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from .cuda_setup import cuda_available, register_cuda_dlls

log = logging.getLogger(__name__)

# [model].temperature_fallback: retried warmer only when a decode loops or is
# unsure, so a clean decode stays deterministic (the first entry is 0).
FALLBACK_TEMPERATURES = (0.0, 0.2, 0.4, 0.6)
MODEL_ALIASES = {
    "large-v3-turbo": "deepdml/faster-whisper-large-v3-turbo-ct2",
    "turbo": "deepdml/faster-whisper-large-v3-turbo-ct2",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
    "distil-small.en": "Systran/faster-distil-whisper-small.en",
    "distil-medium.en": "Systran/faster-distil-whisper-medium.en",
}


_SIZES = ("tiny", "base", "small", "medium")


def model_size(name: str) -> int:
    """Rough size rank: tiny 0, base 1, small 2, medium 3, anything large 4."""
    lowered = name.lower()
    for rank, size in enumerate(_SIZES):
        if size in lowered and "large" not in lowered:
            return rank
    return len(_SIZES)


def choose_command_model(setting: str, main_model: str, language: str | None) -> str | None:
    """Which model to load for commands, or None to use the main one.

    "auto" means base.en (base for other languages): accurate enough for
    short fixed phrases and several times faster than a dictation-sized
    model. Not worth a second load when the main model is no bigger.
    """
    setting = (setting or "").strip()
    if setting.lower() in ("", "none", "off", "false"):
        return None
    if setting.lower() == "auto":
        english = (language or "").lower() in ("en", "english")
        setting = "base.en" if english else "base"
    if model_size(main_model) <= model_size(setting):
        return None
    return setting


def memory_gb() -> tuple[float, float]:
    """(total, free) system RAM in GB. Zeros if it cannot be determined."""
    if sys.platform == "win32":
        class _Status(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        try:
            status = _Status()
            status.dwLength = ctypes.sizeof(_Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                gb = 1024.0**3
                return status.ullTotalPhys / gb, status.ullAvailPhys / gb
        except Exception:
            pass
    try:
        gb = 1024.0**3
        pages = os.sysconf("SC_PHYS_PAGES")
        size = os.sysconf("SC_PAGE_SIZE")
        return pages * size / gb, 0.0
    except (ValueError, AttributeError, OSError):
        return 0.0, 0.0


@dataclass(frozen=True)
class Tier:
    model: str
    compute: str
    note: str


# Ordered worst-hardware-first. The English-only `.en` builds are both smaller
# and more accurate than their multilingual siblings at the same size, which is
# the right trade on a machine that cannot afford a larger model.
def recommend_tier() -> Tier:
    """Pick a model that will actually keep up on this machine.

    Defaults target low-spec laptops: no discrete GPU, few cores, little RAM.
    A big model that takes eight seconds per sentence is unusable for dictation
    regardless of how accurate it is.
    """
    if cuda_available():
        return Tier("large-v3-turbo", "float16", "GPU available")
    return recommend_tier_for_cpu()


def recommend_tier_for_cpu() -> Tier:
    """The best model for this machine's CPU, ignoring any GPU."""
    total, _ = memory_gb()
    cores = os.cpu_count() or 2

    if total and total < 4.0:
        return Tier("tiny.en", "int8", "under 4 GB RAM")
    if cores >= 8 and (not total or total >= 8.0):
        return Tier("small.en", "int8", "8+ cores")
    if cores >= 4:
        return Tier("base.en", "int8", "4+ cores")
    return Tier("tiny.en", "int8", "2 cores or fewer")


class Transcriber:
    # Set by the app from [vocab].hotwords; a class default so tests that
    # build a Transcriber without __init__ still work.
    hotwords: str | None = None

    def __init__(self, model_cfg: dict[str, Any]) -> None:
        register_cuda_dlls()

        self.cfg = model_cfg
        requested = str(model_cfg.get("device", "auto")).lower()
        if requested == "auto":
            self.device = "cuda" if cuda_available() else "cpu"
        else:
            self.device = requested
        if self.device == "cuda" and not cuda_available():
            log.warning("CUDA requested but no usable CUDA device found; using CPU.")
            self.device = "cpu"

        compute = str(model_cfg.get("compute_type", "auto")).lower()
        if compute == "auto":
            compute = "float16" if self.device == "cuda" else "int8"
        self.compute_type = compute

        name = str(model_cfg.get("name", "auto")).lower()
        if name == "auto":
            tier = recommend_tier() if self.device == "cuda" else recommend_tier_for_cpu()
            name = tier.model
            log.info("Model auto-selected: %s (%s).", name, tier.note)
        self.model_name = MODEL_ALIASES.get(name, name)

        # CPU inference spawns one thread per core by default, which starves the
        # audio callback on a 2- or 4-core laptop and causes dropped frames.
        workers = max(1, (os.cpu_count() or 2) - 1) if self.device == "cpu" else 0
        threads = int(model_cfg.get("cpu_threads", 0) or 0) or workers

        from faster_whisper import WhisperModel

        log.info(
            "Loading %s on %s (%s). First run downloads the model.",
            self.model_name,
            self.device,
            self.compute_type,
        )
        started = time.perf_counter()
        try:
            self.model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
                cpu_threads=threads if self.device == "cpu" else 0,
            )
        except Exception as exc:
            if self.device == "cpu":
                raise
            # A GPU-sized model on a CPU that was never meant to run it takes
            # many seconds per sentence, so drop to what this machine can serve.
            fallback = recommend_tier_for_cpu()
            log.warning(
                "GPU load failed (%s). Falling back to %s on CPU.", exc, fallback.model
            )
            self.device, self.compute_type = "cpu", fallback.compute
            self.model_name = MODEL_ALIASES.get(fallback.model, fallback.model)
            self.model = WhisperModel(
                self.model_name,
                device="cpu",
                compute_type=self.compute_type,
                cpu_threads=int(model_cfg.get("cpu_threads", 0) or 0)
                or max(1, (os.cpu_count() or 2) - 1),
            )
        log.info("Model ready in %.1fs", time.perf_counter() - started)

        # Set by the app when wake phrases bias the decoder. Kept off `cfg` so
        # biasing stays idempotent instead of concatenating on every call.
        self.initial_prompt: str | None = str(model_cfg.get("initial_prompt") or "") or None

    def warmup(self, sample_rate: int = 16000) -> None:
        """Run one tiny inference so the first real dictation is not slow.

        This is also the only place a broken GPU install surfaces. Loading a
        model onto CUDA succeeds even when the cuBLAS/cuDNN runtime is missing;
        it only fails on the first actual compute. Left unhandled that turns
        every dictation into a silent failure, so a GPU warmup that fails
        rebuilds the model on CPU rather than being swallowed.
        """
        silence = np.zeros(sample_rate, dtype=np.float32)
        try:
            segments, _ = self.model.transcribe(silence, beam_size=1, vad_filter=False)
            list(segments)
            return
        except Exception as exc:
            if self.device != "cuda":
                log.warning("Warmup failed: %s", exc)
                return
            log.error(
                "GPU inference is not usable (%s). The CUDA runtime is probably "
                'missing -- install it with:  uv pip install -e ".[cuda]"  '
                "Falling back to CPU for now.",
                exc,
            )

        from faster_whisper import WhisperModel

        fallback = recommend_tier_for_cpu()
        self.device, self.compute_type = "cpu", fallback.compute
        self.model_name = MODEL_ALIASES.get(fallback.model, fallback.model)
        self.model = WhisperModel(
            self.model_name, device="cpu", compute_type=self.compute_type
        )
        log.warning("Now running %s on CPU (%s).", self.model_name, self.compute_type)

    def _decode_lock(self) -> threading.Lock:
        lock = self.__dict__.get("_lock")
        if lock is None:
            lock = self.__dict__.setdefault("_lock", threading.Lock())
        return lock

    def transcribe(self, audio: np.ndarray, beam_size: int | None = None,
                   wait: bool = True) -> str | None:
        """Decode `audio`. One decode at a time per model.

        `wait=False` is for interim transcripts: if the model is busy (with
        the final transcript, which matters more) return None at once
        instead of queueing behind it. `beam_size` overrides the configured
        one, e.g. 1 for a quick interim pass.
        """
        lock = self._decode_lock()
        if not lock.acquire(blocking=wait):
            return None
        try:
            return self._transcribe(audio, beam_size)
        finally:
            lock.release()

    def _transcribe(self, audio: np.ndarray, beam_size: int | None) -> str:
        language = self.cfg.get("language", "en")
        if isinstance(language, str) and language.lower() in ("", "auto", "none"):
            language = None

        # Only an empty buffer can be skipped safely without decoding it.
        # Amplitude is not evidence that a recording contains no speech.
        if not audio.size:
            return ""

        fallback = bool(self.cfg.get("temperature_fallback", False))
        segments, _info = self.model.transcribe(
            audio,
            language=language,
            beam_size=int(beam_size or self.cfg.get("beam_size", 3) or 3),
            vad_filter=bool(self.cfg.get("vad_filter", False)),
            # Deterministic by default. With temperature_fallback, a decode that
            # loops ("...fix it and then write it up and then...") or is unsure
            # trips faster-whisper's compression-ratio / log-prob checks and is
            # decoded again, warmer.
            temperature=list(FALLBACK_TEMPERATURES) if fallback else 0.0,
            condition_on_previous_text=False,
            initial_prompt=self.initial_prompt,
            # Sits beside initial_prompt in the decoder context; only a
            # `prefix` would disable it, and none is used.
            hotwords=self.hotwords,
            # Disable silence-based skipping by default. The log-probability
            # threshold still controls decoder fallback, not a post-decode drop.
            no_speech_threshold=self.cfg.get("no_speech_threshold"),
            log_prob_threshold=float(self.cfg.get("log_prob_threshold", -1.0)),
        )
        kept = []
        for segment in segments:
            if self._unsure_short(segment):
                log.info("Dropped an unsure short segment %r (avg_logprob %.2f).",
                         segment.text.strip(), segment.avg_logprob)
                continue
            kept.append(segment.text)
        return "".join(kept).strip()

    def _unsure_short(self, segment: object) -> bool:
        """[model].drop_unsure_short: a few words the decoder was unsure of.

        Measured 2026-09-29: real speech decodes at avg_logprob -0.18 to -0.23,
        silence phantoms ("Thank you.", "Yeah, yeah") at -0.4 to -1.8.
        """
        if not self.cfg.get("drop_unsure_short", False):
            return False
        words = len(str(getattr(segment, "text", "")).split())
        logprob = float(getattr(segment, "avg_logprob", 0.0))
        return (words <= int(self.cfg.get("unsure_max_words", 5))
                and logprob < float(self.cfg.get("unsure_logprob", -0.8)))
