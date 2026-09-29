"""Secrets in Windows Credential Manager via `keyring` (rule 18).

Never read tokens from config files. Tests call `use_backend(dict_like)`.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

SERVICE = "voicevibe"

_backend: Any = None  # a MutableMapping in tests; None = real keyring


def use_backend(backend: Any) -> None:
    """Swap in a dict (tests) or None (real keyring)."""
    global _backend
    _backend = backend


def get(name: str) -> str | None:
    if _backend is not None:
        return _backend.get(name)
    try:
        import keyring

        return keyring.get_password(SERVICE, name)
    except Exception as exc:  # noqa: BLE001 - no keyring must not crash the hub
        log.warning("keyring unavailable reading %s: %s", name, exc)
        return None


def set(name: str, value: str) -> None:  # noqa: A001 - matches the spec name
    if _backend is not None:
        _backend[name] = value
        return
    import keyring

    keyring.set_password(SERVICE, name, value)


def delete(name: str) -> None:
    if _backend is not None:
        _backend.pop(name, None)
        return
    import keyring

    try:
        keyring.delete_password(SERVICE, name)
    except keyring.errors.PasswordDeleteError:
        pass
