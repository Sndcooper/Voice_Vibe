"""WS5: the control app (pywebview window on a page the hub serves) and its launcher.

- `launcher`: start the hub before Voice Vibe, detached; opt-in login autostart.
- `api`: the token-protected HTTP API the page uses (mounted by the hub).
- `window`: `python -m vvhub.ui` opens the window (only while you look at it).

Nothing here is imported by Voice Vibe; importing this package is cheap.
"""
