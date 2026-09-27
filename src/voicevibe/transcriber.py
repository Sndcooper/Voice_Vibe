"""faster-whisper wrapper. Picks a sane device/compute_type and falls back to CPU."""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from .cuda_setup import cuda_available, register_cuda_dlls

log = logging.getLogger(__name__)

# Short aliases -> Hugging Face repos, so config stays readable.
MODEL_ALIASES = {
    "large-v3-turbo": "deepdml/faster-whisper-large-v3-turbo-ct2",
    "turbo": "deepdml/faster-whisper-large-v3-turbo-ct2",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
    "distil-small.en": "Systran/faster-distil-whisper-small.en",
    "distil-medium.en": "Systran/faster-distil-whisper-medium.en",
}


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
            tier = recommend_tier()
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
            fallback = recommend_tier()
            log.warning(
                "GPU load failed (%s). Falling back to %s on CPU.", exc, fallback.model
            )
            self.device, self.compute_type = "cpu", fallback.compute
            self.model_name = MODEL_ALIASES.get(fallback.model, fallback.model)
            self.model = WhisperModel(
                self.model_name,
                device="cpu",
                compute_type=self.compute_type,
                cpu_threads=workers,
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

    def transcribe(self, audio: np.ndarray) -> str:
        language = self.cfg.get("language", "en")
        if isinstance(language, str) and language.lower() in ("", "auto", "none"):
            language = None
        prompt = self.initial_prompt

        segments, _info = self.model.transcribe(
            audio,
            language=language,
            beam_size=int(self.cfg.get("beam_size", 1) or 1),
            vad_filter=bool(self.cfg.get("vad_filter", True)),
            condition_on_previous_text=False,
            initial_prompt=prompt,
        )
        return "".join(segment.text for segment in segments).strip()
