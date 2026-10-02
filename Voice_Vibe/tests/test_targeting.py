"""Finding things on screen by name: UIA elements, OCR boxes, numbered tags.

The critical properties: a clear match is clicked, an unclear one is asked
about (numbers), and a missing one is said out loud -- never guessed. Nothing
here touches a real window: the finder, badges, mouse and keyboard are fakes.
"""

from __future__ import annotations

import unittest

import stubs

stubs.install()

from voicevibe.actions import ActionError, ElementAction, Executor, parse  # noqa: E402
from voicevibe.control import NOT_HANDLED, Router  # noqa: E402
from voicevibe.overlay import render_badges  # noqa: E402
from voicevibe.screen import OcrLine, OcrResult, OcrWord  # noqa: E402
from voicevibe.uia import (  # noqa: E402
    Element,
    Finder,
    ambiguous,
    dedupe,
    rank,
    rank_text,
    reading_order,
    split_kind,
)

HWND = 500


class Invokable(Element):
    """An element with an Invoke pattern: clicking it needs no mouse."""

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.invoked = 0

    def invoke(self) -> bool:
        self.invoked += 1
        return True


def el(name: str, kind: str = "Button", rect=(0, 0, 40, 20)) -> Element:  # noqa: ANN001
    return Element(name, kind, rect)


def line(*words: tuple[str, tuple[int, int, int, int]]) -> OcrLine:
    return OcrLine(" ".join(w for w, _ in words), tuple(OcrWord(w, r) for w, r in words))


class FakeFinder:
    def __init__(self, elements=(), lines=()) -> None:  # noqa: ANN001
        self._elements = list(elements)
        self._lines = tuple(lines)
        self.ocr_calls = 0

    def new_command(self) -> None:
        pass

    def elements(self, hwnd: int, types=None, popups: bool = False) -> list[Element]:  # noqa: ANN001
        if types is None:
            return self._elements
        return [e for e in self._elements if e.control_type in types]

    def text(self, hwnd: int) -> OcrResult:
        self.ocr_calls += 1
        return OcrResult(self._lines)


class FakeBadges:
    def __init__(self) -> None:
        self.shown: list[list[tuple[str, tuple]]] = []
        self.cleared = 0

    def show(self, badges, seconds=None) -> None:  # noqa: ANN001
        self.shown.append(list(badges))

    def clear(self) -> None:
        self.cleared += 1


class FakeDesktop:
    def __init__(self, front: int | None = HWND, process: str = "") -> None:
        self.front = front
        self.app = process

    def foreground(self) -> int | None:
        return self.front

    def process(self, hwnd: int | None) -> str:
        return self.app


def setup(elements=(), lines=(), confirmer=None, front=HWND, **cfg):  # noqa: ANN001, ANN003, ANN201
    mouse, keyboard, badges = stubs.FakeMouse(), stubs.FakeController(), FakeBadges()
    executor = Executor(keyboard=keyboard, mouse=mouse, desktop=FakeDesktop(front),
                        confirmer=confirmer, step_delay=0)
    router = Router({"enabled": True, **cfg}, executor=executor,
                    finder=FakeFinder(elements, lines), badges=badges)
    return router, mouse, badges


def clicks(mouse: stubs.FakeMouse) -> list[tuple]:
    """(x, y, button, count) for each click, from move+click event pairs."""
    out, at = [], None
    for event in mouse.events:
        if event[0] == "move":
            at = event[1:]
        elif event[0] == "click":
            out.append((*at, event[1].name, event[2]))
    return out


# ------------------------------------------------------------------ matching
class TestMatching(unittest.TestCase):
    def test_split_kind(self) -> None:
        for said, expected in (
            ("save", ("save", None)),
            ("the save button", ("save", "Button")),
            ("downloads link", ("downloads", "Hyperlink")),
            ("remember me check box", ("remember me", "CheckBox")),
            ("button", ("button", None)),  # a thing may be called "button"
        ):
            with self.subTest(said=said):
                self.assertEqual(split_kind(said), expected)

    def test_rank_prefers_exact_then_contained(self) -> None:
        save, save_as, saved = el("Save"), el("Save As..."), el("Saved searches")
        self.assertEqual(rank("save", [save_as, saved, save])[:2], [save, save_as])

    def test_rank_finds_plurals_and_casing(self) -> None:
        downloads = el("Downloads", "ListItem")
        self.assertEqual(rank("download", [el("Documents"), downloads]), [downloads])
        self.assertEqual(rank("SIGN IN", [el("Sign in")])[0].name, "Sign in")

    def test_kind_breaks_a_tie(self) -> None:
        item, button = el("Save", "MenuItem"), el("Save", "Button")
        self.assertIs(rank("the save button", [item, button])[0], button)

    def test_nothing_close_is_empty(self) -> None:
        self.assertEqual(rank("photoshop", [el("Photos"), el("Settings")]), [])

    def test_ambiguity(self) -> None:
        a, b = el("Reply", rect=(0, 0, 10, 10)), el("Reply", rect=(0, 50, 10, 60))
        self.assertTrue(ambiguous("reply", [a, b]))
        self.assertFalse(ambiguous("reply", [a, el("Reply all")]))
        self.assertFalse(ambiguous("reply", [a]))
        self.assertFalse(ambiguous("reply", [a, el("Reply", "MenuItem")]))

    def test_dedupe_keeps_the_button_inside_a_list_item(self) -> None:
        item = el("Inbox", "ListItem", (0, 0, 200, 30))
        button = el("Inbox", "Button", (2, 1, 198, 29))
        other = el("Sent", "ListItem", (0, 40, 200, 70))
        self.assertEqual(dedupe([item, button, other]), [button, other])

    def test_reading_order(self) -> None:
        a, b, c = el("a", rect=(300, 10, 320, 30)), el("b", rect=(10, 12, 30, 30)), el("c", rect=(10, 90, 30, 110))
        self.assertEqual(reading_order([c, a, b]), [b, a, c])


class TestOcrBoxes(unittest.TestCase):
    LINES = (
        line(("Welcome", (10, 10, 80, 24)), ("back", (84, 10, 120, 24))),
        line(("Sign", (10, 40, 40, 54)), ("in", (44, 40, 56, 54)), ("here", (60, 40, 90, 54))),
    )

    def test_multi_word_targets_get_one_box(self) -> None:
        best = rank_text("sign in", self.LINES)[0]
        self.assertEqual((best.name, best.rect), ("Sign in", (10, 40, 56, 54)))
        self.assertEqual(best.source, "ocr")

    def test_ocr_misreads_still_match(self) -> None:
        misread = (line(("Sign", (10, 40, 40, 54)), ("ln", (44, 40, 56, 54))),)
        self.assertEqual(rank_text("sign in", misread)[0].name, "Sign ln")

    def test_the_shortest_run_wins_a_tie(self) -> None:
        self.assertEqual(rank_text("welcome", self.LINES)[0].name, "Welcome")

    def test_no_match(self) -> None:
        self.assertEqual(rank_text("checkout", self.LINES), [])

    def test_result_text_and_shift(self) -> None:
        result = OcrResult(self.LINES)
        self.assertEqual(result.text, "Welcome back\nSign in here")
        moved = result.shifted(100, 200)
        self.assertEqual(moved.lines[1].words[1].rect, (144, 240, 156, 254))
        self.assertEqual(moved.lines[1].rect, (110, 240, 190, 254))


class TestFinderCache(unittest.TestCase):
    def test_one_walk_per_window_per_command(self) -> None:
        finder = Finder()
        calls: list[int] = []
        finder._query = lambda hwnd, types, popups=False: calls.append(hwnd) or [el(str(len(calls)))]
        first = finder.elements(1)
        self.assertIs(finder.elements(1), first)          # same command: cached
        finder.elements(2)                                # another window: walked
        finder.new_command()
        self.assertIsNot(finder.elements(1), first)       # next command: fresh
        self.assertEqual(calls, [1, 2, 1])

    def test_types_are_cached_separately(self) -> None:
        finder = Finder()
        calls: list[tuple] = []
        finder._query = lambda hwnd, types, popups=False: calls.append(types) or []
        finder.elements(1)
        finder.elements(1, ("Hyperlink",))
        self.assertEqual(len(calls), 2)


# ------------------------------------------------------------------ clicking
class TestClickByName(unittest.TestCase):
    def test_click_uses_the_pattern_when_there_is_one(self) -> None:
        save = Invokable("Save", "Button", (100, 100, 140, 120))
        router, mouse, _ = setup([save])
        self.assertTrue(router.route("click save").handled)
        self.assertEqual(save.invoked, 1)
        self.assertEqual(mouse.events, [])  # the pointer never moved

    def test_click_falls_back_to_the_mouse(self) -> None:
        router, mouse, _ = setup([el("Save", rect=(100, 100, 140, 120))])
        router.route("click on the save")
        self.assertEqual(clicks(mouse), [(120, 110, "left", 1)])

    def test_other_verbs_always_use_the_mouse(self) -> None:
        for said, expected in (
            ("double click save", [(120, 110, "left", 2)]),
            ("double-click save", [(120, 110, "left", 2)]),
            ("right click save", [(120, 110, "right", 1)]),
        ):
            with self.subTest(said=said):
                save = Invokable("Save", "Button", (100, 100, 140, 120))
                router, mouse, _ = setup([save])
                router.route(said)
                self.assertEqual(clicks(mouse), expected)
                self.assertEqual(save.invoked, 0)

    def test_hover_only_moves(self) -> None:
        router, mouse, _ = setup([el("Profile", rect=(0, 0, 20, 20))])
        router.route("hover over profile")
        self.assertEqual(mouse.events, [("move", 10, 10)])

    def test_ocr_when_uia_has_nothing(self) -> None:
        lines = (line(("Sign", (10, 40, 40, 54)), ("in", (44, 40, 56, 54))),)
        router, mouse, _ = setup([el("Menu")], lines)
        router.route("click sign in")
        self.assertEqual(clicks(mouse), [(33, 47, "left", 1)])

    def test_uia_match_skips_ocr(self) -> None:
        router, _, _ = setup([el("Sign in")])
        router.route("click sign in")
        self.assertEqual(router.finder.ocr_calls, 0)

    def test_not_found_is_said_not_guessed(self) -> None:
        router, mouse, _ = setup([el("Settings")])
        route = router.route("click checkout")
        self.assertEqual(route.speak, "I can't find checkout.")
        self.assertEqual(mouse.events, [])

    def test_no_window_in_front(self) -> None:
        router, _, _ = setup([el("Save")], front=None)
        self.assertIn("no window", router.route("click save").speak)

    def test_trigger_words_apply_to_what_is_clicked(self) -> None:
        # "Send" is a trigger word: the click waits for a yes.
        asked: list[str] = []
        router, mouse, _ = setup([el("Send", rect=(0, 0, 20, 20))],
                                 confirmer=lambda prompt, t: asked.append(prompt) or False)
        route = router.route("click send")
        self.assertEqual(route.caption, "Cancelled")
        self.assertEqual(asked, ["click send"])
        self.assertEqual(mouse.events, [])


class TestNextOne(unittest.TestCase):
    ELEMENTS = [el("Reply all", rect=(0, 0, 20, 20)), el("Reply", rect=(0, 50, 20, 70)),
                el("Replay", rect=(0, 90, 20, 110))]

    def test_next_one_walks_the_other_matches(self) -> None:
        router, mouse, _ = setup(self.ELEMENTS)
        router.route("click reply")                  # exact "Reply" first
        router.route("next one")                     # then "Reply all"
        router.route("no, the next one")             # then "Replay"
        route = router.route("next one")             # then nothing
        self.assertEqual([c[:2] for c in clicks(mouse)], [(10, 60), (10, 10), (10, 100)])
        self.assertIn("no other match", route.speak)

    def test_the_verb_carries_over(self) -> None:
        router, mouse, _ = setup(self.ELEMENTS)
        router.route("right click reply")
        router.route("next one")
        self.assertEqual([c[2] for c in clicks(mouse)], ["right", "right"])

    def test_another_command_forgets_the_matches(self) -> None:
        router, _, _ = setup(self.ELEMENTS)
        router.route("click reply")
        router.route("scroll down")
        self.assertIn("no other match", router.route("next one").speak)


class TestNumbers(unittest.TestCase):
    ELEMENTS = [
        el("Home", "Hyperlink", (10, 10, 60, 30)),
        el("Save", "Button", (200, 10, 240, 30)),
        el("News", "Hyperlink", (10, 100, 60, 120)),
        el("Close", "Button", (300, 100, 340, 120)),
    ]

    def test_show_numbers_tags_everything_in_reading_order(self) -> None:
        router, _, badges = setup(self.ELEMENTS)
        route = router.route("show numbers")
        self.assertIn("4 numbers", route.caption)
        self.assertEqual(badges.shown[-1], [
            ("1", (10, 10, 60, 30)), ("2", (200, 10, 240, 30)),
            ("3", (10, 100, 60, 120)), ("4", (300, 100, 340, 120)),
        ])

    def test_pick_by_number(self) -> None:
        for said, expected in (
            ("click 3", [(35, 110, "left", 1)]),
            ("3", [(35, 110, "left", 1)]),
            ("number three", [(35, 110, "left", 1)]),
            ("right click 2", [(220, 20, "right", 1)]),
            ("double click on number 4", [(320, 110, "left", 2)]),
        ):
            with self.subTest(said=said):
                router, mouse, badges = setup(self.ELEMENTS)
                router.route("show numbers")
                router.route(said)
                self.assertEqual(clicks(mouse), expected)
                self.assertEqual(badges.cleared, 1)

    def test_a_bad_number_keeps_the_tags(self) -> None:
        router, mouse, badges = setup(self.ELEMENTS)
        router.route("show numbers")
        self.assertEqual(router.route("click 9").speak, "There's no number 9.")
        self.assertEqual(badges.cleared, 0)
        router.route("click 1")
        self.assertEqual(len(clicks(mouse)), 1)

    def test_the_next_command_takes_the_tags_away(self) -> None:
        router, mouse, badges = setup(self.ELEMENTS)
        router.route("show numbers")
        router.route("scroll down")
        self.assertEqual(badges.cleared, 1)
        # Numbers are names again: nothing is called "3".
        self.assertEqual(router.route("click 3").speak, "I can't find 3.")

    def test_tags_expire(self) -> None:
        router, _, _ = setup(self.ELEMENTS, badge_seconds=0)
        router.route("show numbers")
        self.assertEqual(router.route("click 1").speak, "I can't find 1.")

    def test_hide_numbers(self) -> None:
        router, _, badges = setup(self.ELEMENTS)
        router.route("show numbers")
        self.assertTrue(router.route("hide numbers").handled)
        self.assertEqual(badges.cleared, 1)

    def test_show_links_is_links_only(self) -> None:
        router, mouse, badges = setup(self.ELEMENTS)
        route = router.route("show links")
        self.assertIn("2 links", route.caption)
        self.assertEqual([label for label, _ in badges.shown[-1]], ["1", "2"])
        router.route("click 2")
        self.assertEqual(clicks(mouse), [(35, 110, "left", 1)])  # News, not Save

    def test_nothing_clickable(self) -> None:
        router, _, badges = setup([])
        self.assertIn("anything clickable", router.route("show numbers").speak)
        self.assertIn("links", router.route("show links").speak)
        self.assertEqual(badges.shown, [])

    def test_ambiguous_click_asks_with_numbers(self) -> None:
        elements = [el("Reply", rect=(0, 0, 20, 20)), el("Reply", rect=(0, 60, 20, 80)),
                    el("Forward", rect=(50, 0, 70, 20))]
        router, mouse, badges = setup(elements)
        route = router.route("click reply")
        self.assertEqual(route.speak, "Which one?")
        self.assertEqual(mouse.events, [])  # nothing clicked on a coin toss
        self.assertEqual([r for _, r in badges.shown[-1]], [(0, 0, 20, 20), (0, 60, 20, 80)])
        router.route("2")
        self.assertEqual(clicks(mouse), [(10, 70, "left", 1)])

    def test_an_ambiguous_right_click_keeps_its_verb(self) -> None:
        elements = [el("Reply", rect=(0, 0, 20, 20)), el("Reply", rect=(0, 60, 20, 80))]
        router, mouse, _ = setup(elements)
        router.route("right click reply")
        router.route("1")
        self.assertEqual(clicks(mouse), [(10, 10, "right", 1)])

    def test_a_bare_number_is_not_a_command_without_tags(self) -> None:
        router, _, _ = setup(self.ELEMENTS)
        self.assertEqual(router.route("3"), NOT_HANDLED)


class TestElementStep(unittest.TestCase):
    def test_validation(self) -> None:
        for spec in (
            {"element": "save"},
            {"element": {"action": "click"}},
            {"element": {"target": "not an element"}},
            {"element": {"target": el("x"), "action": "triple_click"}},
            {"element": {"target": el("x"), "where": 1}},
        ):
            with self.subTest(spec=spec), self.assertRaises(ActionError):
                parse(spec)

    def test_dry_run_describes_it(self) -> None:
        step = parse({"element": {"target": el("Save"), "action": "right_click"}})[0]
        self.assertIsInstance(step, ElementAction)
        self.assertEqual(step.describe(), "right click Save button")
        self.assertEqual(Element("Sign in", "Text", (0, 0, 1, 1), source="ocr").describe(),
                         "Sign in text")


class TestBadgeRendering(unittest.TestCase):
    def test_nothing_to_draw(self) -> None:
        self.assertIsNone(render_badges([]))

    def test_image_covers_just_the_tags(self) -> None:
        image, origin = render_badges([("1", (100, 200, 150, 220)), ("12", (400, 500, 450, 520))])
        self.assertEqual(origin, (98, 198))  # tags sit just inside each element's corner
        self.assertGreater(image.width, 400 - 100)
        self.assertLess(image.width, 400)
        # Transparent between tags, opaque on them.
        self.assertEqual(image.getpixel((image.width // 2, image.height // 2))[3], 0)
        self.assertGreater(image.getpixel((4, 4))[3], 200)


if __name__ == "__main__":
    unittest.main()
