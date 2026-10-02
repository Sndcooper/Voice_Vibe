"""2-day retention and "computer save this conversation" (rule 15).

Temp directories only; nothing touches %LOCALAPPDATA%.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import stubs

stubs.install()

from voicevibe.history import History, is_save_command  # noqa: E402
from vvhub import dispatch  # noqa: E402
from vvhub.bus import Bus  # noqa: E402
from vvhub.skills.conversation import SKILL as CONVERSATION  # noqa: E402
from vvhub.store import RETENTION_SECONDS, Store, today_conversation  # noqa: E402

DAY = 86400


def _age(path: Path, days: float) -> None:
    stamp = time.time() - days * DAY
    os.utime(path, (stamp, stamp))


class HistoryRetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_default_keeps_two_days(self) -> None:
        self.assertEqual(History(directory=self.dir).keep_days, 2)

    def test_prune_boundaries_and_saved_is_exempt(self) -> None:
        fresh, edge, old = (self.dir / f"{n}.jsonl" for n in ("fresh", "edge", "old"))
        for path in (fresh, edge, old):
            path.write_text("{}\n", encoding="utf-8")
        _age(fresh, 0.5)
        _age(edge, 1.9)
        _age(old, 2.1)
        saved = self.dir / "saved"
        saved.mkdir()
        ancient = saved / "2020-01-01.jsonl"
        ancient.write_text("{}\n", encoding="utf-8")
        _age(ancient, 900)

        History(directory=self.dir)

        self.assertTrue(fresh.exists())
        self.assertTrue(edge.exists())
        self.assertFalse(old.exists())
        self.assertTrue(ancient.exists())

    def test_zero_keeps_everything(self) -> None:
        old = self.dir / "old.jsonl"
        old.write_text("{}\n", encoding="utf-8")
        _age(old, 400)
        History(keep_days=0, directory=self.dir)
        self.assertTrue(old.exists())

    def test_save_copies_kept_days_without_duplicates(self) -> None:
        history = History(directory=self.dir)
        history.add(action="dictate", heard="first")
        history.add(action="dictate", heard="second")
        self.assertEqual(history.save(), 2)
        history.add(action="dictate", heard="third")
        self.assertEqual(history.save(), 3)  # re-save merges, no duplicates

        files = list(history.saved_directory.glob("*.jsonl"))
        self.assertEqual(len(files), 1)
        heard = [json.loads(line)["heard"]
                 for line in files[0].read_text(encoding="utf-8").splitlines()]
        self.assertEqual(heard, ["first", "second", "third"])

        # Saved survives even after the kept file ages out.
        for day in self.dir.glob("*.jsonl"):
            _age(day, 5)
        History(directory=self.dir)
        self.assertEqual(list(self.dir.glob("*.jsonl")), [])
        self.assertTrue(files[0].exists())

    def test_save_when_disabled_is_a_no_op(self) -> None:
        self.assertEqual(History(enabled=False, directory=self.dir).save(), 0)


class SavePhraseTests(unittest.TestCase):
    def test_matches(self) -> None:
        for said in ("save this conversation", "Save the conversation.",
                     "save conversation", "keep this conversation!"):
            self.assertTrue(is_save_command(said), said)

    def test_dictation_is_not_swallowed(self) -> None:
        for said in ("save", "save it", "save this conversation for later reading",
                     "we should save this conversation", ""):
            self.assertFalse(is_save_command(said), said)


class StoreRetentionTests(unittest.TestCase):
    def test_purge_keeps_recent_and_saved(self) -> None:
        store = Store()
        now = time.time()
        old = now - RETENTION_SECONDS - 60
        store.add_turn("user", "old unsaved", conversation="old", ts=old)
        store.add_turn("user", "old saved", conversation="kept", ts=old)
        store.save_conversation("kept")
        store.add_turn("user", "recent", conversation="new", ts=now - 60)
        store.add_decision("old", {"category": "app"}, conversation="old", ts=old)
        store.add_approval({"id": "a1", "action": "post", "created": old, "status": "denied"},
                           conversation="old")
        store.add_approval({"id": "a2", "action": "post", "created": old, "status": "pending"},
                           conversation="old")

        counts = store.purge(now)

        self.assertEqual(store.turns("old"), [])
        self.assertEqual([t["text"] for t in store.turns("kept")], ["old saved"])
        self.assertEqual([t["text"] for t in store.turns("new")], ["recent"])
        self.assertEqual(counts["turns"], 1)
        self.assertEqual(counts["decisions"], 1)
        # A pending approval is never silently dropped.
        self.assertEqual([a["id"] for a in store.approvals()], ["a2"])

    def test_watch_items_dedupe_and_outlive_conversations(self) -> None:
        store = Store()
        self.assertTrue(store.add_watch_item("github", "pr", "pr:1", title="Fix"))
        self.assertFalse(store.add_watch_item("github", "pr", "pr:1", title="Fix"))
        store.purge(time.time() + 3 * DAY)
        self.assertEqual(len(store.list_watch_items()), 1)


class _Hub:
    def __init__(self) -> None:
        self.store = Store()
        self.bus = Bus()
        self.skills = {"conversation": CONVERSATION}
        CONVERSATION.bind(self)


class HubSaveSkillTests(unittest.TestCase):
    def test_phrase_saves_every_kept_day(self) -> None:
        hub = _Hub()
        result = asyncio.run(dispatch.handle(hub, "Save this conversation."))
        self.assertTrue(result.ok)
        self.assertEqual(result.text, "Conversation saved.")
        self.assertTrue(hub.store.is_saved(today_conversation()))
        self.assertTrue(hub.store.is_saved(today_conversation(time.time() - DAY)))


class AppSaveTests(unittest.TestCase):
    def make(self):  # noqa: ANN201
        from types import SimpleNamespace
        from unittest.mock import Mock

        from voicevibe import app
        from voicevibe.control import Router

        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.config = SimpleNamespace(output={}, control={}, feedback={}, wake={})
        vv._last_inserted = "x"
        vv._ends_dictation = False
        vv.executor = app.Executor(keyboard=stubs.FakeController(),
            desktop=SimpleNamespace(foreground=lambda: 1, process=lambda hwnd: "test.exe"),
            confirmer=Mock(return_value=True))
        vv.router = Router({"enabled": True}, executor=vv.executor, finder=Mock(), profiles={})
        vv.router._front = lambda: 1
        vv.history = Mock()
        vv.history.save.return_value = 4
        vv.hub = Mock()
        vv.overlay, vv.airoot, vv.beeper, vv.voice = Mock(), Mock(), Mock(), Mock()
        vv._do_insert = Mock()
        return vv

    def test_save_phrase_saves_instead_of_ctrl_s(self) -> None:
        vv = self.make()
        vv._do_command_or_insert("computer save this conversation", 0.1)
        vv.history.save.assert_called_once()
        vv.hub.request_async.assert_called_once_with("save this conversation")
        vv.voice.say.assert_called_once_with("Conversation saved.")
        self.assertEqual(vv.executor.keyboard.events, [])  # no Ctrl+S
        vv._do_insert.assert_not_called()

    def test_plain_save_still_presses_ctrl_s(self) -> None:
        vv = self.make()
        vv._do_command_or_insert("computer save", 0.1)
        vv.history.save.assert_not_called()
        self.assertTrue(vv.executor.keyboard.events)


if __name__ == "__main__":
    unittest.main()
