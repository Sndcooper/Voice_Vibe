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
    Cancelled,
    Click,
    Confirm,
    Executor,
    Keys,
    Scroll,
    TypeText,
    parse,
    trigger_pattern,
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


class Answers:
    """A Confirmer that replies from a script and remembers what it was asked."""

    def __init__(self, *replies: object) -> None:
        self.replies = list(replies)
        self.asked: list[tuple[str, float]] = []

    def __call__(self, prompt: str, timeout: float) -> object:
        self.asked.append((prompt, timeout))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def gated(confirmer: Answers | None, **kwargs) -> Executor:  # noqa: ANN003
    return Executor(keyboard=stubs.FakeController(), mouse=stubs.FakeMouse(),
                    step_delay=0, type_delay=0, confirmer=confirmer, **kwargs)


def typed(executor: Executor) -> str:
    return "".join(e[1] for e in executor.keyboard.events if e[0] == "type")


class TestConfirmation(unittest.TestCase):
    """A gated step runs only on an explicit yes; everything else cancels."""

    SEND = [
        {"type_text": "hello"},
        {"click": [900, 40], "label": "send the message", "confirm": True},
        {"type_text": "after"},
    ]

    def test_yes_runs_the_gated_step(self) -> None:
        answers = Answers(True)
        executor = gated(answers, confirm_timeout=5)
        executor.run(self.SEND)
        self.assertEqual(answers.asked, [("send the message", 5.0)])
        self.assertEqual(executor.mouse.events[0], ("move", 900, 40))
        self.assertEqual(typed(executor), "helloafter")

    def test_no_stops_before_the_gated_step(self) -> None:
        executor = gated(Answers(False))
        with self.assertRaises(Cancelled) as caught:
            executor.run(self.SEND)
        self.assertEqual(caught.exception.prompt, "send the message")
        # The step before the gate ran; the gated one and everything after did not.
        self.assertEqual(typed(executor), "hello")
        self.assertEqual(executor.mouse.events, [])
        self.assertEqual(executor.performed, [TypeText("hello")])

    def test_anything_but_true_is_no(self) -> None:
        for reply in (None, 1, "yes", RuntimeError("mic gone")):
            with self.subTest(reply=reply):
                executor = gated(Answers(reply))
                with self.assertRaises(Cancelled), self.assertLogs("voicevibe.actions"):
                    executor.run({"keys": "enter", "confirm": True})
                self.assertEqual(executor.keyboard.events, [])

    def test_without_a_confirmer_gated_steps_never_run(self) -> None:
        executor = gated(None)
        with self.assertRaises(Cancelled):
            executor.run({"keys": "enter", "confirm": True})
        self.assertEqual(executor.keyboard.events, [])

    def test_ungated_specs_never_ask(self) -> None:
        answers = Answers()
        gated(answers).run([{"keys": "ctrl+t"}, {"type_text": "news"}, {"scroll": "down"}])
        self.assertEqual(answers.asked, [])

    def test_confirm_can_be_the_question(self) -> None:
        answers = Answers(True)
        gated(answers).run({"keys": "ctrl+enter", "confirm": "Post this comment?"})
        self.assertEqual(answers.asked[0][0], "Post this comment?")

    def test_the_prompt_falls_back_to_describing_the_step(self) -> None:
        answers = Answers(True)
        gated(answers).run({"click": [1, 2], "confirm": True})
        self.assertEqual(answers.asked[0][0], "click left at (1, 2)")

    def test_a_confirmed_sequence_asks_once_before_all_of_it(self) -> None:
        answers = Answers(True)
        spec = {"sequence": [{"keys": "ctrl+a"}, {"keys": "backspace"}], "confirm": True}
        self.assertEqual(gated(answers).plan(spec)[0], Confirm("keys ctrl+a; keys backspace"))
        executor = gated(answers)
        executor.run(spec)
        self.assertEqual(len(answers.asked), 1)

    def test_an_empty_confirmed_sequence_asks_nothing(self) -> None:
        self.assertEqual(parse({"sequence": [], "confirm": True}), [])

    def test_dry_run_records_the_gate_without_asking(self) -> None:
        answers = Answers()
        executor = Executor(dry_run=True, confirmer=answers)
        steps = executor.run({"keys": "enter", "label": "submit", "confirm": True})
        self.assertEqual(steps, [Confirm("submit"), Keys("enter")])
        self.assertEqual(answers.asked, [])

    def test_bad_options_are_rejected(self) -> None:
        for spec in (
            {"keys": "a", "confirm": "yes please", "label": 3},
            {"keys": "a", "confirm": 1},
            {"label": "just a label"},
            {"confirm": True},
        ):
            with self.subTest(spec=spec), self.assertRaises(ActionError):
                parse(spec)


class TestTriggerWords(unittest.TestCase):
    """Trigger words force a gate even when the spec did not ask for one."""

    def test_defaults(self) -> None:
        pattern = trigger_pattern(actions.DEFAULT_CONFIRM_WORDS)
        for label in ("delete the file", "Uninstall Blender", "send", "Buy now",
                      "sending it", "resend the invite", "buyer checkout"):
            with self.subTest(label=label):
                self.assertTrue(parse({"click": [1, 1], "label": label}, pattern)[0].forced_by)
        for label in ("open the file", "scroll the page", "reply", ""):
            with self.subTest(label=label):
                self.assertEqual(parse({"click": [1, 1], "label": label}, pattern), [Click(1, 1)])

    def test_label_forces_confirmation(self) -> None:
        answers = Answers(False)
        executor = gated(answers)
        with self.assertRaises(Cancelled):
            executor.run({"click": [5, 5], "label": "Buy now"})
        self.assertEqual(answers.asked[0][0], "Buy now")
        self.assertEqual(executor.mouse.events, [])

    def test_confirm_false_does_not_override_a_trigger(self) -> None:
        answers = Answers(False)
        executor = gated(answers)
        with self.assertRaises(Cancelled):
            executor.run({"click": [5, 5], "label": "delete account", "confirm": False})
        self.assertEqual(executor.mouse.events, [])

    def test_keys_can_trigger(self) -> None:
        # shift+delete skips the Recycle Bin: nobody labelled it, it still asks.
        steps = gated(Answers()).plan({"keys": "shift+delete"})
        self.assertEqual(steps, [Confirm("keys shift+delete", "delete"), Keys("shift+delete")])

    def test_typed_text_does_not_trigger(self) -> None:
        # Typing the word "send" into a document sends nothing.
        self.assertEqual(gated(Answers()).plan({"type_text": "please send the report"}),
                         [TypeText("please send the report")])

    def test_the_spoken_command_gates_the_whole_spec(self) -> None:
        answers = Answers(False)
        executor = gated(answers)
        with self.assertRaises(Cancelled):
            executor.run([{"keys": "ctrl+a"}, {"keys": "enter"}], command="send it to everyone")
        self.assertEqual(answers.asked[0][0], "send it to everyone")
        self.assertEqual(executor.keyboard.events, [])

    def test_a_confirmed_command_is_not_asked_again_inside(self) -> None:
        # "delete line" presses the delete key: one question, not two.
        answers = Answers(True)
        executor = gated(answers)
        executor.run([{"keys": "home"}, {"keys": "shift+down"}, {"keys": "delete"}],
                     command="delete line")
        self.assertEqual(answers.asked, [("delete line", 8.0)])

    def test_explicit_gates_inside_a_confirmed_command_still_ask(self) -> None:
        answers = Answers(True, True)
        executor = gated(answers)
        executor.run([{"keys": "a"}, {"keys": "enter", "confirm": "Really send?"}],
                     command="send it")
        self.assertEqual([prompt for prompt, _ in answers.asked], ["send it", "Really send?"])

    def test_adjacent_gates_become_one_question(self) -> None:
        answers = Answers(True)
        executor = gated(answers)
        executor.run({"click": [1, 1], "confirm": "Really?"}, command="send the email")
        self.assertEqual(answers.asked, [("send the email; Really?", 8.0)])

    def test_words_are_configurable(self) -> None:
        executor = gated(Answers(), confirm_words=["publish"])
        self.assertIsInstance(executor.plan({"keys": "enter", "label": "publish post"})[0], Confirm)
        self.assertEqual(executor.plan({"keys": "enter", "label": "send"}), [Keys("enter")])

    def test_an_empty_list_leaves_only_explicit_gates(self) -> None:
        executor = gated(Answers(), confirm_words=[])
        self.assertEqual(executor.plan({"keys": "shift+delete"}, command="delete"),
                         [Keys("shift+delete")])
        self.assertIsInstance(executor.plan({"keys": "enter", "confirm": True})[0], Confirm)


if __name__ == "__main__":
    unittest.main()
