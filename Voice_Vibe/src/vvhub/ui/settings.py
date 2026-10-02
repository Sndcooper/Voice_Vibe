"""Validate config.toml text before the control app replaces the file.

Errors (file untouched): TOML syntax; a value whose type can't work with
Voice Vibe's default (voicevibe.config.DEFAULTS: bool must stay bool, numbers
numbers, lists lists, tables tables; a string default also accepts a bool,
for tri-state keys like partials = "auto" | true | false); Stereo Mix in
[audio].input_priority (TASK.md rule 20: it records silence). Warnings (saved
anyway): unknown sections or keys, an explicit loopback input_device.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

ARRAY_TABLES = {"commands", "profiles", "replacements"}
LOOPBACK = ("stereo mix", "what u hear", "loopback")


def _kind(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "table"
    return type(value).__name__


def _compatible(default: Any, value: Any) -> bool:
    want, got = _kind(default), _kind(value)
    if default is None or want == got:
        return True
    return want == "string" and got == "bool"


def validate(text: str, defaults: dict | None = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return [f"TOML syntax: {exc}"], []
    if defaults is None:
        from voicevibe.config import DEFAULTS as defaults  # stdlib-only module
    for section, value in data.items():
        if section in ARRAY_TABLES:
            if not isinstance(value, list):
                errors.append(f"[[{section}]] must be an array of tables")
            continue
        if section not in defaults:
            warnings.append(f"[{section}] isn't in Voice Vibe's defaults (kept as is; check the spelling)")
            continue
        if not isinstance(value, dict):
            errors.append(f"[{section}] must be a table")
            continue
        for key, item in value.items():
            known = defaults[section]
            if key not in known:
                warnings.append(f"{section}.{key} isn't in Voice Vibe's defaults (kept as is; check the spelling)")
            elif not _compatible(known[key], item):
                errors.append(f"{section}.{key} should be a {_kind(known[key])}, not a {_kind(item)}")
    audio = data.get("audio") if isinstance(data.get("audio"), dict) else {}
    priority = audio.get("input_priority")
    if isinstance(priority, list):
        for name in priority:
            if any(bad in str(name).lower() for bad in LOOPBACK):
                errors.append(f"audio.input_priority: '{name}' is a loopback that records silence; use a real mic")
    device = str(audio.get("input_device") or "").lower()
    if any(bad in device for bad in LOOPBACK):
        warnings.append("audio.input_device is a loopback device: Voice Vibe will record silence")
    return errors, warnings


def write(path: Path, text: str) -> Path:
    """Replace `path` atomically, keeping the previous file as `<name>.bak`."""
    path = Path(path)
    backup = path.with_name(path.name + ".bak")
    if path.exists():
        backup.write_bytes(path.read_bytes())
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return backup
