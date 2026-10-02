"""Print every engine's hypothesis for chosen user clips (WS6 debugging).
    python tools\\bench\\show.py w01 w02 c11
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import bench_dir  # noqa: E402


def main() -> int:
    wanted = set(sys.argv[1:])
    for path in sorted((bench_dir() / "results").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data["results"]:
            if row["set"] == "user" and row["id"] in wanted:
                print(f"{row['id']:4} {path.stem[:44]:44} [{row['hyp']}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
