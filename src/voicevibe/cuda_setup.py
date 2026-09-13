"""Make pip-installed NVIDIA runtime DLLs visible to ctranslate2 on Windows.

ctranslate2 >= 4.5 links against cuBLAS 12 and cuDNN 9. On Windows those DLLs
ship inside the `nvidia-*-cu12` wheels under `site-packages/nvidia/*/bin`, but
Windows' loader does not look there. `os.add_dll_directory` fixes that, and it
must run *before* ctranslate2 (and therefore faster_whisper) is imported.
"""

from __future__ import annotations

import os
import sys
import sysconfig
from pathlib import Path

_done = False


def _nvidia_roots() -> list[Path]:
    roots: list[Path] = []
    for key in ("purelib", "platlib"):
        path = sysconfig.get_paths().get(key)
        if path:
            roots.append(Path(path) / "nvidia")
    for entry in sys.path:
        if entry:
            roots.append(Path(entry) / "nvidia")
    seen: set[Path] = set()
    unique: list[Path] = []
    for root in roots:
        if root not in seen:
            seen.add(root)
            unique.append(root)
    return unique


def register_cuda_dlls() -> list[Path]:
    """Add every bundled NVIDIA `bin`/`lib` directory to the DLL search path."""
    global _done
    added: list[Path] = []
    if _done or sys.platform != "win32":
        return added

    for root in _nvidia_roots():
        if not root.is_dir():
            continue
        for sub in sorted(root.iterdir()):
            for name in ("bin", "lib"):
                candidate = sub / name
                if not candidate.is_dir():
                    continue
                if not any(candidate.glob("*.dll")):
                    continue
                try:
                    os.add_dll_directory(str(candidate))
                except OSError:
                    continue
                added.append(candidate)

    if added:
        joined = os.pathsep.join(str(p) for p in added)
        os.environ["PATH"] = joined + os.pathsep + os.environ.get("PATH", "")

    _done = True
    return added


def cuda_available() -> bool:
    """True if ctranslate2 can actually see a usable CUDA device."""
    register_cuda_dlls()
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False
