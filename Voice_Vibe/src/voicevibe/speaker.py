"""Text-to-speech playback via Soprano.

Soprano (https://github.com/ekwek1/soprano, Apache-2.0) is an 80M-parameter TTS
model. It pulls in torch and transformers, so it lives behind the optional `tts`
extra and is imported lazily: the dictation path never pays for it.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

INSTALL_HINT = 'Soprano is not installed. Run:  uv pip install -e ".[tts]"'


class SpeechUnavailable(RuntimeError):
    pass


class Speaker:
    """Lazily loads Soprano and plays synthesized speech through the speakers."""

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self._model = None
        self._lock = threading.Lock()
        self._load_failed: str | None = None

    @staticmethod
    def is_installed() -> bool:
        from importlib.util import find_spec

        try:
            return find_spec("soprano") is not None
        except (ImportError, ValueError):
            return False

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self):  # noqa: ANN201
        with self._lock:
            if self._model is not None:
                return self._model
            if self._load_failed:
                raise SpeechUnavailable(self._load_failed)
            try:
                from soprano import SopranoTTS
            except Exception as exc:
                self._load_failed = f"{INSTALL_HINT} ({exc})"
                raise SpeechUnavailable(self._load_failed) from exc

            log.info("Loading Soprano TTS (first run downloads the model)...")
            started = time.perf_counter()
            try:
                self._model = SopranoTTS(
                    backend=str(self.cfg.get("backend", "auto")),
                    device=str(self.cfg.get("device", "auto")),
                    cache_size_mb=int(self.cfg.get("cache_size_mb", 100)),
                    decoder_batch_size=int(self.cfg.get("decoder_batch_size", 1)),
                )
            except Exception as exc:
                self._load_failed = f"Soprano failed to load: {exc}"
                raise SpeechUnavailable(self._load_failed) from exc
            log.info("Soprano ready in %.1fs", time.perf_counter() - started)
            return self._model

    def _sampling_kwargs(self) -> dict:
        return {
            "temperature": float(self.cfg.get("temperature", 0.4)),
            "top_p": float(self.cfg.get("top_p", 0.95)),
            "repetition_penalty": float(self.cfg.get("repetition_penalty", 1.2)),
        }

    def _save_path(self) -> Path | None:
        raw = str(self.cfg.get("save_dir", "") or "").strip()
        if not raw:
            return None
        directory = Path(raw).expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return directory / f"speak-{stamp}.wav"

    def speak(self, text: str) -> None:
        """Synthesize and play `text`. Blocks until playback finishes."""
        text = text.strip()
        if not text:
            return
        model = self.load()
        kwargs = self._sampling_kwargs()
        destination = self._save_path()

        # Streaming plays as it generates (<15 ms latency on GPU per Soprano's
        # docs) but cannot also write a file, so saving forces the batch path.
        if self.cfg.get("streaming", True) and destination is None:
            try:
                from soprano.utils.streaming import play_stream

                stream = model.infer_stream(text, chunk_size=1, **kwargs)
                play_stream(stream)
                return
            except Exception as exc:
                log.warning("Streaming playback failed (%s); falling back.", exc)

        if destination is not None:
            model.infer(text, str(destination), **kwargs)
            log.info("Saved %s", destination)
            _play_file(destination)
        else:
            audio = model.infer(text, **kwargs)
            _play_array(audio)


def _play_array(audio, sample_rate: int = 32000) -> None:
    """Play whatever `infer` handed back. Soprano outputs 32 kHz mono."""
    import numpy as np
    import sounddevice as sd

    data = audio
    # infer() may return a tensor, a bare array, or (audio, sample_rate).
    if isinstance(data, tuple) and len(data) == 2:
        data, maybe_rate = data
        if isinstance(maybe_rate, (int, float)) and maybe_rate > 1000:
            sample_rate = int(maybe_rate)
    if hasattr(data, "detach"):
        data = data.detach().cpu().numpy()
    data = np.asarray(data, dtype="float32").squeeze()
    if data.ndim > 1:
        data = data[0] if data.shape[0] < data.shape[-1] else data[:, 0]
    sd.play(data, samplerate=sample_rate)
    sd.wait()


def _play_file(path: Path) -> None:
    import wave

    import numpy as np
    import sounddevice as sd

    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    data = np.frombuffer(frames, dtype=np.int16).astype("float32") / 32768.0
    sd.play(data, samplerate=rate)
    sd.wait()


class SystemVoice:
    """Windows' built-in SAPI5 voice, for short spoken replies.

    Soprano sounds better but drags in torch and transformers -- several
    gigabytes of install and a large resident footprint. Confirmations like
    "Opening Blender" do not justify that on a low-spec machine, and SAPI is
    already present on every Windows install at no memory cost.

    Two backends: comtypes when available (in-process, instant), otherwise a
    detached PowerShell call.
    """

    def __init__(self, enabled: bool = True, rate: int = 1) -> None:
        self.enabled = enabled and sys.platform == "win32"
        self.rate = max(-10, min(10, int(rate)))
        self._voice = None
        self._checked = False
        self._lock = threading.Lock()

    def _com_voice(self):  # noqa: ANN201
        if self._checked:
            return self._voice
        self._checked = True
        try:
            import comtypes.client

            self._voice = comtypes.client.CreateObject("SAPI.SpVoice")
            self._voice.Rate = self.rate
        except Exception as exc:
            log.debug("SAPI via comtypes unavailable: %s", exc)
            self._voice = None
        return self._voice

    def _powershell(self, text: str) -> None:
        """Fallback path. The script is a fixed string and the text travels in
        an environment variable, so nothing spoken can alter the command."""
        env = dict(os.environ, VV_TTS_TEXT=text, VV_TTS_RATE=str(self.rate))
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "$s.Rate = [int]$env:VV_TTS_RATE;"
            "$s.Speak($env:VV_TTS_TEXT)"
        )
        subprocess.Popen(  # noqa: S603 - fixed argv, shell=False, text via env
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            env=env,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def say(self, text: str, block: bool = False) -> bool:
        """Speak `text`. Returns False if no voice was available."""
        text = " ".join(str(text).split())
        if not text or not self.enabled:
            return False

        def run() -> None:
            with self._lock:
                voice = self._com_voice()
                try:
                    if voice is not None:
                        voice.Speak(text)
                    else:
                        self._powershell(text)
                except Exception as exc:
                    log.debug("system voice failed: %s", exc)

        if block:
            run()
        else:
            threading.Thread(target=run, name="system-voice", daemon=True).start()
        return True
