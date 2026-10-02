"""voicevibe.engines: engine choice + the Parakeet engine. Fakes only: no
model, no onnxruntime session, no network."""

from __future__ import annotations

import threading
import unittest

import numpy as np

import stubs

stubs.install()

from voicevibe import engines  # noqa: E402
from voicevibe.engines import parakeet  # noqa: E402


class FakeWhisper:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.model_name = "fake-whisper"


class FakeParakeet:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.model_name = "fake-parakeet"


class BrokenParakeet:
    def __init__(self, cfg: dict) -> None:
        raise ImportError("No module named 'onnx_asr'")


class CreateTests(unittest.TestCase):
    def make(self, cfg: dict, par: type = FakeParakeet, cuda: bool = False) -> object:
        return engines.create(cfg, whisper=FakeWhisper, parakeet=par, cuda=lambda: cuda)

    def test_default_is_whisper(self) -> None:
        self.assertIsInstance(self.make({}), FakeWhisper)
        self.assertIsInstance(self.make({"engine": "whisper"}), FakeWhisper)

    def test_parakeet_by_name(self) -> None:
        self.assertIsInstance(self.make({"engine": "Parakeet"}), FakeParakeet)

    def test_missing_parakeet_falls_back_to_whisper(self) -> None:
        with self.assertLogs("voicevibe.engines", "WARNING"):
            self.assertIsInstance(self.make({"engine": "parakeet"}, par=BrokenParakeet), FakeWhisper)

    def test_unknown_engine_is_whisper(self) -> None:
        with self.assertLogs("voicevibe.engines", "WARNING"):
            self.assertIsInstance(self.make({"engine": "banana"}), FakeWhisper)

    def test_auto_uses_whisper_on_gpu_and_parakeet_on_cpu(self) -> None:
        self.assertIsInstance(self.make({"engine": "auto"}, cuda=True), FakeWhisper)
        self.assertIsInstance(self.make({"engine": "auto"}, cuda=False), FakeParakeet)
        self.assertIsInstance(self.make({"engine": "auto", "device": "cpu"}, cuda=True), FakeParakeet)
        # A pinned Whisper model name keeps Whisper even on CPU.
        self.assertIsInstance(self.make({"engine": "auto", "name": "small.en"}, cuda=False), FakeWhisper)

    def test_auto_without_parakeet_is_whisper_silently(self) -> None:
        self.assertIsInstance(self.make({"engine": "auto"}, par=BrokenParakeet), FakeWhisper)


class FakeModel:
    def __init__(self, reply: str = "Computer, run Claude.") -> None:
        self.reply = reply
        self.calls: list[np.ndarray] = []
        self.gate = threading.Event()
        self.gate.set()

    def recognize(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        self.gate.wait(2)
        self.calls.append(audio)
        return self.reply


def speech_at(*spans: tuple[float, float]):  # noqa: ANN201
    """A fake VAD that reports the given (start, end) seconds as speech."""
    def vad(audio: np.ndarray, max_seconds: float) -> list[np.ndarray]:
        return [audio[int(a * 16000):int(b * 16000)] for a, b in spans]
    return vad


class ParakeetTests(unittest.TestCase):
    def engine(self, cfg: dict | None = None, model: FakeModel | None = None, vad=None):  # noqa: ANN001, ANN201
        self.model = model or FakeModel()
        return parakeet.ParakeetTranscriber(cfg or {"vad_filter": True}, loader=lambda name, threads: self.model,
                                            vad=vad or speech_at((0.5, 1.5)))

    def test_interface_matches_the_whisper_transcriber(self) -> None:
        engine = self.engine()
        for name in ("model_name", "device", "compute_type", "hotwords", "initial_prompt", "cfg"):
            self.assertTrue(hasattr(engine, name), name)
        engine.hotwords = "Claude, Codex"      # the app assigns these; they must not break
        engine.initial_prompt = "hint"
        self.assertEqual(engine.device, "cpu")
        self.assertEqual(engine.model_name, parakeet.DEFAULT_MODEL)

    def test_only_speech_reaches_the_model(self) -> None:
        engine = self.engine()
        text = engine.transcribe(np.zeros(3 * 16000, np.float32))
        self.assertEqual(text, "Computer, run Claude.")
        self.assertEqual(len(self.model.calls), 1)
        self.assertEqual(self.model.calls[0].size, 16000)

    def test_silence_never_decodes(self) -> None:
        engine = self.engine(vad=speech_at())
        self.assertEqual(engine.transcribe(np.zeros(8 * 16000, np.float32)), "")
        self.assertEqual(self.model.calls, [])

    def test_empty_audio(self) -> None:
        self.assertEqual(self.engine().transcribe(np.zeros(0, np.float32)), "")

    def test_several_chunks_are_joined(self) -> None:
        engine = self.engine(vad=speech_at((0, 1), (2, 3)), model=FakeModel("part."))
        self.assertEqual(engine.transcribe(np.zeros(4 * 16000, np.float32)), "part. part.")

    def test_without_vad_long_audio_is_split(self) -> None:
        engine = self.engine(cfg={"vad_filter": False})
        engine.transcribe(np.zeros(int(60 * 16000), np.float32))
        self.assertEqual([c.size for c in self.model.calls],
                         [int(parakeet.MAX_CHUNK_S * 16000)] * 2 + [60 * 16000 - 2 * int(parakeet.MAX_CHUNK_S * 16000)])

    def test_busy_model_returns_none_without_waiting(self) -> None:
        engine = self.engine()
        self.model.gate.clear()
        worker = threading.Thread(target=engine.transcribe, args=(np.zeros(32000, np.float32),))
        worker.start()
        try:
            for _ in range(100):
                if engine._lock.locked():
                    break
                threading.Event().wait(0.01)
            self.assertIsNone(engine.transcribe(np.zeros(32000, np.float32), wait=False))
        finally:
            self.model.gate.set()
            worker.join(2)

    def test_warmup_runs_the_model_and_never_raises(self) -> None:
        engine = self.engine()
        engine.warmup()
        self.assertEqual(len(self.model.calls), 1)

        class Boom(FakeModel):
            def recognize(self, audio, sample_rate=16000):  # noqa: ANN001, ANN201
                raise RuntimeError("bad model")

        broken = self.engine(model=Boom())
        with self.assertLogs("voicevibe.engines.parakeet", "WARNING"):
            broken.warmup()

    def test_threads_follow_cpu_threads(self) -> None:
        seen = {}
        parakeet.ParakeetTranscriber({"cpu_threads": 3}, loader=lambda name, threads: seen.update(t=threads),
                                     vad=speech_at())
        self.assertEqual(seen["t"], 3)


class ChunkTests(unittest.TestCase):
    def test_split_long(self) -> None:
        pieces = parakeet.split_long(np.zeros(50 * 16000, np.float32), 20.0)
        self.assertEqual([p.size // 16000 for p in pieces], [20, 20, 10])
        self.assertEqual(parakeet.split_long(np.zeros(0, np.float32), 20.0), [])


if __name__ == "__main__":
    unittest.main()
