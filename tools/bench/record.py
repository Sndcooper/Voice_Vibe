"""Record the user's benchmark phrases once (WS6) -- hands-free.

    ..\\venvs\\voicevibe\\Scripts\\python.exe tools\\bench\\record.py [--redo ID ...]

Each phrase is shown; say just those words. Recording starts when you speak
and stops after you pause, then the next phrase appears. Keys (optional):
R = redo the previous phrase, S = skip this one, Q = quit (progress is kept;
run again to continue). Uses Voice Vibe's microphone, never a loopback.
Output: %LOCALAPPDATA%\\VoiceVibe\\bench\\user\\<id>.wav + manifest.jsonl.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import queue
import sys
import time

import numpy as np
import sounddevice as sd

from common import SAMPLE_RATE, bench_dir, load_phrases, read_manifest, write_manifest, write_wav

BLOCK = 480                # 30 ms at 16 kHz
BLOCK_S = BLOCK / SAMPLE_RATE
PRE_ROLL = 1.0             # kept from before the onset, so a soft first word survives
END_SILENCE = 1.5          # a pause this long ends the take (the app's silence_duration)
KEEP_TAIL = END_SILENCE    # keep the whole tail: soft last words sit below the threshold
MAX_WAIT, MAX_TAKE = 15.0, 20.0

try:
    import msvcrt
except ImportError:  # not Windows
    msvcrt = None


def key() -> str:
    if msvcrt is not None and msvcrt.kbhit():
        return msvcrt.getwch().lower()
    return ""


class Mic:
    def __init__(self, device: int | str | None) -> None:
        self.device = device
        self.blocks: queue.Queue[np.ndarray] = queue.Queue()
        self.stream = sd.InputStream(samplerate=SAMPLE_RATE, device=device, channels=1,
                                     dtype="float32", blocksize=BLOCK, callback=self._callback)
        self.stream.start()

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        self.blocks.put(indata[:, 0].copy())

    def drain(self) -> None:
        while not self.blocks.empty():
            self.blocks.get_nowait()

    def read(self, seconds: float) -> list[np.ndarray]:
        out, need = [], int(seconds / BLOCK_S)
        while len(out) < need:
            try:
                out.append(self.blocks.get(timeout=2.0))
            except queue.Empty:
                self.restart()
        return out

    def restart(self) -> None:
        """The driver stopped delivering blocks (device switched or reset)."""
        print("   (microphone stalled - reopening it)")
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
        self.stream = sd.InputStream(samplerate=SAMPLE_RATE, device=self.device, channels=1,
                                     dtype="float32", blocksize=BLOCK, callback=self._callback)
        self.stream.start()

    def close(self) -> None:
        self.stream.stop()
        self.stream.close()


def rms(block: np.ndarray) -> float:
    return float(np.sqrt(np.mean(block ** 2)))


def listen(mic: Mic, floor: float) -> tuple[str, np.ndarray | None]:
    """Wait for speech, record until a pause. ('', audio) or (key|'timeout', None)."""
    threshold = max(0.004, 3.0 * floor)   # 0.012 missed soft first/last words (2026-09-30)
    pre: collections.deque[np.ndarray] = collections.deque(maxlen=int(PRE_ROLL / BLOCK_S))
    take: list[np.ndarray] = []
    run = silent = last_voiced = 0
    waited = 0.0
    while True:
        pressed = key()
        if pressed in ("r", "s", "q"):
            return pressed, None
        try:
            block = mic.blocks.get(timeout=2.0)
        except queue.Empty:
            mic.restart()
            continue
        voiced = rms(block) > threshold
        if not take:
            pre.append(block)
            waited += BLOCK_S
            run = run + 1 if voiced else 0
            if run >= 3:                       # 90 ms of voice = an onset
                take = list(pre)
                last_voiced = len(take)
            elif waited > MAX_WAIT:
                return "timeout", None
            continue
        take.append(block)
        if voiced:
            silent, last_voiced = 0, len(take)
        else:
            silent += 1
        if silent * BLOCK_S >= END_SILENCE or len(take) * BLOCK_S >= MAX_TAKE:
            break
    keep = min(len(take), last_voiced + int(KEEP_TAIL / BLOCK_S))
    return "", np.concatenate(take[:keep])


def pick_device(explicit: str | None) -> tuple[int | str | None, str]:
    from voicevibe import audio
    from voicevibe.config import load_config

    if explicit is not None:
        device: int | str | None = int(explicit) if explicit.isdigit() else explicit
    else:
        device = load_config().input_device
    label = audio.device_label(device) if isinstance(device, int) else str(device)
    if device is None or audio.is_loopback(label):
        sys.exit(f"Refusing to record from {label!r}: not a real microphone. Pass --device N "
                 "(see run.bat --list-devices).")
    return device, label


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--device", help="input device index or name (default: Voice Vibe's choice)")
    parser.add_argument("--redo", nargs="*", default=[], help="phrase ids to record again")
    args = parser.parse_args()

    out = bench_dir() / "user"
    manifest = out / "manifest.jsonl"
    phrases = load_phrases()
    rows = [r for r in read_manifest(manifest) if r["id"] not in set(args.redo)]
    device, label = pick_device(args.device)
    print("=" * 70)
    print(" Voice Vibe benchmark recorder  (hands-free)")
    print(f" Microphone: {label}")
    print(" For each phrase: wait for SPEAK NOW, say ONLY the words in quotes,")
    print(" then pause. It saves and moves on by itself. No keys needed.")
    print(" Optional keys: R = redo previous, S = skip, Q = quit (resume later).")
    print(" Keep Voice Vibe unarmed (no Ctrl+Alt+W): these are real commands.")
    print("=" * 70)

    mic = Mic(device)
    queue_ = [p for p in phrases if p["id"] not in {r["id"] for r in rows}]
    total, previous = len(phrases), None
    try:
        while queue_:
            phrase, kind = queue_[0], queue_[0]["kind"]
            print(f"\n[{total - len(queue_) + 1}/{total}]  ({kind})")
            mic.drain()
            time.sleep(0.8)                  # let the user read before measuring the room
            mic.drain()
            floor = float(np.median([rms(b) for b in mic.read(0.6)]))
            if kind in ("silence", "noise"):
                seconds = float(phrase.get("seconds", 5))
                print(f"   {phrase.get('prompt', 'STAY QUIET, do not speak').upper()}  for {seconds:.0f} s ...")
                audio, pressed = np.concatenate(mic.read(seconds)), ""
            else:
                print(f'   Say:   "{phrase["text"]}"')
                print("   >>> SPEAK NOW")
                pressed, audio = listen(mic, floor)
            if pressed == "q":
                break
            if pressed == "s":
                queue_.pop(0)
                continue
            if pressed == "r" and previous is not None:
                rows = [r for r in rows if r["id"] != previous["id"]]
                queue_.insert(0, previous)
                previous = None
                continue
            if pressed == "timeout":
                print("   (heard nothing - showing it again)")
                continue
            if audio is None:
                continue
            peak = float(np.max(np.abs(audio))) if audio.size else 0.0
            write_wav(out / f"{phrase['id']}.wav", audio)
            rows = [r for r in rows if r["id"] != phrase["id"]]
            rows.append({"id": phrase["id"], "kind": kind, "text": phrase["text"],
                         "wav": f"{phrase['id']}.wav", "seconds": round(audio.size / SAMPLE_RATE, 2),
                         "peak": round(peak, 4), "rms": round(rms(audio), 5), "floor": round(floor, 5),
                         "device": label, "recorded": datetime.datetime.now().isoformat(timespec="seconds")})
            write_manifest(manifest, rows)
            print(f"   saved {audio.size / SAMPLE_RATE:.1f} s")
            previous = queue_.pop(0)
    except KeyboardInterrupt:
        pass
    finally:
        mic.close()
    print(f"\n{len(rows)}/{total} recorded in {out}")
    input("Press Enter to close. ")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 - keep the window open and leave a log
        import traceback

        text = traceback.format_exc()
        log = bench_dir() / "user" / "record.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(f"{datetime.datetime.now().isoformat()}\n{text}\n")
        print(text)
        input(f"Crashed (logged to {log}). Press Enter to close. ")
        sys.exit(1)
