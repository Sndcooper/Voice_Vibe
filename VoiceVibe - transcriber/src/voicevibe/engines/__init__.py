"""Speech-to-text engines behind one interface (WS6).

`create(model_cfg)` returns an object that behaves like
`voicevibe.transcriber.Transcriber`: `transcribe(audio, beam_size=None,
wait=True)`, `warmup()`, and the attributes `model_name`, `device`,
`compute_type`, `hotwords`, `initial_prompt`, `cfg`.

[model].engine:
  "whisper"  faster-whisper (default; the only GPU engine)
  "parakeet" NVIDIA Parakeet TDT 0.6B v2 int8 on CPU via onnx-asr
             (pip `onnx-asr`, extra `parakeet`); see engines/parakeet.py
  "auto"     Whisper when a GPU is used, Parakeet on CPU-only machines
             (unless [model].name pins a Whisper model)
A missing or broken optional engine falls back to Whisper (rule 19).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

log = logging.getLogger(__name__)

ENGINES = ("whisper", "parakeet", "auto")


def _cuda() -> bool:
    from ..cuda_setup import cuda_available

    return cuda_available()


def wanted(model_cfg: dict[str, Any], cuda: Callable[[], bool] = _cuda) -> str:
    """The engine to try first: "whisper" or "parakeet"."""
    name = str(model_cfg.get("engine", "whisper") or "whisper").strip().lower()
    if name == "auto":
        pinned = str(model_cfg.get("name", "auto") or "auto").strip().lower() != "auto"
        device = str(model_cfg.get("device", "auto") or "auto").strip().lower()
        on_cpu = device == "cpu" or (device == "auto" and not cuda())
        return "parakeet" if on_cpu and not pinned else "whisper"
    if name in ("whisper", "faster-whisper", "faster_whisper", ""):
        return "whisper"
    if name == "parakeet":
        return "parakeet"
    log.warning("Unknown [model].engine %r; using Whisper.", name)
    return "whisper"


def create(model_cfg: dict[str, Any], *, whisper: Callable | None = None,
           parakeet: Callable | None = None, cuda: Callable[[], bool] = _cuda) -> Any:
    choice = wanted(model_cfg, cuda)
    if choice == "parakeet":
        try:
            if parakeet is None:
                from .parakeet import ParakeetTranscriber as parakeet
            return parakeet(model_cfg)
        except Exception as exc:  # noqa: BLE001 - optional engine: degrade to Whisper
            level = logging.INFO if str(model_cfg.get("engine", "")).lower() == "auto" else logging.WARNING
            log.log(level, "Parakeet engine unavailable (%s); using Whisper.", exc)
    if whisper is None:
        from ..transcriber import Transcriber as whisper
    return whisper(model_cfg)
