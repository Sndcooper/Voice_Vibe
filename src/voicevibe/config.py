"""Config loading with defaults, so a missing or partial config.toml still works."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "hotkeys": {
        "dictate": "f9",
        "dictate_hold": "",
        "session": "f10",
        "speak": "shift+f9",
        "speak_hold": "",
        "quit": "ctrl+shift+f12",
    },
    "continuous": {
        "silence_duration": 1.5,
        "speech_ratio": 4.0,
        "min_rms": 0.006,
        "min_segment": 0.3,
        "max_segment": 60.0,
        "pre_roll": 0.35,
    },
    "wake": {
        "enabled": True,
        "phrases": ["hey computer", "okay computer", "ok computer"],
        "sleep_phrases": ["never mind", "go to sleep"],
        "fuzzy": 0.82,
        "bias_prompt": True,
        "active_timeout": 20.0,
        "log_ignored": True,
    },
    "model": {
        "name": "large-v3-turbo",
        "device": "auto",
        "compute_type": "auto",
        "language": "en",
        "beam_size": 1,
        "vad_filter": True,
        "initial_prompt": "",
    },
    "audio": {
        "sample_rate": 16000,
        "input_device": "",
        "min_duration": 0.25,
        "max_duration": 300.0,
    },
    "output": {
        "mode": "paste",
        "restore_clipboard": True,
        "type_delay": 0.004,
        "add_trailing_space": True,
        "strip_trailing_period": False,
        "lowercase": False,
        "voice_commands": True,
        "command_delay": 0.12,
    },
    "speech": {
        "device": "auto",
        "backend": "auto",
        "streaming": True,
        "temperature": 0.4,
        "top_p": 0.95,
        "repetition_penalty": 1.2,
        "cache_size_mb": 100,
        "decoder_batch_size": 1,
        "preload": False,
        "save_dir": "",
    },
    "feedback": {
        "sounds": True,
        "tray_icon": True,
        "log_transcripts": True,
    },
}


@dataclass
class Config:
    hotkeys: dict[str, Any] = field(default_factory=dict)
    model: dict[str, Any] = field(default_factory=dict)
    audio: dict[str, Any] = field(default_factory=dict)
    continuous: dict[str, Any] = field(default_factory=dict)
    wake: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    speech: dict[str, Any] = field(default_factory=dict)
    feedback: dict[str, Any] = field(default_factory=dict)
    replacements: list[dict[str, str]] = field(default_factory=list)
    commands: list[dict[str, str]] = field(default_factory=list)
    path: Path | None = None

    @property
    def input_device(self) -> int | str | None:
        raw = self.audio.get("input_device", "")
        if raw in ("", None):
            return None
        if isinstance(raw, str) and raw.isdigit():
            return int(raw)
        return raw


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def find_config(explicit: str | Path | None = None) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    candidates = [
        Path.cwd() / "config.toml",
        Path(__file__).resolve().parents[2] / "config.toml",
        Path.home() / ".voicevibe" / "config.toml",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def load_config(explicit: str | Path | None = None) -> Config:
    path = find_config(explicit)
    raw: dict[str, Any] = {}
    if path:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)

    tables = ("replacements", "commands")
    merged = _merge(DEFAULTS, {k: v for k, v in raw.items() if k not in tables})
    replacements = [
        {"find": str(item.get("find", "")), "replace": str(item.get("replace", ""))}
        for item in raw.get("replacements", [])
        if item.get("find")
    ]
    # Phrases are matched lowercase against the end of a transcript.
    # ends_dictation controls whether firing this command sends a wake-word
    # session back to armed. True suits submit keys, False suits things like Tab.
    commands = [
        {
            "say": str(item.get("say", "")).strip().lower(),
            "keys": str(item.get("keys", "")).strip(),
            "ends_dictation": bool(item.get("ends_dictation", True)),
        }
        for item in raw.get("commands", [])
        if item.get("say") and item.get("keys")
    ]
    return Config(
        hotkeys=merged["hotkeys"],
        model=merged["model"],
        audio=merged["audio"],
        continuous=merged["continuous"],
        wake=merged["wake"],
        output=merged["output"],
        speech=merged["speech"],
        feedback=merged["feedback"],
        replacements=replacements,
        commands=commands,
        path=path,
    )
