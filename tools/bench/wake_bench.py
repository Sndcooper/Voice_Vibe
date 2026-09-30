"""Wake-word comparison (WS6): recall on "hey/ok computer" clips, false
accepts on everything else, and CPU cost per second of audio.

  whisper  today's check: base.en int8 decode biased with the wake phrases,
           then the app's PhraseMatcher (fuzzy 0.82) -- one decode per utterance
  oww      openWakeWord 0.6.0 + the community computer_v2.onnx (fires on
           "computer" too), threshold 0.5
  kws      sherpa-onnx 1.13.8 keyword spotter, zipformer-gigaspeech-3.3M int8,
           open vocabulary "HEY COMPUTER" / "OK COMPUTER" / "OKAY COMPUTER"

    ..\\venvs\\bench\\Scripts\\python.exe tools\\bench\\wake_bench.py [--threads 1]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from bench import clips  # noqa: E402
from common import bench_dir, read_wav  # noqa: E402
from engines import APP_SRC, MODELS, app_config  # noqa: E402
from metrics import normalize  # noqa: E402

KWS_DIR = MODELS / "sherpa-kws" / "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"
OWW_MODEL = MODELS / "oww-computer" / "computer_v2.onnx"
KEYWORDS = ["HEY COMPUTER", "OK COMPUTER", "OKAY COMPUTER"]


def is_wake(text: str) -> bool:
    return normalize(text).startswith(("hey computer", "ok computer"))


def whisper_detector(threads: int):  # noqa: ANN201
    config = app_config()
    sys.path.insert(0, str(APP_SRC))
    from voicevibe.transcriber import Transcriber
    from voicevibe.vocab import Vocabulary
    from voicevibe.wake import PhraseMatcher

    phrases = list(config.wake.get("phrases", []))
    engine = Transcriber({**config.model, "name": "base.en", "device": "cpu", "compute_type": "int8",
                          "cpu_threads": threads, "beam_size": 1})
    engine.hotwords = Vocabulary(config.vocab).hotwords_text()
    engine.initial_prompt = ". ".join(dict.fromkeys(phrases))
    engine.warmup()
    matcher = PhraseMatcher(phrases, fuzzy=float(config.wake.get("fuzzy", 0.82)))
    return lambda audio: matcher.find(engine.transcribe(audio) or "") is not None


def oww_detector(threads: int):  # noqa: ANN201
    from openwakeword import utils
    from openwakeword.model import Model

    utils.download_models(["alexa"])          # fetches the shared feature models once
    model = Model(wakeword_models=[str(OWW_MODEL)], inference_framework="onnx")

    def detect(audio: np.ndarray) -> bool:
        model.reset()
        pcm = (np.clip(np.concatenate([audio, np.zeros(8000, np.float32)]), -1, 1) * 32767).astype(np.int16)
        best = 0.0
        for i in range(0, pcm.size - 1279, 1280):
            best = max(best, max(model.predict(pcm[i:i + 1280]).values()))
        return best >= 0.5

    return detect


def kws_detector(threads: int):  # noqa: ANN201
    import sherpa_onnx

    tokens = sherpa_onnx.text2token(KEYWORDS, tokens=str(KWS_DIR / "tokens.txt"), tokens_type="bpe",
                                    bpe_model=str(KWS_DIR / "bpe.model"))
    handle = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    with handle:
        for words, toks in zip(KEYWORDS, tokens):
            handle.write(" ".join(toks) + " @" + words.replace(" ", "_") + "\n")
    stem = "epoch-12-avg-2-chunk-16-left-64.int8.onnx"
    spotter = sherpa_onnx.KeywordSpotter(
        tokens=str(KWS_DIR / "tokens.txt"), encoder=str(KWS_DIR / f"encoder-{stem}"),
        decoder=str(KWS_DIR / f"decoder-{stem}"), joiner=str(KWS_DIR / f"joiner-{stem}"),
        num_threads=threads, keywords_file=handle.name, provider="cpu")

    def detect(audio: np.ndarray) -> bool:
        stream = spotter.create_stream()
        stream.accept_waveform(16000, np.concatenate([audio, np.zeros(8000, np.float32)]))
        stream.input_finished()
        while spotter.is_ready(stream):
            spotter.decode_stream(stream)
            if spotter.get_result(stream):
                return True
        return False

    return detect


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threads", type=int, default=1)
    args = parser.parse_args()
    data = [(c, read_wav(Path(c["path"]))[0]) for c in clips()]
    rows = []
    for name, factory in (("kws", kws_detector), ("oww", oww_detector), ("whisper", whisper_detector)):
        detect = factory(args.threads)
        stats = {"tp": 0, "pos": 0, "fa_computer": 0, "n_computer": 0, "fa_speech": 0, "n_speech": 0,
                 "fa_quiet": 0, "n_quiet": 0, "neg_seconds": 0.0, "cpu_s": 0.0, "audio_s": 0.0}
        for clip, audio in data:
            started = time.process_time()
            fired = detect(audio)
            stats["cpu_s"] += time.process_time() - started
            stats["audio_s"] += audio.size / 16000
            if is_wake(clip["text"]):
                stats["pos"] += 1
                stats["tp"] += fired
                continue
            stats["neg_seconds"] += audio.size / 16000
            bucket = ("computer" if normalize(clip["text"]).startswith("computer")
                      else "quiet" if clip["kind"] in ("silence", "noise") else "speech")
            stats[f"n_{bucket}"] += 1
            stats[f"fa_{bucket}"] += fired
        stats["detector"] = name
        rows.append(stats)
        print(json.dumps(stats), flush=True)
    out = bench_dir() / "results-wake.json"
    out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print("| Detector | Recall | FA on 'computer …' | FA other speech | FA silence/noise | FA per hour | CPU ms per s audio |")
    print("|---|---|---|---|---|---|---|")
    for s in rows:
        fa = s["fa_computer"] + s["fa_speech"] + s["fa_quiet"]
        print(f"| {s['detector']} | {s['tp']}/{s['pos']} | {s['fa_computer']}/{s['n_computer']} | "
              f"{s['fa_speech']}/{s['n_speech']} | {s['fa_quiet']}/{s['n_quiet']} | "
              f"{fa / (s['neg_seconds'] / 3600):.0f} | {1000 * s['cpu_s'] / s['audio_s']:.1f} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
