"""Shared helpers for the speech benchmarks (WS6): paths, phrases, WAV I/O.

Recordings of the user's voice stay local in %LOCALAPPDATA%\\VoiceVibe\\bench\\
and are never committed; only the phrase list (reference text) is in git.
"""

from __future__ import annotations

import json
import os
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
PHRASES = HERE / "phrases.jsonl"
SAMPLE_RATE = 16000


def bench_dir() -> Path:
    """Where recordings and results live. VOICEVIBE_BENCH overrides it."""
    override = os.environ.get("VOICEVIBE_BENCH")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "VoiceVibe" / "bench"


def load_phrases(path: Path = PHRASES) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def read_manifest(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_manifest(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def write_wav(path: Path, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    """Mono float32 in [-1, 1] -> 16-bit PCM WAV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(pcm.tobytes())


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """16-bit PCM WAV -> (mono float32, sample rate). Stereo is averaged."""
    with wave.open(str(path), "rb") as src:
        if src.getsampwidth() != 2:
            raise ValueError(f"{path}: only 16-bit PCM is supported")
        frames = src.readframes(src.getnframes())
        channels, rate = src.getnchannels(), src.getframerate()
    audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio, rate
