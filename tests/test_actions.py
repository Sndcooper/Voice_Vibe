"""Step specs and the executor that runs them.

The critical property is that a bad spec does nothing at all. Input sent to the
OS cannot be taken back, so a typo late in a sequence must be caught before the
first key goes out -- not after half the script has already run.

Nothing here touches the real keyboard or mouse: every executor is either a dry
run or driven through the recording fakes in stubs.
"""

from __future__ import annotations

import unittest

import stubs

stubs.install()

from voicevibe import actions  # noqa: E402
from voicevibe.actions import (  # noqa: E402
    ActionError,
    Click,
    Executor,
    Keys,
    Scroll,
    TypeText,
    parse,
)
from voicevibe.inserter import Key  # noqa: E402


def live() -> Executor:
    """An executor that 'sends' input to recording fakes, with no pacing."""
    return Executor(keyboard=stubs.FakeController(), mouse=stubs.FakeMouse(),
                    step_delay=0, type_delay=0)


class TestParsing(unittest.TestCase):
    def test_each_primitive(self) -> None:
        for spec, step in (
            ({"keys": "ctrl+t"}, Keys("ctrl+t")),
            ({"keys": " Ctrl + Shift + T "}, Keys("ctrl+shift+t")),
            ({"type_text": "hello"}, TypeText("hello")),
            ({"click": [100, 200]}, Click(100, 200)),
            ({"click": {"x": 1, "y": 2, "button": "right", "count": 2}}, Click(1, 2, "right", 2)),
            ({"scroll": ["down", 3]}, Scroll("down", 3)),
            ({"scroll": {"direction": "Left", "amount": 2}}, Scroll("left", 2)),
            ({"scroll": "up"}, Scroll("up", 1)),
        ):
            with self.subTest(spec=spec):
                self.assertEqual(parse(spec), [step])

    def test_sequences_flatten_in_order(self) -> None:
        spec = {"sequence": [
            {"keys": "ctrl+l"},
            {"sequence": [{"type_text": "example.com"}, {"keys": "enter"}]},
            {"scroll": ["down", 2]},
        ]}
        self.assertEqual(parse(spec), [
            Keys("ctrl+l"), TypeText("example.com"), Keys("enter"), Scroll("down", 2),
        ])

    def test_a_bare_list_is_a_sequence(self) -> None:
        self.assertEqual(parse([{"keys": "a"}, {"keys": "b"}]), [Keys("a"), Keys("b")])

    def test_negative_coordinates_are_other_monitors(self) -> None:
        self.assertEqual(parse({"click": [-1200, -40]}), [Click(-1200, -40)])

    def test_an_empty_sequence_does_nothing(self) -> None:
        self.assertEqual(parse({"sequence": []}), [])


class TestRejection(unittest.TestCase):
    """Malformed specs raise ActionError; they are never partly understood."""

    def test_bad_specs(self) -> None:
        for spec in (
            "ctrl+t",                               # not a step
            {},                                     # no action
            {"keys": "a", "type_text": "b"},        # two actions in one step
            {"press": "enter"},                     # unknown action
            {"keys": ""},
            {"keys": "ctrl"},                       # modifier only
            {"keys": "ctrl+foo+t"},                 # unknown key, not dropped
            {"keys": "a+b"},                        # two main keys
            {"keys": "ctrl++t"},
            {"type_text": ""},
            {"type_text": 42},
            {"click": [1]},
            {"click": [1.5, 2]},
            {"click": [True, 2]},                   # bool is not a coordinate
            {"click": {"x": 1, "y": 2, "button": "back"}},
            {"click": {"x": 1, "y": 2, "count": 4}},
            {"click": {"x": 1, "y": 2, "double": True}},
            {"scroll": ["sideways", 1]},
            {"scroll": ["down", 0]},
            {"scroll": ["down", 51]},
            {"scroll": {"direction": "down", "speed": 2}},
            {"sequence": {"keys": "a"}},            # sequence of a dict
        ):
            with self.subTest(spec=spec), self.assertRaises(ActionError):
                parse(spec)

    def test_text_length_is_capped(self) -> None:
        with self.assertRaises(ActionError):
            parse({"type_text": "x" * (actions.MAX_TEXT + 1)})

    def test_step_count_is_capped(self) -> None:
        with self.assertRaises(ActionError):
            parse([{"keys": "a"}] * (actions.MAX_STEPS + 1))

    def test_nesting_is_capped(self) -> None:
        spec: object = {"keys": "a"}
        for _ in range(actions.MAX_DEPTH + 1):
            spec = {"sequence": [spec]}
        with self.assertRaises(ActionError):
            parse(spec)

    def test_a_bad_late_step_sends_nothing(self) -> None:
        executor = live()
        with self.assertRaises(ActionError):
            executor.run([{"keys": "ctrl+a"}, {"type_text": "gone"}, {"keys": "ctrl+nope"}])
        self.assertEqual(executor.keyboard.events, [])
        self.assertEqual(executor.performed, [])


class TestDryRun(unittest.TestCase):
    def test_records_without_creating_controllers(self) -> None:
        executor = Executor(dry_run=True)
        steps = executor.run([{"click": [5, 6]}, {"type_text": "hi"}])
        self.assertEqual(steps, [Click(5, 6), TypeText("hi")])
        self.assertEqual(executor.performed, steps)
        # Nothing was reached for: no pynput controller was ever built.
        self.assertIsNone(executor._keyboard)
        self.assertIsNone(executor._mouse)

    def test_still_validates(self) -> None:
        with self.assertRaises(ActionError):
            Executor(dry_run=True).run({"click": "here"})

    def test_performed_accumulates_across_runs(self) -> None:
        executor = Executor(dry_run=True)
        executor.run({"keys": "a"})
        executor.run({"keys": "b"})
        self.assertEqual(executor.performed, [Keys("a"), Keys("b")])

    def test_descriptions_are_readable(self) -> None:
        self.assertEqual(Click(1, 2, "right", 2).describe(), "click right at (1, 2) x2")
        self.assertEqual(Scroll("down", 3).describe(), "scroll down 3")
        self.assertTrue(TypeText("x" * 100).describe().endswith("...'"))


class TestSending(unittest.TestCase):
    """What actually reaches pynput, via the recording fakes."""

    @staticmethod
    def sent(events: list) -> list:
        """Drop the stray-modifier releases each step starts with (tested below)."""
        return events[len(actions._MODIFIERS):]

    def test_combo_holds_modifiers_around_the_key(self) -> None:
        executor = live()
        executor.run({"keys": "ctrl+shift+t"})
        self.assertEqual(self.sent(executor.keyboard.events), [
            ("press", Key.ctrl), ("press", Key.shift),
            ("press", "t"), ("release", "t"),
            ("release", Key.shift), ("release", Key.ctrl),
        ])

    def test_stray_modifiers_are_released_first(self) -> None:
        # A hotkey's ctrl+alt still held would turn "t" into ctrl+alt+t.
        executor = live()
        executor.run({"keys": "t"})
        events = executor.keyboard.events
        self.assertEqual(events[:len(actions._MODIFIERS)],
                         [("release", k) for k in actions._MODIFIERS])
        self.assertEqual(events[-2:], [("press", "t"), ("release", "t")])

    def test_named_key(self) -> None:
        executor = live()
        executor.run({"keys": "enter"})
        self.assertEqual(executor.keyboard.events[-2:], [("press", Key.enter), ("release", Key.enter)])

    def test_typing_turns_newlines_into_enter(self) -> None:
        executor = live()
        executor.run({"type_text": "a\nb"})
        self.assertEqual(self.sent(executor.keyboard.events),
                         [("type", "a"), ("tap", Key.enter), ("type", "b")])

    def test_click_moves_then_clicks(self) -> None:
        executor = live()
        executor.run({"click": {"x": 300, "y": 400, "button": "right", "count": 2}})
        move, click = executor.mouse.events
        self.assertEqual(move, ("move", 300, 400))
        self.assertEqual((click[0], click[1].name, click[2]), ("click", "right", 2))

    def test_scroll_directions(self) -> None:
        for direction, expected in (
            ("up", (0, 3)), ("down", (0, -3)), ("left", (-3, 0)), ("right", (3, 0)),
        ):
            with self.subTest(direction=direction):
                executor = live()
                executor.run({"scroll": [direction, 3]})
                self.assertEqual(executor.mouse.events, [("scroll", *expected)])

    def test_sequence_runs_in_order_across_devices(self) -> None:
        executor = live()
        executor.run([{"click": [10, 20]}, {"type_text": "hi"}, {"keys": "enter"}])
        self.assertEqual(executor.mouse.events[0], ("move", 10, 20))
        typed = [e for e in executor.keyboard.events if e[0] in ("type", "press")]
        self.assertEqual(typed, [("type", "h"), ("type", "i"), ("press", Key.enter)])

    def test_modifiers_are_released_even_if_the_key_fails(self) -> None:
        class Failing(stubs.FakeController):
            def press(self, key: object) -> None:
                super().press(key)
                if key == "t":
                    raise RuntimeError("input blocked")

        executor = Executor(keyboard=Failing(), mouse=stubs.FakeMouse(), step_delay=0)
        with self.assertRaises(RuntimeError):
            executor.run({"keys": "ctrl+t"})
        self.assertEqual(executor.keyboard.events[-1], ("release", Key.ctrl))
        self.assertEqual(executor.performed, [])


if __name__ == "__main__":
    unittest.main()
