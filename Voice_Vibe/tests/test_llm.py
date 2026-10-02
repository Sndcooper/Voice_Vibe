"""vvhub.llm: the FreeLLMAPI client. httpx MockTransport; no network."""

from __future__ import annotations

import asyncio
import base64
import json
import struct
import unittest
import zlib

import stubs

stubs.install()

import httpx  # noqa: E402

from vvhub import llm  # noqa: E402
from vvhub.llm import Client, LLMUnavailable  # noqa: E402


def run(coro):  # noqa: ANN001, ANN201
    return asyncio.run(coro)


def png(width: int, height: int) -> bytes:
    """A real (tiny-payload) PNG header of the given size."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + chunk
            + struct.pack(">I", zlib.crc32(chunk)) + b"\x00\x00\x00\x00IEND\xaeB`\x82")


def ok(text: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


class Server:
    """Scripted responses, recording every request."""

    def __init__(self, *responses) -> None:  # noqa: ANN002
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        status, body, headers = item if len(item) == 3 else (*item, {})
        return httpx.Response(status, json=body, headers=headers)

    def client(self, key: str | None = "freellmapi-test", **kw) -> Client:  # noqa: ANN003
        return Client(key=lambda: key, transport=httpx.MockTransport(self), backoff=0, **kw)

    def body(self, i: int = -1) -> dict:
        return json.loads(self.requests[i].content)


class CompleteTests(unittest.TestCase):
    def test_request_shape_and_answer(self) -> None:
        server = Server((200, ok("  Hello there.  ")))
        text = run(server.client().complete([{"role": "user", "content": "hi"}], max_tokens=50))
        self.assertEqual(text, "Hello there.")
        req = server.requests[0]
        self.assertEqual(str(req.url), "http://localhost:3001/v1/chat/completions")
        self.assertEqual(req.headers["authorization"], "Bearer freellmapi-test")
        body = server.body()
        self.assertEqual((body["model"], body["max_tokens"], body["stream"]), ("auto", 50, False))
        self.assertEqual(body["messages"], [{"role": "user", "content": "hi"}])

    def test_pool_exhausted_is_unavailable_with_retry_time(self) -> None:
        server = Server((429, {"error": {"type": "rate_limit_error", "message": "All models exhausted.",
                                         "retryAtMs": 0}}, {"Retry-After": "240"}))
        with self.assertRaises(LLMUnavailable) as caught:
            run(server.client().complete([{"role": "user", "content": "hi"}]))
        self.assertEqual(caught.exception.kind, "exhausted")
        self.assertEqual(caught.exception.retry_after, 240)
        self.assertIn("4 minutes", caught.exception.spoken)
        self.assertEqual(len(server.requests), 1)  # the pool already failed over; no retry

    def test_transient_errors_are_retried(self) -> None:
        server = Server((502, {"error": {"type": "provider_error", "message": "upstream"}}),
                        (200, ok("done")))
        self.assertEqual(run(server.client().complete([{"role": "user", "content": "x"}])), "done")
        self.assertEqual(len(server.requests), 2)

    def test_retries_run_out(self) -> None:
        server = Server((503, {"error": {"message": "degraded"}}))
        with self.assertRaises(LLMUnavailable) as caught:
            run(server.client(retries=2).complete([{"role": "user", "content": "x"}]))
        self.assertEqual(len(server.requests), 3)
        self.assertEqual(caught.exception.kind, "unavailable")

    def test_not_running(self) -> None:
        server = Server(httpx.ConnectError("refused"))
        with self.assertRaises(LLMUnavailable) as caught:
            run(server.client(retries=0).complete([{"role": "user", "content": "x"}]))
        self.assertEqual(caught.exception.kind, "offline")
        self.assertIn("FreeLLMAPI", caught.exception.spoken)

    def test_missing_key_never_calls(self) -> None:
        server = Server((200, ok("x")))
        with self.assertRaises(LLMUnavailable) as caught:
            run(server.client(key=None).complete([{"role": "user", "content": "x"}]))
        self.assertEqual(caught.exception.kind, "no_key")
        self.assertEqual(server.requests, [])

    def test_bad_key(self) -> None:
        server = Server((401, {"error": {"message": "bad key"}}))
        with self.assertRaises(LLMUnavailable) as caught:
            run(server.client().complete([{"role": "user", "content": "x"}]))
        self.assertEqual(caught.exception.kind, "no_key")

    def test_empty_answer(self) -> None:
        server = Server((200, {"choices": [{"message": {"content": ""}}]}))
        with self.assertRaises(LLMUnavailable):
            run(server.client().complete([{"role": "user", "content": "x"}]))

    def test_only_loopback_base_urls(self) -> None:
        with self.assertRaises(ValueError):
            Client(base_url="https://api.example.com/v1")
        Client(base_url="http://127.0.0.1:3001/v1")


class VisionTests(unittest.TestCase):
    def test_image_is_sent_as_a_data_url_part(self) -> None:
        server = Server((200, ok("A stack trace.")))
        image = png(800, 500)
        self.assertEqual(run(server.client().vision("What is this?", image)), "A stack trace.")
        content = server.body()["messages"][-1]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "What is this?"})
        url = content[1]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/png;base64,"))
        self.assertEqual(base64.b64decode(url.split(",", 1)[1]), image)

    def test_system_message_goes_first(self) -> None:
        server = Server((200, ok("x")))
        run(server.client().vision("q", png(10, 10), system="data only"))
        self.assertEqual(server.body()["messages"][0], {"role": "system", "content": "data only"})

    def test_full_screenshots_are_refused(self) -> None:
        server = Server((200, ok("x")))
        with self.assertRaises(ValueError):
            run(server.client().vision("q", png(1920, 1080)))
        with self.assertRaises(ValueError):
            run(server.client().vision("q", b"not a png"))
        self.assertEqual(server.requests, [])

    def test_no_vision_model(self) -> None:
        server = Server((422, {"error": {"code": "no_vision_model", "message": "none"}}))
        with self.assertRaises(LLMUnavailable) as caught:
            run(server.client().vision("q", png(10, 10)))
        self.assertEqual(caught.exception.kind, "no_vision")


class ModuleTests(unittest.TestCase):
    def test_module_functions_use_the_shared_client(self) -> None:
        server = Server((200, ok("shared")))
        old = llm.set_client(server.client())
        try:
            self.assertEqual(run(llm.complete([{"role": "user", "content": "x"}])), "shared")
        finally:
            llm.set_client(old)

    def test_key_comes_from_the_secret_store(self) -> None:
        from vvhub import secrets

        secrets.use_backend({llm.KEY_NAME: "freellmapi-from-keyring"})
        try:
            self.assertEqual(llm.default_key(), "freellmapi-from-keyring")
        finally:
            secrets.use_backend(None)


if __name__ == "__main__":
    unittest.main()
