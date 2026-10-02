"""Command line: argument parsing, logging setup, diagnostics, and dispatch."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from . import __version__
from .config import Config, load_config

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voicevibe",
        description="Local-first voice dictation with global hotkeys and wake-word sessions.",
    )
    parser.add_argument("-c", "--config", metavar="PATH", help="load a different TOML file")
    parser.add_argument("--model", metavar="NAME", help="override the Whisper model")
    parser.add_argument(
        "--device", choices=("auto", "cuda", "cpu"), help="override inference device"
    )
    parser.add_argument(
        "--language", metavar="CODE", help="override language; use 'auto' to detect"
    )
    parser.add_argument(
        "--mode", choices=("paste", "type"), help="override the insertion method"
    )

    parser.add_argument("--list-devices", action="store_true", help="list microphone inputs")
    parser.add_argument(
        "--check", action="store_true", help="check Python, CUDA, microphone, and clipboard"
    )
    parser.add_argument("--mic-test", action="store_true", help="record with a live level meter")
    parser.add_argument(
        "--test", action="store_true", help="record and transcribe without inserting"
    )
    parser.add_argument(
        "--seconds", type=float, default=None, help="duration for test modes"
    )
    parser.add_argument(
        "--wake-test", action="store_true", help="measure wake phrase recognition"
    )
    parser.add_argument(
        "--wake", metavar="PHRASE", help="override wake phrases; comma-separated accepted"
    )
    parser.add_argument("--rounds", type=int, default=5, help="attempts during --wake-test")
    parser.add_argument("--say", metavar="TEXT", help="synthesize text through Soprano and exit")
    parser.add_argument(
        "--key-test",
        action="store_true",
        help="show the hotkey name of each key you press, to find usable bindings",
    )
    parser.add_argument(
        "--suggest-replacements",
        action="store_true",
        help="propose [[replacements]] from corrections in your history (writes nothing)",
    )
    parser.add_argument(
        "--min-count", type=float, default=2,
        help="how often a correction must recur for --suggest-replacements",
    )

    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    parser.add_argument("--version", action="version", version=f"voicevibe {__version__}")
    return parser


def enable_dpi_awareness() -> None:
    """Opt out of Windows DPI virtualisation before any window exists.

    An unaware process is lied to on scaled displays: window rects and screen
    metrics come back in 96-DPI units, and its own windows are bitmap-stretched
    and blurry. Per-monitor awareness makes every coordinate a physical pixel.
    Setting it fails harmlessly if a manifest or host already chose a mode.
    """
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        return
    except (AttributeError, OSError):
        pass
    # shcore is Windows 8.1+; this older call gives system-wide awareness.
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = []

    # Under pythonw.exe there is no console and sys.stdout is None, so a
    # StreamHandler would raise on the first record.
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)

    # Running in the background means the console is not the record of what
    # happened; the file is.
    from .history import attach_file_log

    path = attach_file_log(verbose)
    if path and sys.stdout is not None:
        print(f"  log      {path}")


def apply_overrides(config: Config, args: argparse.Namespace) -> None:
    if args.model:
        config.model["name"] = args.model
    if args.device:
        config.model["device"] = args.device
    if args.language:
        config.model["language"] = args.language
    if args.mode:
        config.output["mode"] = args.mode
    if args.wake:
        phrases = [p.strip() for p in args.wake.split(",") if p.strip()]
        if phrases:
            config.wake["phrases"] = phrases
            config.wake["enabled"] = True


def check(config: Config) -> int:
    """Report the environment. Every line here maps to a known failure mode."""
    from .cuda_setup import register_cuda_dlls

    ok = True
    print(f"\n  voicevibe   {__version__}")
    print(f"  python      {sys.version.split()[0]} ({sys.platform})")
    print(f"  config      {config.path or 'defaults (no config.toml found)'}")

    registered = register_cuda_dlls()
    print(f"\n  cuda dlls   {len(registered)} director{'y' if len(registered) == 1 else 'ies'}")
    for path in registered:
        print(f"              {path}")

    # No GPU is the expected case on the low-spec laptops this targets, so it
    # reports as a supported mode rather than a failure.
    try:
        import ctranslate2

        count = ctranslate2.get_cuda_device_count()
        version = getattr(ctranslate2, "__version__", "unknown")
        print(f"  ctranslate2 {version}")
        if count:
            # A CUDA device being visible is not the same as GPU inference
            # working: ctranslate2 loads a model onto the GPU happily and only
            # fails on the first compute when cuBLAS/cuDNN are missing.
            try:
                import numpy as np
                from faster_whisper import WhisperModel

                probe = WhisperModel("tiny.en", device="cuda", compute_type="float16")
                segments, _ = probe.transcribe(
                    np.zeros(16000, dtype=np.float32), vad_filter=False
                )
                list(segments)
                print(f"  cuda        {count} device(s) -- GPU inference works")
            except Exception as exc:
                ok = False
                print(f"  cuda        {count} device(s) visible, but inference FAILED")
                print(f"              {str(exc)[:70]}")
                print('              Fix with:  uv pip install -e ".[cuda]"')
        else:
            print("  cuda        none -- CPU mode (supported)")
    except Exception as exc:
        ok = False
        print(f"  ctranslate2 import failed: {exc}")

    from .transcriber import memory_gb, recommend_tier

    print(f"\n  cpu cores   {os.cpu_count() or '?'}")
    total, free = memory_gb()
    if total:
        print(f"  ram         {total:.1f} GB total, {free:.1f} GB free")
    tier = recommend_tier()
    print(f'  suggested   model "{tier.model}" / {tier.compute}  ({tier.note})')
    configured = str(config.model.get("name", "auto"))
    if configured != "auto" and configured != tier.model:
        print(f'              config pins "{configured}"; set it to "auto" to follow this')

    try:
        import sounddevice as sd

        from .audio import is_loopback

        system_default = sd.default.device[0]
        chosen = config.input_device
        index = chosen if isinstance(chosen, int) else system_default
        name = sd.query_devices(index)["name"] if index is not None else "none"
        print(f"\n  microphone  [{index}] {name}")

        if index is not None and is_loopback(name):
            ok = False
            print(
                "\n  FAIL  that is a loopback device: it records what the speakers\n"
                "        play, not what you say, so every recording is silent.\n"
                "        Run --list-devices and set [audio].input_device to a\n"
                "        real microphone's number."
            )
        elif system_default is not None and index != system_default:
            other = sd.query_devices(system_default)["name"]
            print(f"              Windows default [{system_default}] {other}")
            print("              is a loopback, so a real microphone was chosen instead.")
    except Exception as exc:
        ok = False
        print(f"\n  microphone  unavailable: {exc}")

    try:
        import pyperclip

        pyperclip.paste()
        print("  clipboard   ok")
    except Exception as exc:
        ok = False
        print(f"  clipboard   unavailable: {exc}")

    print("\n  OK    environment looks usable.\n" if ok else "\n  Some checks failed.\n")
    return 0 if ok else 1


def key_test(seconds: float = 20.0) -> int:
    """Print what each key press looks like to the hotkey listener.

    Laptops often send media actions from the top row unless Fn is held, and
    which keys are affected varies by manufacturer. This shows exactly what a
    given key produces, so a binding can be chosen that actually arrives.
    """
    import threading

    from pynput import keyboard

    from .hotkey import normalize_key

    held: list[str] = []
    done = threading.Event()

    def on_press(key) -> None:  # noqa: ANN001
        token = normalize_key(key)
        if token is None:
            print("  (a key the listener cannot name -- not usable as a hotkey)")
            return
        if token not in held:
            held.append(token)
        print(f"  {'+'.join(held):<32} -> {token}")
        if token == "esc" and len(held) == 1:
            done.set()

    def on_release(key) -> None:  # noqa: ANN001
        token = normalize_key(key)
        if token in held:
            held.remove(token)

    print("\nPress keys or combinations; each line shows the name to put in")
    print(f"[hotkeys] in config.toml. Esc or {seconds:.0f}s to stop.\n")
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    done.wait(seconds)
    listener.stop()
    print()
    return 0


def say(config: Config, text: str) -> int:
    from .speaker import Speaker, SpeechUnavailable

    try:
        Speaker(config.speech).speak(text)
    except SpeechUnavailable as exc:
        print(f"{exc}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    enable_dpi_awareness()
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)

    config = load_config(args.config)
    apply_overrides(config, args)

    if args.list_devices:
        from .audio import describe_devices

        print(describe_devices())
        return 0
    if args.check:
        return check(config)
    if args.mic_test:
        from .selftest import mic_test

        return mic_test(config, args.seconds or 5.0)
    if args.test:
        from .selftest import loop_test

        return loop_test(config, args.seconds or 5.0)
    if args.wake_test:
        from .selftest import wake_test

        return wake_test(config, args.rounds, min(args.seconds or 2.5, 2.5))
    if args.say:
        return say(config, args.say)
    if args.key_test:
        return key_test(args.seconds or 20.0)
    if args.suggest_replacements:
        from .history import data_dir
        from .suggest import report

        print(report(data_dir() / "history", config.replacements, args.min_count))
        return 0

    from .app import VoiceVibe

    try:
        return VoiceVibe(config).run()
    except KeyboardInterrupt:
        return 0
    except Exception:
        # Under pythonw there is no console and no stderr, so an uncaught
        # exception would otherwise kill the app leaving no trace anywhere.
        log.exception("Voice Vibe stopped because of an unhandled error")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
