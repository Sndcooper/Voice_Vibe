"""FreeLLMAPI client: text and vision generation, never decisions (rule 9).

FreeLLMAPI (github.com/tashfeenahmed/freellmapi, pinned in THIRD_PARTY.lock)
is a local router on http://localhost:3001/v1 that fails over across free
providers. This client is only glue around its OpenAI-compatible
`/v1/chat/completions`:

  complete(messages, model="auto", max_tokens=800) -> str     §3.7
  vision(prompt, png_bytes) -> str                             §3.7
  LLMUnavailable(kind, spoken, retry_after)                    kinds below

  exhausted    429 rate_limit_error: every provider is rate-limited or out of
               quota. FreeLLMAPI already failed over, so no retry here; the
               Retry-After header says when the pool recovers.
  unavailable  5xx / timeouts after `retries` short retries
  offline      nothing listening on :3001 (the tray app isn't running)
  no_key       no unified key in the keyring (`freellmapi_key`), or 401
  no_vision    422 no_vision_model: no vision model enabled in the chain

`LLMUnavailable.spoken` is a sentence Voice Vibe can say as-is.

Only loopback base URLs are accepted: FreeLLMAPI itself forwards prompts to
cloud providers (TASK.md §2), so callers must send only what the user asked
about -- vision gets crops, never whole screens (`vision` refuses images
larger than MAX_VISION_SIZE).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import struct
from typing import Any, Callable
from urllib.parse import urlparse

log = logging.getLogger(__name__)

BASE_URL = "http://localhost:3001/v1"
KEY_NAME = "freellmapi_key"
TIMEOUT = 60.0
RETRIES = 2
BACKOFF = 1.0
# Crops are ~800x500; this leaves room for a HiDPI crop, not a monitor.
MAX_VISION_SIZE = (1400, 1000)
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class LLMUnavailable(RuntimeError):
    def __init__(self, kind: str, message: str, spoken: str = "",
                 retry_after: float | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.retry_after = retry_after
        self.spoken = spoken or _SPOKEN.get(kind, "The AI service isn't answering right now.")


_SPOKEN = {
    "unavailable": "The free AI providers aren't answering right now. Try again in a bit.",
    "offline": "FreeLLMAPI isn't running, so I can't write that. Start it from the tray.",
    "no_key": "FreeLLMAPI's key isn't set up. Add the unified key to the keyring as "
              "freellmapi_key.",
    "no_vision": "No vision model is enabled in FreeLLMAPI, so I can't look at the image.",
}


def _exhausted_spoken(seconds: float | None) -> str:
    base = "The free AI pool is used up for now"
    if not seconds:
        return base + ". Try again later."
    minutes = max(1, round(seconds / 60))
    return f"{base}. Try again in about {minutes} minute{'s' if minutes != 1 else ''}."


def default_key() -> str | None:
    from . import secrets

    return secrets.get(KEY_NAME)


def png_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


class Client:
    def __init__(self, base_url: str = BASE_URL, key: Callable[[], str | None] = default_key,
                 timeout: float = TIMEOUT, retries: int = RETRIES, backoff: float = BACKOFF,
                 transport: Any = None) -> None:
        host = urlparse(base_url).hostname or ""
        if host not in _LOOPBACK:
            raise ValueError(f"FreeLLMAPI must be local, got {base_url!r}")
        self.base_url = base_url.rstrip("/")
        self.key = key
        self.timeout = timeout
        self.retries = max(0, int(retries))
        self.backoff = backoff
        self.transport = transport

    async def _post(self, body: dict) -> str:
        import httpx

        key = self.key()
        if not key:
            raise LLMUnavailable("no_key", "no FreeLLMAPI key in the keyring")
        headers = {"Authorization": f"Bearer {key}"}
        last: LLMUnavailable | None = None
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as http:
            for attempt in range(self.retries + 1):
                if attempt and self.backoff:
                    await asyncio.sleep(self.backoff * attempt)
                try:
                    response = await http.post(f"{self.base_url}/chat/completions",
                                               json=body, headers=headers)
                except httpx.ConnectError as exc:
                    last = LLMUnavailable("offline", f"FreeLLMAPI not reachable: {exc}")
                    continue
                except httpx.TimeoutException as exc:
                    last = LLMUnavailable("unavailable", f"FreeLLMAPI timed out: {exc}")
                    continue
                failure = self._failure(response)
                if failure is None:
                    return self._text(response)
                if failure.kind != "unavailable":
                    raise failure
                last = failure
        assert last is not None
        raise last

    @staticmethod
    def _failure(response: Any) -> LLMUnavailable | None:
        status = response.status_code
        if status < 400:
            return None
        try:
            error = (response.json() or {}).get("error") or {}
        except ValueError:
            error = {}
        message = str(error.get("message") or response.text[:200] or status)
        if status == 429:
            retry = response.headers.get("Retry-After")
            seconds = float(retry) if retry and retry.replace(".", "", 1).isdigit() else None
            return LLMUnavailable("exhausted", message, _exhausted_spoken(seconds), seconds)
        if status == 401 or error.get("code") == "provider_authentication_failed":
            return LLMUnavailable("no_key", message)
        if status == 422 and error.get("code") == "no_vision_model":
            return LLMUnavailable("no_vision", message)
        if status >= 500:
            return LLMUnavailable("unavailable", message)
        return LLMUnavailable("rejected", message, "The AI service refused that request.")

    @staticmethod
    def _text(response: Any) -> str:
        try:
            text = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable("unavailable", f"unexpected reply: {exc}") from exc
        if isinstance(text, list):  # content parts
            text = "".join(str(p.get("text", "")) for p in text if isinstance(p, dict))
        text = str(text or "").strip()
        if not text:
            raise LLMUnavailable("unavailable", "empty reply")
        routed = response.headers.get("X-Routed-Via")
        if routed:
            log.info("FreeLLMAPI answered via %s", routed)
        return text

    async def complete(self, messages: list[dict], model: str = "auto",
                       max_tokens: int = 800) -> str:
        return await self._post({"model": model, "messages": list(messages),
                                 "max_tokens": int(max_tokens), "stream": False})

    async def vision(self, prompt: str, png_bytes: bytes, system: str = "",
                     max_tokens: int = 500, model: str = "auto") -> str:
        size = png_size(png_bytes)
        if size is None:
            raise ValueError("vision takes a PNG crop")
        if size[0] > MAX_VISION_SIZE[0] or size[1] > MAX_VISION_SIZE[1]:
            raise ValueError(f"{size[0]}x{size[1]} is not a crop; vision only gets crops")
        url = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": url}},
        ]})
        return await self.complete(messages, model=model, max_tokens=max_tokens)


_client: Client | None = None


def client() -> Client:
    global _client
    if _client is None:
        _client = Client()
    return _client


def set_client(new: Client | None) -> Client | None:
    global _client
    old, _client = _client, new
    return old


async def complete(messages: list[dict], model: str = "auto", max_tokens: int = 800) -> str:
    return await client().complete(messages, model=model, max_tokens=max_tokens)


async def vision(prompt: str, png_bytes: bytes, system: str = "") -> str:
    return await client().vision(prompt, png_bytes, system=system)
