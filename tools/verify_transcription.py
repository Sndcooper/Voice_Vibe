"""Score existing local voice recordings and ask local Laya about meaning.

Run with the app Python. Results and audio remain on this machine. Laya judges
text pairs only; word error rate measures audio transcription against references.
"""
from __future__ import annotations

import json
import os
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from voicevibe.config import load_config
from voicevibe.engines import create
from voicevibe.vocab import Vocabulary


def edits(reference, actual):
    import re
    def words(text):
        return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.lower().replace("\u2019", "'"))
    ref, hyp = words(reference), words(actual)
    row = list(range(len(hyp) + 1))
    for i, word in enumerate(ref, 1):
        nxt = [i]
        for j, other in enumerate(hyp, 1):
            nxt.append(min(row[j] + 1, nxt[j - 1] + 1, row[j - 1] + (word != other)))
        row = nxt
    return row[-1], len(ref)


def main():
    bench = Path(os.environ["LOCALAPPDATA"]) / "VoiceVibe" / "bench" / "user"
    samples = [json.loads(line) for line in (bench / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    speech = [row for row in samples if row["kind"] == "dictation"]
    speech += [row for row in samples if row["kind"] == "command"][:5]
    config = load_config(ROOT / "config.toml")
    engine = create(config.model)
    vocab = Vocabulary(config.vocab)
    engine.hotwords = vocab.hotwords_text()
    engine.warmup()
    rows = []
    for sample in speech:
        with wave.open(str(bench / sample["wav"]), "rb") as wav:
            assert wav.getframerate() == 16000 and wav.getsampwidth() == 2
            channels = wav.getnchannels()
            audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
            if channels > 1:
                audio = audio.reshape(-1, channels).mean(axis=1)
        engine.initial_prompt = str(config.model.get("initial_prompt") or "") or None
        start = time.perf_counter()
        text = engine.transcribe(audio) or ""
        errors, words = edits(sample["text"], text)
        result = {"id": sample["id"], "reference": sample["text"], "transcript": text,
                  "word_errors": errors, "reference_words": words,
                  "seconds": round(time.perf_counter() - start, 3)}
        rows.append(result)
        print(json.dumps(result), flush=True)
    silence = engine.transcribe(np.zeros(32000, dtype=np.float32)) or ""
    del engine
    import gc
    gc.collect()
    import torch
    torch.set_num_threads(4)
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    from laya import Router
    router = Router(device="cuda" if torch.cuda.is_available() else "cpu", max_loaded=1, default="english")
    question = {"faithfulness": {"type": "choice",
        "instructions": "Compare the reference and transcription. Does the transcription preserve the reference meaning, including names, numbers, actions and negation?",
        "criteria": {"faithful": "Same meaning; punctuation and harmless wording differences are acceptable.",
                     "changed": "Missing words or substitutions change the meaning or requested action."}}}
    checks = []
    selected = rows[:3] + sorted(rows, key=lambda row: row["word_errors"] / max(1, row["reference_words"]), reverse=True)[:3]
    for row in selected:
        state = f'Reference: {row["reference"]}\nTranscription: {row["transcript"]}'
        result = router.predict(state, question, model="english", min_confidence=0.7)
        checks.append({"id": row["id"], "answer": result["answers"]["faithfulness"]})
        print("Laya " + json.dumps(checks[-1]), flush=True)
    for label, reference, actual in [("positive_control", "Please open the document.", "Please open the document."),
                                      ("negative_control", "Please open the document.", "Please delete the document.")]:
        result = router.predict(f"Reference: {reference}\nTranscription: {actual}", question, model="english", min_confidence=0.7)
        checks.append({"id": label, "answer": result["answers"]["faithfulness"]})
        print("Laya " + json.dumps(checks[-1]), flush=True)
    report = {"samples": len(rows), "word_error_rate": sum(r["word_errors"] for r in rows) / max(1, sum(r["reference_words"] for r in rows)),
              "silence_transcript": silence, "transcriptions": rows, "laya": checks,
              "limitation": "Existing local recordings, not a fresh live microphone test. Laya judges text meaning only; its controls must be checked. Laya checkpoint reports uncalibrated temperatures; probabilities are not an accuracy guarantee."}
    out = Path(os.environ["LOCALAPPDATA"]) / "VoiceVibe" / "verification" / "transcriber-laya.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report: {out}\nSamples: {len(rows)}; WER: {report['word_error_rate']:.1%}; silence: {silence!r}", flush=True)


if __name__ == "__main__":
    main()
