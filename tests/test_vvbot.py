"""Telegram bot fork (src/vvbot): everything except the python-telegram-bot glue.

What matters: the bot answers only the paired chat; pairing needs a one-time
code created on the PC (hashed at rest, expiring, lockout after repeated
misses); approval cards reach the hub only as an explicit button press or a
strict yes/no; ambiguous voice answers never approve; text and voice notes go
to the hub (`request` / `transcribe`) and the hub being down is reported, not
crashed on. No network, no Telegram, no keyring: fakes throughout.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vvbot import answers, audio, core, hub_client, pairing, utils  # noqa: E402
from vvbot.approvals import ApprovalDesk  # noqa: E402

OWNER = 555


def run(coro):
    return asyncio.run(coro)


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeMessenger:
    def __init__(self):
        self.sent: list[tuple] = []
        self.cards: list[tuple] = []
        self.edits: list[tuple] = []
        self._next = 100

    async def send_text(self, chat_id, text, reply_to=None):
        self._next += 1
        self.sent.append((chat_id, text, reply_to))
        return self._next

    async def send_card(self, chat_id, text, buttons):
        self._next += 1
        self.cards.append((chat_id, text, buttons, self._next))
        return self._next

    async def edit_text(self, chat_id, message_id, text):
        self.edits.append((chat_id, message_id, text))

    def texts(self):
        return [t for _, t, _ in self.sent]


class FakeHub:
    """Stands in for HubClient: canned replies per message type."""

    def __init__(self, replies=None, down=False):
        self.calls: list[tuple[str, dict]] = []
        self.sent: list[dict] = []
        self.replies = replies or {}
        self.down = down

    async def call(self, type_, timeout=None, **fields):
        self.calls.append((type_, fields))
        if self.down:
            raise hub_client.HubUnavailable("hub down")
        reply = self.replies.get(type_)
        if callable(reply):
            reply = reply(fields)
        return reply or {"type": "error", "message": "no reply"}

    async def send(self, msg):
        if self.down:
            raise hub_client.HubUnavailable("hub down")
        self.sent.append(msg)


def paired(tmp, clock=None):
    secrets = {"telegram_chat_id": str(OWNER)}
    return pairing.Pairing(secrets=secrets, state_path=Path(tmp) / "pair.json", clock=clock or Clock())


def make_core(tmp, hub=None, clock=None, transcode=None):
    clock = clock or Clock()
    msgr = FakeMessenger()
    hub = hub or FakeHub({"request": {"type": "reply", "text": "Done.", "speak": False, "handled": True}})
    pair = paired(tmp, clock)
    bot = core.BotCore(hub=hub, messenger=msgr, pairing=pair, clock=clock,
                       transcode=transcode or (lambda data: b"WAV" + data))
    return bot, msgr, hub


def approval_msg(aid="ab12cd34ef56", action="push", preview="Push feature/x to GitHub", timeout=None):
    msg = {"id": "req" + aid, "type": "approval_request",
           "approval": {"id": aid, "action": action, "preview": preview, "channel": "telegram",
                        "status": "pending", "created": 0, "decided_by": ""}}
    if timeout is not None:
        msg["timeout"] = timeout
    return msg


# --------------------------------------------------------------------------
class AnswerTests(unittest.TestCase):
    def test_strict_yes(self):
        for said in ("yes", "Yes.", "yes yes", "approve", "Yes, approve!", "confirm"):
            self.assertIs(answers.parse(said), True, said)

    def test_loose_no(self):
        for said in ("no", "No thanks", "cancel that", "yes no", "don't", "never mind", "deny"):
            self.assertIs(answers.parse(said), False, said)

    def test_anything_else_is_undecided(self):
        for said in ("", "Thank you.", "yes please do the other thing", "I know", "maybe", "yesterday"):
            self.assertIsNone(answers.parse(said), said)


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.secrets: dict = {}
        self.clock = Clock()
        self.p = pairing.Pairing(secrets=self.secrets, state_path=Path(self.tmp) / "p.json", clock=self.clock)

    def test_code_shape_and_not_stored_in_clear(self):
        code = self.p.new_code()
        self.assertEqual(len(code), 8)
        self.assertTrue(set(code) <= set(pairing.ALPHABET))
        self.assertNotIn(code, (Path(self.tmp) / "p.json").read_text(encoding="utf-8"))

    def test_pair_with_code(self):
        code = self.p.new_code()
        ok, _ = self.p.try_pair(OWNER, OWNER, code.lower(), "private")
        self.assertTrue(ok)
        self.assertEqual(self.p.owner, OWNER)
        self.assertEqual(self.secrets["telegram_chat_id"], str(OWNER))
        # One-time: the code is gone.
        ok, _ = self.p.try_pair(777, 777, code, "private")
        self.assertFalse(ok)
        self.assertEqual(self.p.owner, OWNER)

    def test_no_code_no_pairing(self):
        ok, _ = self.p.try_pair(OWNER, OWNER, "ABCDEFGH", "private")
        self.assertFalse(ok)
        self.assertIsNone(self.p.owner)

    def test_group_chats_cannot_pair(self):
        code = self.p.new_code()
        self.assertFalse(self.p.try_pair(-100, OWNER, code, "group")[0])

    def test_expiry(self):
        code = self.p.new_code()
        self.clock.t += pairing.CODE_TTL_SECONDS + 1
        self.assertFalse(self.p.try_pair(OWNER, OWNER, code, "private")[0])

    def test_lockout_after_failures(self):
        code = self.p.new_code()
        for _ in range(pairing.MAX_FAILED_ATTEMPTS):
            self.assertFalse(self.p.try_pair(OWNER, OWNER, "WRONGCOD", "private")[0])
        ok, msg = self.p.try_pair(OWNER, OWNER, code, "private")
        self.assertFalse(ok)
        self.assertIn("locked", msg.lower())
        self.clock.t += pairing.LOCKOUT_SECONDS + 1
        code = self.p.new_code()
        self.assertTrue(self.p.try_pair(OWNER, OWNER, code, "private")[0])

    def test_authorized_only_owner_private(self):
        self.secrets["telegram_chat_id"] = str(OWNER)
        self.assertTrue(self.p.authorized(OWNER, OWNER, "private"))
        self.assertFalse(self.p.authorized(OWNER, 1, "private"))
        self.assertFalse(self.p.authorized(1, 1, "private"))
        self.assertFalse(self.p.authorized(OWNER, OWNER, "group"))

    def test_unpaired_authorizes_nobody(self):
        self.assertFalse(self.p.authorized(OWNER, OWNER, "private"))

    def test_unpair(self):
        self.secrets["telegram_chat_id"] = str(OWNER)
        self.p.unpair()
        self.assertIsNone(self.p.owner)

    def test_corrupt_owner_value(self):
        self.secrets["telegram_chat_id"] = "not-a-number"
        self.assertIsNone(self.p.owner)


class AudioTests(unittest.TestCase):
    @staticmethod
    def wav_bytes(seconds=0.5, rate=44100, channels=2):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(2)
            w.setframerate(rate)
            frames = bytearray()
            for i in range(int(seconds * rate)):
                v = int(8000 * math.sin(2 * math.pi * 440 * i / rate))
                frames += struct.pack("<h", v) * channels
            w.writeframes(bytes(frames))
        return buf.getvalue()

    def setUp(self):
        try:
            import av  # noqa: F401
        except ImportError:
            self.skipTest("PyAV not installed")

    def test_to_wav_resamples_to_16k_mono(self):
        out = audio.to_wav(self.wav_bytes())
        with wave.open(io.BytesIO(out)) as w:
            self.assertEqual((w.getnchannels(), w.getframerate(), w.getsampwidth()), (1, 16000, 2))
            self.assertAlmostEqual(w.getnframes() / 16000, 0.5, delta=0.05)

    def test_ogg_opus_voice_note(self):
        import av

        buf = io.BytesIO()
        try:
            out = av.open(buf, "w", format="ogg")
            stream = out.add_stream("libopus", rate=48000)
        except Exception:  # noqa: BLE001
            self.skipTest("no opus encoder in this PyAV build")
        stream.layout = "mono"
        pcm = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 300 * i / 48000)))
                       for i in range(48000))
        frame = av.AudioFrame(format="s16", layout="mono", samples=48000)
        frame.planes[0].update(pcm)
        frame.rate = 48000
        for packet in stream.encode(frame):
            out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
        out.close()
        wav = audio.to_wav(buf.getvalue())
        with wave.open(io.BytesIO(wav)) as w:
            self.assertEqual(w.getframerate(), 16000)
            self.assertGreater(w.getnframes(), 12000)

    def test_too_long_rejected(self):
        with self.assertRaises(audio.AudioError):
            audio.to_wav(self.wav_bytes(seconds=2.0, rate=8000, channels=1), max_seconds=1)

    def test_garbage_rejected(self):
        with self.assertRaises(audio.AudioError):
            audio.to_wav(b"definitely not audio")


class UtilsTests(unittest.TestCase):
    def test_split_into_chunks(self):
        self.assertEqual(utils.split_into_chunks("abcdef", 4), ["abcd", "ef"])
        self.assertEqual(utils.split_into_chunks("", 4), [])

    def test_is_group_chat(self):
        from types import SimpleNamespace as NS

        self.assertTrue(utils.is_group_chat(NS(effective_chat=NS(type="supergroup"))))
        self.assertFalse(utils.is_group_chat(NS(effective_chat=NS(type="private"))))
        self.assertFalse(utils.is_group_chat(NS(effective_chat=None)))


# --------------------------------------------------------------------------
class LockTests(unittest.TestCase):
    def test_strangers_ignored_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot, msgr, hub = make_core(tmp)
            run(bot.on_text(999, 999, "computer push everything", "private"))
            run(bot.on_voice(999, 999, b"ogg", "private"))
            self.assertEqual(hub.calls, [])
            self.assertEqual(msgr.sent, [])

    def test_owner_in_group_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot, msgr, hub = make_core(tmp)
            run(bot.on_text(-1001, OWNER, "hello", "supergroup"))
            self.assertEqual(hub.calls, [])

    def test_unpaired_bot_only_explains_pairing(self):
        with tempfile.TemporaryDirectory() as tmp:
            msgr, hub = FakeMessenger(), FakeHub()
            p = pairing.Pairing(secrets={}, state_path=Path(tmp) / "p.json", clock=Clock())
            bot = core.BotCore(hub=hub, messenger=msgr, pairing=p)
            run(bot.on_text(OWNER, OWNER, "hello", "private"))
            self.assertEqual(hub.calls, [])
            self.assertIn("/pair", msgr.texts()[-1])
            code = p.new_code()
            run(bot.on_command(OWNER, OWNER, "pair", code, "private"))
            self.assertEqual(p.owner, OWNER)
            self.assertIn("paired", msgr.texts()[-1].lower())
            self.assertNotIn(code, " ".join(msgr.texts()))

    def test_pair_when_already_paired_by_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot, msgr, hub = make_core(tmp)
            run(bot.on_command(999, 999, "pair", "ABCDEFGH", "private"))
            self.assertEqual(msgr.sent, [])


class RequestTests(unittest.TestCase):
    def test_text_goes_to_hub(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot, msgr, hub = make_core(tmp)
            run(bot.on_text(OWNER, OWNER, "note this: buy milk", "private"))
            self.assertEqual(hub.calls[0][0], "request")
            self.assertEqual(hub.calls[0][1]["text"], "note this: buy milk")
            self.assertEqual(hub.calls[0][1]["source"], "telegram")
            self.assertEqual(msgr.texts()[-1], "Done.")

    def test_hub_down(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot, msgr, _ = make_core(tmp, hub=FakeHub(down=True))
            run(bot.on_text(OWNER, OWNER, "hi", "private"))
            self.assertIn("offline", msgr.texts()[-1].lower())

    def test_hub_error_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub = FakeHub({"request": {"type": "error", "message": "boom"}})
            bot, msgr, _ = make_core(tmp, hub=hub)
            run(bot.on_text(OWNER, OWNER, "hi", "private"))
            self.assertIn("boom", msgr.texts()[-1])

    def test_long_reply_chunked(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub = FakeHub({"request": {"type": "reply", "text": "x" * 9000}})
            bot, msgr, _ = make_core(tmp, hub=hub)
            run(bot.on_text(OWNER, OWNER, "hi", "private"))
            self.assertEqual(len(msgr.sent), 3)

    def test_voice_note_transcribed_by_hub_then_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub = FakeHub({"transcribe": {"type": "text", "text": "check github"},
                           "request": {"type": "reply", "text": "Nothing new."}})
            bot, msgr, _ = make_core(tmp, hub=hub)
            run(bot.on_voice(OWNER, OWNER, b"OGGDATA", "private"))
            kind, fields = hub.calls[0]
            self.assertEqual(kind, "transcribe")
            self.assertEqual(fields["format"], "wav")
            self.assertEqual(base64.b64decode(fields["audio_b64"]), b"WAVOGGDATA")
            self.assertEqual(hub.calls[1][1]["text"], "check github")
            joined = "\n".join(msgr.texts())
            self.assertIn("check github", joined)
            self.assertIn("Nothing new.", joined)

    def test_voice_transcriber_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub = FakeHub({"transcribe": {"type": "error", "message": "voicevibe", "code": "no_transcriber"}})
            bot, msgr, _ = make_core(tmp, hub=hub)
            run(bot.on_voice(OWNER, OWNER, b"x", "private"))
            self.assertEqual([c[0] for c in hub.calls], ["transcribe"])
            self.assertIn("voice vibe", msgr.texts()[-1].lower())

    def test_bad_audio(self):
        def bad(data):
            raise audio.AudioError("not audio")

        with tempfile.TemporaryDirectory() as tmp:
            bot, msgr, hub = make_core(tmp, transcode=bad)
            run(bot.on_voice(OWNER, OWNER, b"x", "private"))
            self.assertEqual(hub.calls, [])
            self.assertIn("not audio", msgr.texts()[-1])

    def test_empty_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub = FakeHub({"transcribe": {"type": "text", "text": "  "}})
            bot, msgr, _ = make_core(tmp, hub=hub)
            run(bot.on_voice(OWNER, OWNER, b"x", "private"))
            self.assertEqual(len(hub.calls), 1)


class NotifyTests(unittest.TestCase):
    def test_notify_goes_to_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot, msgr, _ = make_core(tmp)
            run(bot.on_hub_message({"id": "n1", "type": "notify", "title": "Report", "text": "3 new PRs",
                                    "level": "info"}))
            chat, text, _ = msgr.sent[-1]
            self.assertEqual(chat, OWNER)
            self.assertIn("Report", text)
            self.assertIn("3 new PRs", text)

    def test_notify_unpaired_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            msgr = FakeMessenger()
            p = pairing.Pairing(secrets={}, state_path=Path(tmp) / "p.json")
            bot = core.BotCore(hub=FakeHub(), messenger=msgr, pairing=p)
            run(bot.on_hub_message({"id": "n", "type": "notify", "title": "t", "text": "x"}))
            self.assertEqual(msgr.sent, [])

    def test_ping_answered(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot, _, hub = make_core(tmp)
            run(bot.on_hub_message({"id": "p1", "type": "ping"}))
            self.assertEqual(hub.sent[-1]["type"], "pong")
            self.assertEqual(hub.sent[-1]["re"], "p1")


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.bot, self.msgr, self.hub = make_core(self._tmp.name, clock=self.clock)

    def tearDown(self):
        self._tmp.cleanup()

    def card(self, **kw):
        run(self.bot.on_hub_message(approval_msg(**kw)))
        return self.msgr.cards[-1]

    def test_card_with_buttons(self):
        chat, text, buttons, _ = self.card()
        self.assertEqual(chat, OWNER)
        self.assertIn("Push feature/x to GitHub", text)
        self.assertEqual([b[0] for b in buttons], ["✅ Approve", "❌ Deny"])
        self.assertEqual([b[1] for b in buttons], ["ap:ab12cd34ef56:y", "ap:ab12cd34ef56:n"])
        self.assertTrue(all(len(b[1].encode()) <= 64 for b in buttons))
        self.assertEqual(self.hub.sent, [])

    def test_button_approve(self):
        _, _, _, mid = self.card()
        toast = run(self.bot.on_callback(OWNER, OWNER, "ap:ab12cd34ef56:y"))
        reply = self.hub.sent[-1]
        self.assertEqual(reply["type"], "approval_result")
        self.assertEqual(reply["re"], "reqab12cd34ef56")
        self.assertIs(reply["approved"], True)
        self.assertEqual(reply["decided_by"], "telegram")
        self.assertIn("Approved", toast)
        self.assertEqual(self.msgr.edits[-1][1], mid)
        # Second press: nothing more reaches the hub.
        run(self.bot.on_callback(OWNER, OWNER, "ap:ab12cd34ef56:y"))
        self.assertEqual(len(self.hub.sent), 1)

    def test_button_deny(self):
        self.card()
        run(self.bot.on_callback(OWNER, OWNER, "ap:ab12cd34ef56:n"))
        self.assertIs(self.hub.sent[-1]["approved"], False)

    def test_stranger_button_ignored(self):
        self.card()
        run(self.bot.on_callback(999, 999, "ap:ab12cd34ef56:y"))
        self.assertEqual(self.hub.sent, [])

    def test_bad_callback_data(self):
        self.card()
        for data in ("ap:ab12cd34ef56:maybe", "junk", "ap:unknown:y", ""):
            run(self.bot.on_callback(OWNER, OWNER, data))
        self.assertEqual(self.hub.sent, [])

    def test_expired_card_cannot_be_approved(self):
        self.card(timeout=60)
        self.clock.t += 61
        toast = run(self.bot.on_callback(OWNER, OWNER, "ap:ab12cd34ef56:y"))
        self.assertEqual(self.hub.sent, [])
        self.assertIn("expired", toast.lower())
        self.assertIn("Expired", self.msgr.edits[-1][2])

    def test_sweep_marks_expired(self):
        self.card(timeout=60)
        self.clock.t += 61
        run(self.bot.desk.sweep())
        self.assertIn("Expired", self.msgr.edits[-1][2])
        self.assertEqual(self.bot.desk.pending, {})

    def test_voice_yes_approves_single_pending(self):
        self.card()
        self.hub.replies["transcribe"] = {"type": "text", "text": "Yes."}
        run(self.bot.on_voice(OWNER, OWNER, b"x", "private"))
        result = [m for m in self.hub.sent if m["type"] == "approval_result"]
        self.assertEqual(len(result), 1)
        self.assertIs(result[0]["approved"], True)
        self.assertEqual(result[0]["answer"], "Yes.")
        self.assertNotIn("request", [c[0] for c in self.hub.calls])

    def test_voice_no_denies(self):
        self.card()
        self.hub.replies["transcribe"] = {"type": "text", "text": "no, don't"}
        run(self.bot.on_voice(OWNER, OWNER, b"x", "private"))
        self.assertIs(self.hub.sent[-1]["approved"], False)

    def test_ambiguous_voice_reply_to_card_never_approves(self):
        _, _, _, mid = self.card()
        self.hub.replies["transcribe"] = {"type": "text", "text": "Thank you."}
        run(self.bot.on_voice(OWNER, OWNER, b"x", "private", reply_to=mid))
        self.assertEqual(self.hub.sent, [])
        self.assertIn("yes", self.msgr.texts()[-1].lower())
        self.assertNotIn("request", [c[0] for c in self.hub.calls])
        self.assertIn("ab12cd34ef56", self.bot.desk.pending)

    def test_unrelated_voice_command_while_pending_goes_to_hub(self):
        self.card()
        self.hub.replies["transcribe"] = {"type": "text", "text": "what's new on github"}
        run(self.bot.on_voice(OWNER, OWNER, b"x", "private"))
        self.assertEqual(self.hub.sent, [])
        self.assertEqual(self.hub.calls[-1][0], "request")
        self.assertIn("ab12cd34ef56", self.bot.desk.pending)

    def test_yes_with_two_pending_needs_reply(self):
        self.card(aid="aaaaaaaaaaaa")
        _, _, _, mid2 = self.card(aid="bbbbbbbbbbbb", preview="Create repo demo")
        run(self.bot.on_text(OWNER, OWNER, "yes", "private"))
        self.assertEqual(self.hub.sent, [])
        self.assertIn("reply", self.msgr.texts()[-1].lower())
        run(self.bot.on_text(OWNER, OWNER, "yes", "private", reply_to=mid2))
        self.assertEqual(self.hub.sent[-1]["re"], "reqbbbbbbbbbbbb")

    def test_text_yes_answers(self):
        self.card()
        run(self.bot.on_text(OWNER, OWNER, "approve", "private"))
        self.assertIs(self.hub.sent[-1]["approved"], True)

    def test_unpaired_approval_denied_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub, msgr = FakeHub(), FakeMessenger()
            p = pairing.Pairing(secrets={}, state_path=Path(tmp) / "p.json")
            bot = core.BotCore(hub=hub, messenger=msgr, pairing=p)
            run(bot.on_hub_message(approval_msg()))
            self.assertIs(hub.sent[-1]["approved"], False)
            self.assertEqual(msgr.cards, [])

    def test_flat_approval_record_accepted(self):
        msg = {"id": "r1", "type": "approval_request", "action": "push", "preview": "Flat preview"}
        run(self.bot.on_hub_message(msg))
        self.assertIn("Flat preview", self.msgr.cards[-1][1])
        # Without its own id the approval is keyed by the request id.
        run(self.bot.on_callback(OWNER, OWNER, "ap:r1:y"))
        self.assertEqual(self.hub.sent[-1]["re"], "r1")

    def test_pending_command_lists(self):
        self.card()
        run(self.bot.on_command(OWNER, OWNER, "pending", "", "private"))
        self.assertIn("Push feature/x", self.msgr.texts()[-1])

    def test_preview_is_escaped_plain_text(self):
        # Cards are sent as plain text so a preview can't inject markup.
        self.card(preview="*bold* [link](http://x)")
        self.assertIn("*bold* [link](http://x)", self.msgr.cards[-1][1])

    def test_desk_standalone(self):
        desk = ApprovalDesk(FakeMessenger(), FakeHub(), clock=Clock())
        self.assertEqual(desk.pending, {})


# --------------------------------------------------------------------------
class FakeSocket:
    def __init__(self, incoming):
        self.incoming = asyncio.Queue()
        for m in incoming:
            self.incoming.put_nowait(m)
        self.outgoing: list[dict] = []
        self.closed = False
        self.on_send = None

    async def send(self, raw):
        msg = json.loads(raw)
        self.outgoing.append(msg)
        if self.on_send:
            self.on_send(msg, self)

    async def recv(self):
        item = await self.incoming.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self):
        self.closed = True


class HubClientTests(unittest.TestCase):
    def test_hello_welcome_call_and_incoming(self):
        async def scenario():
            seen = []
            sock = FakeSocket([])

            def on_send(msg, s):
                if msg["type"] == "hello":
                    s.incoming.put_nowait(json.dumps({"id": "w", "type": "welcome", "re": msg["id"]}))
                    s.incoming.put_nowait(json.dumps({"id": "n1", "type": "notify", "title": "t", "text": "x"}))
                elif msg["type"] == "request":
                    s.incoming.put_nowait(json.dumps({"id": "r", "type": "reply", "re": msg["id"], "text": "ok"}))

            sock.on_send = on_send

            async def connect(url):
                return sock

            async def on_message(msg):
                seen.append(msg)

            client = hub_client.HubClient("ws://127.0.0.1:53874/ws", token=lambda: "T", on_message=on_message,
                                          connect=connect)
            task = asyncio.create_task(client.run_forever())
            await asyncio.wait_for(client.wait_connected(), 2)
            reply = await client.call("request", text="hi", source="telegram")
            await asyncio.sleep(0.01)
            await client.stop()
            task.cancel()
            return sock, reply, seen, client

        sock, reply, seen, client = run(scenario())
        hello = sock.outgoing[0]
        self.assertEqual((hello["type"], hello["role"], hello["token"]), ("hello", "bot", "T"))
        self.assertEqual(reply["text"], "ok")
        self.assertEqual([m["type"] for m in seen], ["notify"])

    def test_call_when_disconnected(self):
        client = hub_client.HubClient("ws://x", token=lambda: "T", on_message=None)
        with self.assertRaises(hub_client.HubUnavailable):
            run(client.call("request", text="x"))

    def test_rejected_token_backs_off(self):
        async def scenario():
            attempts = []

            async def connect(url):
                attempts.append(1)
                return FakeSocket([hub_client.ConnectionClosedLike(4401)])

            client = hub_client.HubClient("ws://x", token=lambda: "bad", on_message=None, connect=connect,
                                          backoff=(0.01, 0.02))
            task = asyncio.create_task(client.run_forever())
            await asyncio.sleep(0.1)
            await client.stop()
            task.cancel()
            return attempts, client

        attempts, client = run(scenario())
        self.assertGreaterEqual(len(attempts), 2)
        self.assertFalse(client.connected)
        self.assertIn("token", client.last_error.lower())

    def test_missing_token_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(hub_client.read_token(Path(tmp) / "none.token"))
            p = Path(tmp) / "hub.token"
            p.write_text(" abc \n", encoding="utf-8")
            self.assertEqual(hub_client.read_token(p), "abc")


class PluginTests(unittest.TestCase):
    def test_dice_plugin_via_manager(self):
        from vvbot.plugin_manager import PluginManager

        pm = PluginManager({"plugins": ["dice", "not_a_plugin"]})
        self.assertEqual([s["name"] for s in pm.get_functions_specs()], ["send_dice"])
        result = json.loads(run(pm.call_function("send_dice", None, '{"emoji": "🎯"}')))
        self.assertEqual(result["direct_result"]["value"], "🎯")

    def test_run_plugin_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot, msgr, _ = make_core(tmp)
            from vvbot.plugin_manager import PluginManager

            bot.plugins = PluginManager({"plugins": ["dice"]})
            run(bot.on_command(OWNER, OWNER, "plugins", "", "private"))
            self.assertIn("send_dice", msgr.texts()[-1])


if __name__ == "__main__":
    unittest.main()
