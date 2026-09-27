"""Config loading with defaults, so a missing or partial config.toml still works."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# tomllib is stdlib from 3.11. pyproject declares 3.10 support, so keep the
# backport path rather than crashing on import there.
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.10 only
    import tomli as tomllib

DEFAULTS: dict[str, Any] = {
    "hotkeys": {
        # Not F-keys: most laptops send brightness/volume from the top row
        # unless Fn is held, so an F-key default silently does nothing.
        "dictate": "ctrl+alt+space",
        "dictate_hold": "",
        "session": "ctrl+alt+w",
        "speak": "ctrl+alt+shift+space",
        "speak_hold": "",
        "quit": "ctrl+alt+shift+q",
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
        "name": "auto",
        "device": "auto",
        "compute_type": "auto",
        "cpu_threads": 0,
        "language": "en",
        "beam_size": 1,
        "vad_filter": True,
        "silence_peak": 0.02,
        "no_speech_threshold": 0.6,
        "log_prob_threshold": -1.0,
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
        "restore_delay": 0.5,
        "type_delay": 0.004,
        "add_trailing_space": True,
        "strip_trailing_period": False,
        "lowercase": False,
        "polish": True,
        "format_lists": True,
        "bullet": "-",
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
    "overlay": {
        "enabled": True,
        "position": "bottom-right",
        "size": 58,
        "margin": 28,
        "opacity": 0.95,
        "expand_seconds": 4.0,
        "max_width": 460,
    },
    "history": {
        "enabled": True,
        "keep_days": 30,
    },
    "assistant": {
        "enabled": True,
        "launch_apps": True,
        "answer_screen": True,
        "discover_apps": True,
        "match_threshold": 0.78,
        "speak_replies": True,
        "voice_rate": 1,
    },
    "airoot": {
        "enabled": False,
        "exe": "",
        "port": 53873,
        "preload": True,
        "quit_on_exit": True,
    },
    "screen": {
        "enabled": True,
        "use_selection": True,
        "use_uia": True,
        "use_ocr": True,
        "max_chars": 4000,
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
    overlay: dict[str, Any] = field(default_factory=dict)
    history: dict[str, Any] = field(default_factory=dict)
    assistant: dict[str, Any] = field(default_factory=dict)
    screen: dict[str, Any] = field(default_factory=dict)
    airoot: dict[str, Any] = field(default_factory=dict)
    apps: list[dict[str, Any]] = field(default_factory=list)
    replacements: list[dict[str, str]] = field(default_factory=list)
    commands: list[dict[str, str]] = field(default_factory=list)
    path: Path | None = None
    # Memoised auto-detected input device; see the input_device property.
    _device_cache: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def input_device(self) -> int | str | None:
        raw = self.audio.get("input_device", "")
        if raw not in ("", None):
            if isinstance(raw, str) and raw.isdigit():
                return int(raw)
            return raw

        # Empty means "the system default" -- except when that default is a
        # loopback, which silently records the speakers instead of speech.
        # Resolved once: every caller would otherwise re-scan the device list
        # and repeat the warning.
        if "_resolved" not in self._device_cache:
            from .audio import default_input_device

            self._device_cache["_resolved"] = default_input_device()
        return self._device_cache["_resolved"]


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

    tables = ("replacements", "commands", "apps")
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
    apps = [
        {
            "say": str(item.get("say", "")).strip(),
            "path": str(item.get("path", "")).strip(),
            "args": [str(a) for a in item.get("args", [])],
        }
        for item in raw.get("apps", [])
        if item.get("say") and item.get("path")
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
        overlay=merged["overlay"],
        history=merged["history"],
        assistant=merged["assistant"],
        screen=merged["screen"],
        airoot=merged["airoot"],
        apps=apps,
        replacements=replacements,
        commands=commands,
        path=path,
    )
