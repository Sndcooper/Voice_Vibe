"""Flag user clips that the recorder cut short (WS6 bench hygiene).

A clip is 'cut' when at least two engines that read the full user set agree
the reference is missing words at the start or the end.
    python tools\\bench\\truncation.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import bench_dir  # noqa: E402
from metrics import normalize  # noqa: E402


def missing_edges(ref: str, hyp: str) -> str:
    r, h = normalize(ref).split(), normalize(hyp).split()
    if not h:
        return "all"
    if r[: len(h)] != h[: len(h)] and r[-1] not in h and r[0] in h:
        return "end"
    if r[0] not in h and r[-1] in h:
        return "start"
    if r[-1] not in h and r[0] in h:
        return "end"
    return ""


def main() -> int:
    runs = []
    for path in sorted((bench_dir() / "results").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        user = {r["id"]: r for r in data["results"] if r["set"] == "user"}
        if len(user) >= 40 and "grammar" not in path.name:
            runs.append((path.stem, user))
    votes: dict[str, list[str]] = {}
    for _, user in runs:
        for clip_id, row in user.items():
            if row["kind"] in ("silence", "noise"):
                continue
            edge = missing_edges(row["text"], row["hyp"])
            if edge:
                votes.setdefault(clip_id, []).append(edge)
    cut = {k: v for k, v in votes.items() if len(v) >= max(2, len(runs) // 2)}
    print(f"{len(runs)} full runs; cut clips: {' '.join(sorted(cut))}")
    for clip_id in sorted(cut):
        print(f"  {clip_id}: {', '.join(sorted(set(cut[clip_id])))} ({len(cut[clip_id])}/{len(runs)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
