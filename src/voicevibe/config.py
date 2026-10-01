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
        "toggle": "ctrl+alt+space",
        "quit": "ctrl+alt+shift+q",
    },
    # While listening: how a pause is told from the end of a sentence.
    "continuous": {
        "silence_duration": 1.5,
        "speech_ratio": 4.0,
        "min_rms": 0.006,
        "min_segment": 0.3,
        "max_segment": 60.0,
        "pre_roll": 0.35,
    },
    "model": {
        "name": "auto",
        "engine": "auto",
        "device": "auto",
        "compute_type": "auto",
        "cpu_threads": 0,
        "language": "en",
        "beam_size": 3,
        "vad_filter": True,
        "temperature_fallback": True,
        "drop_unsure_short": True,
        "unsure_logprob": -0.8,
        "log_prob_threshold": -1.0,
        "initial_prompt": "",
    },
    "audio": {
        "sample_rate": 16000,
        "input_device": "",
        "input_priority": [],
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
    },
    "feedback": {
        "sounds": True,
        "tray_icon": True,
        "log_transcripts": True,
    },
    # The built-in orb: no extra dependencies, used when Airoot is unavailable.
    "overlay": {
        "enabled": False,
        "position": "bottom-right",
        "size": 58,
        "margin": 28,
        "opacity": 0.95,
        "expand_seconds": 4.0,
        "max_width": 460,
    },
    # The animated Airoot logo (assets/airoot_overlay.py).
    "airoot": {
        "enabled": True,
        "exe": "",
        "port": 53873,
        "preload": True,
        "quit_on_exit": True,
    },
}


@dataclass
class Config:
    hotkeys: dict[str, Any] = field(default_factory=dict)
    model: dict[str, Any] = field(default_factory=dict)
    audio: dict[str, Any] = field(default_factory=dict)
    continuous: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    feedback: dict[str, Any] = field(default_factory=dict)
    overlay: dict[str, Any] = field(default_factory=dict)
    airoot: dict[str, Any] = field(default_factory=dict)
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

    merged = _merge(DEFAULTS, raw)
    return Config(
        hotkeys=merged["hotkeys"],
        model=merged["model"],
        audio=merged["audio"],
        continuous=merged["continuous"],
        output=merged["output"],
        feedback=merged["feedback"],
        overlay=merged["overlay"],
        airoot=merged["airoot"],
        path=path,
    )
