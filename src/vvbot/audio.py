"""Voice-note audio -> 16 kHz mono WAV for Voice Vibe's Whisper, via PyAV.

Replaces upstream's pydub + ffmpeg-binary conversion (TASK.md §2: PyAV, not
pydub/ffmpeg). PyAV ships its own FFmpeg libraries, so Telegram's OGG/Opus
voice notes, MP3/M4A audio files and MP4 video notes all decode in-process.
"""

from __future__ import annotations

import io
import wave

RATE = 16000
MAX_SECONDS = 300


class AudioError(ValueError):
    pass


def to_wav(data: bytes, rate: int = RATE, max_seconds: float = MAX_SECONDS) -> bytes:
    try:
        import av
    except ImportError as exc:  # pragma: no cover - the bot venv always has it
        raise AudioError("PyAV is not installed") from exc
    limit = int(rate * max_seconds) * 2
    pcm = bytearray()
    try:
        with av.open(io.BytesIO(data), mode="r") as container:
            if not container.streams.audio:
                raise AudioError("no audio in that file")
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)

            def take(frames) -> None:
                for out in frames:
                    pcm.extend(bytes(out.planes[0])[: out.samples * 2])
                if len(pcm) > limit:
                    raise AudioError(f"voice note longer than {int(max_seconds)} s")

            for frame in container.decode(stream):
                take(resampler.resample(frame))
            take(resampler.resample(None))
    except AudioError:
        raise
    except Exception as exc:  # noqa: BLE001 - av raises many error types
        raise AudioError(f"couldn't read that audio ({type(exc).__name__})") from exc
    if not pcm:
        raise AudioError("that audio is empty")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(bytes(pcm))
    return buf.getvalue()
