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
        "partials": "auto",
        "partial_interval": 0.8,
    },
    "wake": {
        "enabled": True,
        "phrases": ["hey computer", "okay computer", "ok computer"],
        "sleep_phrases": ["never mind", "go to sleep"],
        "fuzzy": 0.82,
        "bias_prompt": True,
        "active_timeout": 20.0,
        "log_ignored": True,
        "engine": "whisper",
        "model": "hey_jarvis",
        "threshold": 0.5,
        "confirm_with_whisper": True,
    },
    "model": {
        "name": "auto",
        "device": "auto",
        "compute_type": "auto",
        "cpu_threads": 0,
        "language": "en",
        "beam_size": 3,
        "vad_filter": False,
        "log_prob_threshold": -1.0,
        "initial_prompt": "",
        "command_model": "auto",
        "command_max_seconds": 3.0,
    },
    "audio": {
        "sample_rate": 16000,
        "input_device": "",
        "input_priority": [],
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
        "raw_dictation": False,
        "polish": True,
        "voice_commands": True,
        "command_delay": 0.12,
        "spoken_edits": False,
        "apply_replacements": False,
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
        "enabled": False,
        "launch_apps": True,
        "answer_screen": True,
        "discover_apps": False,
        "match_threshold": 0.78,
        "speak_replies": True,
        "voice_rate": 1,
    },
    "control": {
        "enabled": False,
        "prefixes": ["computer"],
        "scroll_amount": 5,
        "keep_scrolling_limit": 30.0,
        "badge_seconds": 20.0,
        "implicit_click": True,
        "implicit_ocr": True,
        "confirm_words": ["delete", "uninstall", "send", "buy"],
        "confirm_timeout": 8.0,
        "yes_words": ["yes", "confirm"],
        "no_words": ["no", "cancel", "stop", "never mind"],
    },
    "vocab": {
        "hotwords": [],
        "app_prompts": True,
        "prompts": {},
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
    control: dict[str, Any] = field(default_factory=dict)
    vocab: dict[str, Any] = field(default_factory=dict)
    screen: dict[str, Any] = field(default_factory=dict)
    airoot: dict[str, Any] = field(default_factory=dict)
    apps: list[dict[str, Any]] = field(default_factory=list)
    profiles: list[dict[str, Any]] = field(default_factory=list)
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
        # Memoised: callers read this often. refresh_input_device() re-checks.
        if "_resolved" not in self._device_cache:
            from .audio import default_input_device

            self._device_cache["_resolved"] = default_input_device(
                self.audio.get("input_priority", [])
            )
        return self._device_cache["_resolved"]

    @property
    def input_device_pinned(self) -> bool:
        """[audio].input_device names a device, so nothing is auto-chosen."""
        return self.audio.get("input_device", "") not in ("", None)

    def refresh_input_device(self) -> int | str | None:
        """Re-read the devices and choose again (the Windows default may have
        changed, or a headset been plugged in or out). No stream may be open."""
        if self.input_device_pinned:
            return self.input_device
        from .audio import refresh_devices

        refresh_devices()
        self._device_cache.pop("_resolved", None)
        return self.input_device


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

    tables = ("replacements", "commands", "apps", "profiles")
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
    # Per-app command tables; checked (and bad phrases dropped) by profiles.py.
    profiles = [
        {
            "process": str(item.get("process", "")).strip().lower(),
            "commands": dict(item.get("commands", {})),
            "builtin": bool(item.get("builtin", True)),
        }
        for item in raw.get("profiles", [])
        if item.get("process") and isinstance(item.get("commands", {}), dict)
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
        control=merged["control"],
        vocab=merged["vocab"],
        screen=merged["screen"],
        airoot=merged["airoot"],
        apps=apps,
        profiles=profiles,
        replacements=replacements,
        commands=commands,
        path=path,
    )
