"""faster-whisper wrapper. Picks a sane device/compute_type and falls back to CPU."""

from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from .cuda_setup import cuda_available, register_cuda_dlls

log = logging.getLogger(__name__)

# Short aliases -> Hugging Face repos, so config stays readable.
MODEL_ALIASES = {
    "large-v3-turbo": "deepdml/faster-whisper-large-v3-turbo-ct2",
    "turbo": "deepdml/faster-whisper-large-v3-turbo-ct2",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
}


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

        name = str(model_cfg.get("name", "large-v3-turbo"))
        self.model_name = MODEL_ALIASES.get(name, name)

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
            )
        except Exception as exc:
            if self.device == "cpu":
                raise
            log.warning("GPU load failed (%s). Falling back to CPU int8.", exc)
            self.device, self.compute_type = "cpu", "int8"
            self.model = WhisperModel(
                self.model_name, device="cpu", compute_type="int8"
            )
        log.info("Model ready in %.1fs", time.perf_counter() - started)

    def warmup(self, sample_rate: int = 16000) -> None:
        """Run one tiny inference so the first real dictation is not slow."""
        silence = np.zeros(sample_rate, dtype=np.float32)
        try:
            segments, _ = self.model.transcribe(silence, beam_size=1, vad_filter=False)
            list(segments)
        except Exception as exc:  # pragma: no cover - warmup is best effort
            log.debug("warmup failed: %s", exc)

    def transcribe(self, audio: np.ndarray) -> str:
        language = self.cfg.get("language", "en")
        if isinstance(language, str) and language.lower() in ("", "auto", "none"):
            language = None
        prompt = self.cfg.get("initial_prompt") or None

        segments, _info = self.model.transcribe(
            audio,
            language=language,
            beam_size=int(self.cfg.get("beam_size", 1) or 1),
            vad_filter=bool(self.cfg.get("vad_filter", True)),
            condition_on_previous_text=False,
            initial_prompt=prompt,
        )
        return "".join(segment.text for segment in segments).strip()
