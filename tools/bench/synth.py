"""Synthetic benchmark audio (WS6): every phrase in two SAPI voices, one of
them also with background noise, plus non-speech clips (digital silence,
room-tone-like noise, clicks). Writes %LOCALAPPDATA%\\VoiceVibe\\bench\\synth\\.

    ..\\venvs\\voicevibe\\Scripts\\python.exe tools\\bench\\synth.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

from common import SAMPLE_RATE, bench_dir, load_phrases, read_wav, write_manifest, write_wav

SAFT16kHz16BitMono = 18
SSFMCreateForWrite = 3
LEAD, TAIL = 0.3, 0.6          # seconds of silence around speech, like a real take


def sapi_voices() -> dict[str, object]:
    import comtypes.client

    voice = comtypes.client.CreateObject("SAPI.SpVoice")
    tokens = voice.GetVoices()
    return {tokens.Item(i).GetDescription(): tokens.Item(i) for i in range(tokens.Count)}


def speak(text: str, token: object, path: Path) -> None:
    import comtypes.client

    voice = comtypes.client.CreateObject("SAPI.SpVoice")
    fmt = comtypes.client.CreateObject("SAPI.SpAudioFormat")
    fmt.Type = SAFT16kHz16BitMono
    stream = comtypes.client.CreateObject("SAPI.SpFileStream")
    stream.Format = fmt
    stream.Open(str(path), SSFMCreateForWrite)
    try:
        voice.AudioOutputStream = stream
        voice.Voice = token
        voice.Speak(text)
    finally:
        stream.Close()


def pad(audio: np.ndarray) -> np.ndarray:
    return np.concatenate([np.zeros(int(LEAD * SAMPLE_RATE), np.float32), audio,
                           np.zeros(int(TAIL * SAMPLE_RATE), np.float32)])


def add_noise(audio: np.ndarray, snr_db: float, rng: np.random.Generator) -> np.ndarray:
    speech = audio[np.abs(audio) > 1e-4]
    power = float(np.mean(speech ** 2)) if speech.size else 1e-6
    noise = rng.normal(0.0, np.sqrt(power / 10 ** (snr_db / 10)), audio.size).astype(np.float32)
    return np.clip(audio + noise, -1.0, 1.0)


def non_speech(rng: np.random.Generator) -> dict[str, np.ndarray]:
    n = 5 * SAMPLE_RATE
    clicks = np.zeros(n, np.float32)
    for start in rng.integers(0, n - 200, 40):
        clicks[start:start + 120] += rng.normal(0, 0.15, 120).astype(np.float32) * np.hanning(120)
    return {"s-digital": np.zeros(n, np.float32),
            "s-room": rng.normal(0, 0.0015, n).astype(np.float32),
            "s-hum": (0.004 * np.sin(2 * np.pi * 50 * np.arange(n) / SAMPLE_RATE)
                      + rng.normal(0, 0.001, n)).astype(np.float32),
            "n-clicks": np.clip(clicks + rng.normal(0, 0.001, n).astype(np.float32), -1, 1)}


def main() -> int:
    out = bench_dir() / "synth"
    voices = sapi_voices()
    wanted = [(name, token) for name, token in voices.items()
              if any(k in name for k in ("David", "Zira", "Mark"))][:2] or list(voices.items())[:2]
    if not wanted:
        sys.exit("No SAPI voices installed.")
    rng = np.random.default_rng(7)
    rows = []
    speech = [p for p in load_phrases() if p["kind"] not in ("silence", "noise")]
    with tempfile.TemporaryDirectory() as tmp:
        for index, (name, token) in enumerate(wanted):
            tag = "sapi-" + name.split()[1].lower() if len(name.split()) > 1 else f"sapi-{index}"
            for phrase in speech:
                raw = Path(tmp) / f"{tag}-{phrase['id']}.wav"
                speak(phrase["text"], token, raw)
                audio, _ = read_wav(raw)
                audio = pad(audio)
                sets = [(tag, audio)]
                if index == 0:
                    sets.append((tag + "-noisy15", add_noise(audio, 15.0, rng)))
                for set_name, clip in sets:
                    rel = f"{set_name}/{phrase['id']}.wav"
                    write_wav(out / rel, clip)
                    rows.append({"id": phrase["id"], "set": set_name, "kind": phrase["kind"],
                                 "text": phrase["text"], "wav": rel,
                                 "seconds": round(clip.size / SAMPLE_RATE, 2)})
            print(f"{tag}: {len(speech)} phrases ({name})", flush=True)
    for clip_id, clip in non_speech(rng).items():
        rel = f"nonspeech/{clip_id}.wav"
        write_wav(out / rel, clip)
        rows.append({"id": clip_id, "set": "nonspeech", "kind": "silence" if clip_id.startswith("s-") else "noise",
                     "text": "", "wav": rel, "seconds": 5.0})
    write_manifest(out / "manifest.jsonl", rows)
    print(f"{len(rows)} clips -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
