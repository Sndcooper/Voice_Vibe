"""python -m vvhub {serve,doctor,token,purge,report,eval}"""

from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import HOST, PORT, __version__, data_dir

log = logging.getLogger("vvhub")


def attach_file_log(verbose: bool = False) -> Path | None:
    """%LOCALAPPDATA%\\VoiceVibe\\logs\\vvhub.log, rotating. None if unwritable."""
    folder = data_dir() / "logs"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    path = folder / "vvhub.log"
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(name)s  %(message)s"))
    handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    logging.getLogger().addHandler(handler)
    return path


def quiet_stdio() -> None:
    """pythonw has no console, so sys.stdout/stderr are None and a library
    printing a progress bar dies with "'NoneType' object has no attribute
    'write'" -- how Laya's GPU load failed on 2026-09-30 18:51, dropping every
    request to the keyword tier. Give them a sink; turn the bars off."""
    import os

    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TQDM_DISABLE", "1")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # These two keep their owners' parsers (WS4 scheduler, WS2 evals).
    if argv[:1] == ["report"]:
        from .scheduler import main as report_main

        return report_main(argv)
    if argv[:1] == ["eval"]:
        from .evals.runner import main as eval_main

        return eval_main(argv[1:])

    parser = argparse.ArgumentParser(prog="vvhub", description="Voice Vibe automation hub")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the hub (127.0.0.1 only)")
    serve.add_argument("--port", type=int, default=PORT)
    serve.add_argument("-v", "--verbose", action="store_true")
    sub.add_parser("doctor", help="check every component")
    sub.add_parser("token", help="print the path of the token file")
    sub.add_parser("purge", help="apply the 2-day retention now")
    sub.add_parser("report", help="report --now [--no-poll] [--html-only]: a report right now")
    sub.add_parser("eval", help="Laya routing eval (see: vvhub eval --help)")
    args = parser.parse_args(argv)

    if args.command == "serve":
        quiet_stdio()
        import uvicorn

        from .server import build_hub, create_app

        level = logging.DEBUG if args.verbose else logging.INFO
        logging.basicConfig(level=level,
                            format="%(asctime)s %(levelname)-7s %(name)s  %(message)s")
        path = attach_file_log(args.verbose)
        sys.excepthook = lambda kind, value, tb: log.critical(
            "Uncaught exception", exc_info=(kind, value, tb))
        app = create_app(build_hub())
        log.info("vvhub %s serving on %s:%d (log: %s)", __version__, HOST, args.port, path)
        try:
            # Never 0.0.0.0: the hub can type and click on this machine (rule 18).
            # log_config=None: uvicorn logs through our handlers (the file log).
            uvicorn.run(app, host=HOST, port=args.port, log_config=None,
                        log_level="info" if args.verbose else "warning")
        finally:
            # Absent from the log after a start line = the process was killed.
            log.info("vvhub stopped")
        return 0
    if args.command == "doctor":
        from .doctor import main as doctor

        return doctor()
    if args.command == "token":
        from .server import load_or_create_token, token_path

        load_or_create_token()
        print(token_path())
        return 0
    if args.command == "purge":
        from .store import Store

        print(Store(data_dir() / "hub.db").purge())
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
