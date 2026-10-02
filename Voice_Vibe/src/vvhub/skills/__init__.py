"""Skill discovery: every module here with a module-level `SKILL` is loaded.

A module that fails to import (a missing optional dependency, a half-written
file from another chat) is logged and skipped, never fatal (rule 19).
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any

from .base import Skill

log = logging.getLogger(__name__)


def discover(hub: Any = None) -> dict[str, Skill]:
    found: dict[str, Skill] = {}
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_") or info.name == "base":
            continue
        try:
            module = importlib.import_module(f"{__name__}.{info.name}")
        except Exception as exc:  # noqa: BLE001
            log.warning("Skill module %s not loaded: %s", info.name, exc)
            continue
        skill = getattr(module, "SKILL", None)
        if not isinstance(skill, Skill):
            continue
        if not skill.name:
            skill.name = info.name
        skill.bind(hub)
        found[skill.name] = skill
    return found


__all__ = ["Skill", "discover"]
