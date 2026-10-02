"""Speech benchmark runner (WS6): WER, command accuracy, phantoms, loops,
latency and RAM per engine, on the user's recordings and synthetic audio.

    python tools\\bench\\bench.py all [--only TEXT] [--force]   run the plan (children)
    python tools\\bench\\bench.py report                         markdown table
    python tools\\bench\\bench.py run --engine SPEC --threads N --out FILE   one engine

Each engine runs in its own child process (fresh RAM numbers; a crash or CUDA
out-of-memory only loses that row). GPU faster-whisper rows use the app's venv
(it has the CUDA DLLs); everything else uses venvs\\bench. CPU rows are held to
4 threads and see no GPU, like the ~â‚¹70k target laptop.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import bench_dir, read_manifest, read_wav  # noqa: E402
import metrics  # noqa: E402

ROOT = HERE.parents[2]
APP_PY = ROOT / "venvs" / "voicevibe" / "Scripts" / "python.exe"
BENCH_PY = ROOT / "venvs" / "bench" / "Scripts" / "python.exe"
CPU_THREADS = 4
COMMAND_ONLY = ("wake", "command", "silence", "noise")

PLAN = [  # (label, spec, python, threads, profile)
    ("turbo, app settings (today's GPU default)", "fw:large-v3-turbo:cuda:float16", APP_PY, 0, "GPU"),
    ("turbo, raw decode", "fw:large-v3-turbo:cuda:float16:raw", APP_PY, 0, "GPU"),
    ("distil-large-v3.5, app settings", "fw:distil-whisper/distil-large-v3.5-ct2:cuda:float16", APP_PY, 0, "GPU"),
    ("base.en beam 1 (today's GPU command model)", "fw:base.en:cuda:float16:beam1", APP_PY, 0, "GPU"),
    ("base.en int8 (today's 4-core tier)", "fw:base.en:cpu:int8", BENCH_PY, CPU_THREADS, "CPU"),
    ("small.en int8 (today's 8-core tier)", "fw:small.en:cpu:int8", BENCH_PY, CPU_THREADS, "CPU"),
    ("distil-large-v3.5 int8", "fw:distil-whisper/distil-large-v3.5-ct2:cpu:int8", BENCH_PY, CPU_THREADS, "CPU"),
    ("Parakeet TDT 0.6B v2 int8 (onnx-asr)", "parakeet", BENCH_PY, CPU_THREADS, "CPU"),
    ("Parakeet via app engine (Silero VAD gate)", "app:parakeet", BENCH_PY, CPU_THREADS, "CPU"),
    ("Moonshine v2 small", "moonshine:small", BENCH_PY, CPU_THREADS, "CPU"),
    ("Moonshine v2 medium", "moonshine:medium", BENCH_PY, CPU_THREADS, "CPU"),
    ("whisper.cpp small.en q5_1", "wcpp:small.en-q5_1", BENCH_PY, CPU_THREADS, "CPU"),
    ("whisper.cpp base.en q5_1", "wcpp:base.en-q5_1", BENCH_PY, CPU_THREADS, "CPU"),
    ("Vosk small-en", "vosk", BENCH_PY, CPU_THREADS, "CPU"),
    ("Vosk small-en, command grammar", "vosk-grammar", BENCH_PY, CPU_THREADS, "CPU"),
]


def clips() -> list[dict]:
    """Every clip with its set: 'user' (real voice) and the synthetic sets."""
    rows = []
    user = bench_dir() / "user"
    for row in read_manifest(user / "manifest.jsonl"):
        rows.append({**row, "set": "user", "path": str(user / row["wav"])})
    synth = bench_dir() / "synth"
    for row in read_manifest(synth / "manifest.jsonl"):
        rows.append({**row, "path": str(synth / row["wav"])})
    return rows


def rss_mb() -> tuple[float, float]:
    import psutil

    info = psutil.Process().memory_info()
    peak = getattr(info, "peak_wset", info.rss)
    return info.rss / 2**20, peak / 2**20


def run_one(spec: str, threads: int, out: Path) -> None:
    from engines import build

    todo = clips()
    if spec == "vosk-grammar":
        todo = [c for c in todo if c["kind"] in COMMAND_ONLY]
    started = time.perf_counter()
    transcribe = build(spec, threads)
    load_s = time.perf_counter() - started
    rss_load, _ = rss_mb()
    results = []
    for clip in todo:
        audio, rate = read_wav(Path(clip["path"]))
        if rate != 16000:
            raise ValueError(f"{clip['path']}: {rate} Hz")
        t0 = time.perf_counter()
        hyp = transcribe(audio)
        results.append({"set": clip["set"], "id": clip["id"], "kind": clip["kind"], "text": clip["text"],
                        "hyp": hyp, "seconds": round(audio.size / 16000, 3),
                        "decode_s": round(time.perf_counter() - t0, 4)})
    rss_end, peak = rss_mb()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"spec": spec, "threads": threads, "load_s": round(load_s, 2),
                               "rss_load_mb": round(rss_load), "rss_end_mb": round(rss_end),
                               "peak_mb": round(peak), "results": results}, indent=1), encoding="utf-8")


def slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:60]


def run_all(only: str | None, force: bool, timeout: float) -> None:
    results = bench_dir() / "results"
    for label, spec, python, threads, profile in PLAN:
        if only and only.lower() not in label.lower() and only.lower() not in spec.lower():
            continue
        out = results / f"{profile.lower()}-{slug(label)}.json"
        if out.exists() and not force:
            print(f"skip (done) {profile} {label}", flush=True)
            continue
        env = dict(os.environ, PYTHONUTF8="1", HF_HOME=str(ROOT / "venvs" / "hf-cache"),
                   HF_HUB_OFFLINE="1", OMP_NUM_THREADS=str(threads or ""))
        if profile == "CPU":
            env["CUDA_VISIBLE_DEVICES"] = "-1"
        started = time.perf_counter()
        try:
            done = subprocess.run([str(python), str(HERE / "bench.py"), "run", "--engine", spec,
                                   "--threads", str(threads), "--out", str(out)],
                                  capture_output=True, text=True, timeout=timeout, env=env,
                                  encoding="utf-8", errors="replace")
            status = "ok" if done.returncode == 0 else f"exit {done.returncode}: {done.stderr.strip()[-300:]}"
        except subprocess.TimeoutExpired:
            status = f"TIMEOUT after {timeout:.0f}s"
        if out.exists():
            data = json.loads(out.read_text(encoding="utf-8"))
            data.update(label=label, profile=profile)
            out.write_text(json.dumps(data, indent=1), encoding="utf-8")
        print(f"{status:<8.300} {profile} {label}  ({time.perf_counter() - started:.0f}s)", flush=True)


def fmt(value: float | None, pattern: str = "{:.1%}") -> str:
    return "â€”" if value is None else pattern.format(value)


def bad_takes(runs: list[dict], limit: float = 0.5) -> set[str]:
    """User clips no engine gets half right: failed takes, left out for everyone."""
    best: dict[str, float] = {}
    for data in runs:
        for r in data["results"]:
            if r["set"] == "user" and r["kind"] in metrics.SPEECH_KINDS:
                e, n = metrics.edits(r["text"], r["hyp"])
                best[r["id"]] = min(best.get(r["id"], 9.0), e / max(1, n))
    return {clip for clip, score in best.items() if score > limit}


def report(exclude: set[str] | None = None) -> str:
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((bench_dir() / "results").glob("*.json"))]
    exclude = set(exclude or set()) | bad_takes(runs)
    lines = [f"Left out (failed takes: no engine got half the words): {', '.join(sorted(exclude)) or 'none'}", "",
             "| Profile | Engine | Load s | Peak RAM MB | WER user | WER synth | WER noisy | "
             "Cmd acc user | Cmd acc synth | Phantoms | Loops | Latency mean / p90 s | RTF |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for data in runs:
        rows = [r for r in data["results"] if not (r["set"] == "user" and r["id"] in (exclude or set()))]
        user = metrics.summarize([r for r in rows if r["set"] == "user"])
        synth = metrics.summarize([r for r in rows if r["set"] in ("sapi-david", "sapi-zira")])
        noisy = metrics.summarize([r for r in rows if r["set"].endswith("noisy15")])
        allrows = metrics.summarize(rows)
        lat = f"{fmt(allrows['lat_mean'], '{:.2f}')} / {fmt(allrows['lat_p90'], '{:.2f}')}"
        lines.append(" | ".join([
            f"| {data.get('profile', '?')}", data.get("label", data["spec"]), f"{data['load_s']:.1f}",
            str(data["peak_mb"]), fmt(user["wer"]), fmt(synth["wer"]), fmt(noisy["wer"]),
            fmt(user["cmd_acc"]), fmt(synth["cmd_acc"]),
            f"{sum(bool(metrics.normalize(r['hyp'])) for r in rows if r['kind'] in ('silence', 'noise'))}"
            f"/{allrows['n_quiet']}", str(allrows["loops"]), lat, fmt(allrows["rtf"], "{:.3f}")]) + " |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    one = sub.add_parser("run")
    one.add_argument("--engine", required=True)
    one.add_argument("--threads", type=int, default=CPU_THREADS)
    one.add_argument("--out", required=True)
    plan = sub.add_parser("all")
    plan.add_argument("--only")
    plan.add_argument("--force", action="store_true")
    plan.add_argument("--timeout", type=float, default=2400)
    rep = sub.add_parser("report")
    rep.add_argument("--exclude", default="", help="user clip ids to leave out, comma-separated")
    args = parser.parse_args()
    if args.cmd == "run":
        run_one(args.engine, args.threads, Path(args.out))
    elif args.cmd == "all":
        run_all(args.only, args.force, args.timeout)
    else:
        print(report({x for x in args.exclude.replace(" ", ",").split(",") if x}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
