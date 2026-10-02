"""Interactive checks: microphone levels, then a full record -> transcribe run."""

from __future__ import annotations

import sys
import time

import numpy as np

from .audio import Recorder
from .config import Config

_BAR_WIDTH = 40


def _meter(level: float) -> str:
    """Log-scaled level bar. Speech should reach the middle of the bar."""
    if level <= 0:
        db = -100.0
    else:
        db = 20.0 * np.log10(level)
    filled = int(round(_BAR_WIDTH * max(0.0, (db + 60.0) / 60.0)))
    return "[" + "#" * filled + "-" * (_BAR_WIDTH - filled) + f"] {db:6.1f} dB"


def _recorder(config: Config) -> Recorder:
    return Recorder(
        sample_rate=int(config.audio["sample_rate"]),
        device=config.input_device,
        max_duration=300.0,
    )


def mic_test(config: Config, seconds: float = 5.0) -> int:
    """Record for `seconds` with a live level meter, then report."""
    recorder = _recorder(config)

    print(f"\nRecording {seconds:.0f}s. Talk at your normal volume.\n")
    try:
        recorder.start()
    except Exception as exc:
        print(f"Could not open the microphone: {exc}")
        return 1

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(0.1)
        with recorder._lock:  # noqa: SLF001 - reading the live buffer on purpose
            recent = recorder._chunks[-4:]  # noqa: SLF001
        level = float(np.abs(np.concatenate(recent)).max()) if recent else 0.0
        remaining = max(0.0, deadline - time.monotonic())
        sys.stdout.write(f"\r  {_meter(level)}  {remaining:4.1f}s left ")
        sys.stdout.flush()

    audio = recorder.stop()
    print("\n")

    if audio.size == 0:
        print("FAIL  no audio frames arrived from the device.")
        return 1

    peak = float(np.abs(audio).max())
    rms = float(np.sqrt((audio**2).mean()))
    print(f"  duration  {recorder.duration(audio):.2f}s")
    print(f"  peak      {peak:.5f}")
    print(f"  rms       {rms:.5f}")

    if peak < 1e-4:
        print(
            "\nFAIL  the device is delivering silence.\n"
            "  1. Settings > Privacy & security > Microphone: allow desktop apps.\n"
            "  2. Sound settings > Input: unmute and raise the level to ~80.\n"
            "  3. Try another device: --list-devices, then set\n"
            "     [audio].input_device in config.toml."
        )
        return 1
    if peak < 0.02:
        print(
            "\nWARN  signal is very quiet. Whisper will struggle.\n"
            "  Raise the input level in Windows Sound settings, or move closer."
        )
    else:
        print("\nOK    microphone level looks healthy.")
    return 0


def loop_test(config: Config, seconds: float = 5.0) -> int:
    """Full pipeline check: record, transcribe, print. No text is inserted."""
    from .engines import create as create_transcriber
    from .inserter import Inserter

    print("Loading the model (first run downloads it)...")
    transcriber = create_transcriber(config.model)
    transcriber.warmup(int(config.audio["sample_rate"]))

    recorder = _recorder(config)

    print(f"\nRecording {seconds:.0f}s. Say a sentence, e.g.")
    print('  "Refactor the login handler to validate the token first."\n')
    try:
        recorder.start()
    except Exception as exc:
        print(f"Could not open the microphone: {exc}")
        return 1

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(0.1)
        sys.stdout.write(f"\r  listening... {max(0.0, deadline - time.monotonic()):4.1f}s ")
        sys.stdout.flush()
    audio = recorder.stop()
    print("\n")

    peak = float(np.abs(audio).max()) if audio.size else 0.0
    if peak < 1e-4:
        print("FAIL  silence captured. Run --mic-test for the fix list.")
        return 1

    started = time.perf_counter()
    text = transcriber.transcribe(audio)
    elapsed = time.perf_counter() - started

    print(f"  transcribed in {elapsed:.2f}s on {transcriber.device}")
    if not text:
        print("\nFAIL  nothing recognised. Check the level and [model].language.")
        return 1

    polished = Inserter(config.output).polish(text)
    print(f"\n  raw       {text}")
    print(f"  inserted  {polished!r}")
    print("\nOK    pipeline works. Run the app and try the hotkey in a real text field.")
    return 0
