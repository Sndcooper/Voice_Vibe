"""python -m vvhub {serve,doctor,token,purge}"""

from __future__ import annotations

import argparse
import logging
import sys

from . import HOST, PORT, __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vvhub", description="Voice Vibe automation hub")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the hub (127.0.0.1 only)")
    serve.add_argument("--port", type=int, default=PORT)
    serve.add_argument("-v", "--verbose", action="store_true")
    sub.add_parser("doctor", help="check every component")
    sub.add_parser("token", help="print the path of the token file")
    sub.add_parser("purge", help="apply the 2-day retention now")
    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn

        from .server import build_hub, create_app

        logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                            format="%(asctime)s %(levelname)-7s %(name)s  %(message)s")
        app = create_app(build_hub())
        # Never 0.0.0.0: the hub can type and click on this machine (rule 18).
        uvicorn.run(app, host=HOST, port=args.port, log_level="info" if args.verbose else "warning")
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
        from . import data_dir
        from .store import Store

        print(Store(data_dir() / "hub.db").purge())
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
