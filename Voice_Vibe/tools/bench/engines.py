"""Speech engines under test (WS6). Each spec builds a `transcribe(audio) -> str`
for 16 kHz mono float32 audio. Runs inside bench.py's child process.

  fw:<model>:<device>:<compute>[:raw][:beam1]   faster-whisper through the app's own
        Transcriber and config.toml [model] + [vocab].hotwords ("raw" = code defaults)
  parakeet | canary180                          NeMo models via onnx-asr (int8)
  moonshine:<tiny|small|medium>                 Moonshine v2 streaming models
  wcpp:<ggml name>                              whisper.cpp via pywhispercpp (CPU)
  vosk | vosk-grammar                           Vosk small-en (free / command grammar)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[3]           # ...\voicevibe
APP_SRC = ROOT / "Voice_Vibe" / "src"
MODELS = ROOT / "venvs" / "models"
HF_HOME = Path(os.environ.get("HF_HOME") or ROOT / "venvs" / "hf-cache")

Transcribe = Callable[[np.ndarray], str]


def app_config():  # noqa: ANN201
    sys.path.insert(0, str(APP_SRC))
    from voicevibe.config import load_config

    return load_config(ROOT / "Voice_Vibe" / "config.toml")


def hotword_list() -> list[str]:
    return list(app_config().vocab.get("hotwords", []) or [])


def build(spec: str, threads: int) -> Transcribe:
    kind, _, rest = spec.partition(":")
    return {"fw": _faster_whisper, "parakeet": _onnx_asr, "app": _app_engine,
            "moonshine": _moonshine, "wcpp": _whisper_cpp, "vosk": _vosk,
            "vosk-grammar": _vosk}[kind](kind, rest, threads)


def _app_engine(kind: str, rest: str, threads: int) -> Transcribe:
    """app:<engine> -- the shipped voicevibe.engines code path, config.toml settings."""
    config = app_config()
    from voicevibe.engines import create

    engine = create({**config.model, "engine": rest, "device": "cpu", "cpu_threads": threads})
    engine.warmup()
    return lambda audio: engine.transcribe(audio) or ""


def _faster_whisper(kind: str, rest: str, threads: int) -> Transcribe:
    parts = rest.split(":")
    model, device, compute = parts[0], parts[1], parts[2]
    flags = set(parts[3:])
    config = app_config()
    sys.path.insert(0, str(APP_SRC))
    from voicevibe.transcriber import Transcriber
    from voicevibe.vocab import Vocabulary

    cfg = {"language": "en", "beam_size": 3} if "raw" in flags else dict(config.model)
    cfg.update(name=model, device=device, compute_type=compute, cpu_threads=threads)
    if "beam1" in flags:
        cfg["beam_size"] = 1
    engine = Transcriber(cfg)
    if "raw" not in flags:
        engine.hotwords = Vocabulary(config.vocab).hotwords_text()
    engine.warmup()
    return lambda audio: engine.transcribe(audio) or ""


def _ort_options(threads: int):  # noqa: ANN202
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    return so


def _onnx_asr(kind: str, rest: str, threads: int) -> Transcribe:
    import onnx_asr

    name = "nemo-parakeet-tdt-0.6b-v2"
    model = onnx_asr.load_model(name, quantization="int8", sess_options=_ort_options(threads),
                                providers=["CPUExecutionProvider"])
    return lambda audio: str(model.recognize(audio, sample_rate=16000))


def _moonshine(kind: str, rest: str, threads: int) -> Transcribe:
    from moonshine_voice import ModelArch, Transcriber, get_model_for_language

    arch = {"tiny": ModelArch.TINY_STREAMING, "small": ModelArch.SMALL_STREAMING,
            "medium": ModelArch.MEDIUM_STREAMING}[rest or "small"]
    path, arch = get_model_for_language("en", arch, cache_root=MODELS / "moonshine")
    engine = Transcriber(model_path=path, model_arch=arch)
    if "keyterms" in os.environ.get("BENCH_FLAGS", ""):
        engine.set_keyterms(hotword_list())

    def transcribe(audio: np.ndarray) -> str:
        transcript = engine.transcribe_without_streaming(audio.tolist(), 16000)
        return " ".join(line.text.strip() for line in transcript.lines if line.text.strip())

    return transcribe


def _whisper_cpp(kind: str, rest: str, threads: int) -> Transcribe:
    from huggingface_hub import hf_hub_download
    from pywhispercpp.model import Model

    path = hf_hub_download("ggerganov/whisper.cpp", f"ggml-{rest}.bin", local_files_only=True)
    model = Model(path, n_threads=threads, print_realtime=False, print_progress=False,
                  language="en", no_context=True, single_segment=False)
    return lambda audio: " ".join(s.text.strip() for s in model.transcribe(audio)).strip()


def _vosk(kind: str, rest: str, threads: int) -> Transcribe:
    from vosk import KaldiRecognizer, Model, SetLogLevel

    SetLogLevel(-1)
    model = Model(str(MODELS / "vosk" / "vosk-model-small-en-us-0.15"))
    grammar = None
    if kind == "vosk-grammar":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from common import load_phrases
        from metrics import normalize

        phrases = [normalize(p["text"]) for p in load_phrases() if p["kind"] in ("wake", "command")]
        grammar = json.dumps(sorted(set(phrases)) + ["[unk]"])

    def transcribe(audio: np.ndarray) -> str:
        rec = KaldiRecognizer(model, 16000, grammar) if grammar else KaldiRecognizer(model, 16000)
        pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
        rec.AcceptWaveform(pcm)
        text = json.loads(rec.FinalResult()).get("text", "")
        return "" if text == "[unk]" else text.replace("[unk]", "").strip()

    return transcribe
