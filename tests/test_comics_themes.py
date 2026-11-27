"""The comics themes (Classic, Classic Action, Manga Action), each with a white cover (light) and a black cover (dark).

Colours and the scene rules are checked for every theme in test_themes.py; this file checks what is special here:
the `look` a theme asks for, that both covers really are white and black, and that the action moves follow the
motion rules (nothing when motion is off or reduce-motion is on, text by textContent, at most one move a sentence)."""
import json
import re
from pathlib import Path

import pytest

from tests.test_themes import _lum, contrast

ROOT = Path(__file__).parent.parent
THEMES = ROOT / "themes"
COMICS = {"comics-classic": "classic", "comics-action": "action", "manga-action": "manga"}
LOOKS = {"comics"}
VARIANTS = {"classic", "action", "manga"}


def _theme(tid: str) -> dict:
    return json.loads((THEMES / tid / "theme.json").read_text("utf-8"))


@pytest.mark.parametrize("tid", sorted(COMICS))
def test_each_comics_theme_exists_with_its_look_and_a_scene(tid):
    t = _theme(tid)
    assert t["look"] == "comics" and t["look_variant"] == COMICS[tid]
    assert t["motion"] not in ("still", "none") and (THEMES / tid / "scene.js").exists()


@pytest.mark.parametrize("tid", sorted(COMICS))
def test_the_light_cover_is_white_and_the_dark_cover_is_black(tid):
    tokens = _theme(tid)["tokens"]
    assert _lum(tokens["light"]["bg"]) > 0.8 and _lum(tokens["light"]["panel"]) > 0.85
    assert _lum(tokens["dark"]["bg"]) < 0.01 and _lum(tokens["dark"]["panel"]) < 0.02


@pytest.mark.parametrize("tid", sorted(COMICS))
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_ink_lines_stand_out_on_both_covers(tid, mode):
    """The comics look draws panels with the `border` colour as ink: it must be clearly visible on the cover and the panel."""
    t = _theme(tid)["tokens"][mode]
    assert contrast(t["border"], t["bg"]) >= 3 and contrast(t["border"], t["panel"]) >= 3


@pytest.mark.parametrize("tid", sorted(COMICS))
def test_a_scene_started_in_a_window_with_no_size_does_not_fail(tid):
    """Found in the app: a pattern made before the window has a size threw, the scene stopped, and with it the motion.
    The patterns are made lazily on a frame, and one that cannot be made yet is skipped."""
    src = (THEMES / tid / "scene.js").read_text("utf-8")
    assert "try {" in src and "catch" in src and "??= dotPattern(" in src
    assert not re.search(r"const \w+ = dotPattern\(", src)


def test_every_look_a_theme_asks_for_is_known():
    for f in THEMES.glob("*/theme.json"):
        t = json.loads(f.read_text("utf-8"))
        assert t.get("look") in (None, *LOOKS), f.parent.name
        assert t.get("look_variant") in (None, *VARIANTS), f.parent.name
        assert ("look_variant" in t) <= ("look" in t), f.parent.name


def test_the_theme_sets_its_look_on_the_page():
    src = (ROOT / "web" / "src" / "themes.ts").read_text("utf-8")
    assert "dataset.look" in src and "lookVariant" in src
    types = (ROOT / "web" / "src" / "types.ts").read_text("utf-8")
    assert "look?:" in types and "look_variant?:" in types


def test_the_styles_draw_the_comics_look_for_each_variant():
    css = (ROOT / "web" / "static" / "styles.css").read_text("utf-8")
    assert ':root[data-look="comics"]' in css
    for v in VARIANTS:
        assert f'[data-look-variant="{v}"]' in css, v
    # the reading text keeps the reader's own font: the comics fonts are for headings and controls only
    rules = re.findall(r':root\[data-look="comics"\][^{]*\.paper[^{]*\{([^}]*)\}', css)
    assert rules and not any("--read-font" in r for r in rules)
    assert "@media (prefers-reduced-motion: reduce)" in css.split('data-look="comics"', 1)[1]


def test_the_action_moves_follow_the_motion_rules():
    src = (ROOT / "web" / "src" / "comics.ts").read_text("utf-8")
    # off with reduce-motion, Still or off: only the Gentle and Lively motion settings allow the moves
    assert "prefersReducedMotion" in src and 'ambience.intensity === "gentle" || ambience.intensity === "lively"' in src
    assert "innerHTML" not in src and "textContent" in src
    assert "MIN_GAP_MS" in src  # at most one move per sentence, and never more than one a second
    gap = int(re.search(r"MIN_GAP_MS\s*=\s*([\d_]+)", src).group(1).replace("_", ""))
    assert gap >= 1000
    # found in the app: one counter shared by the effect and the page always gave the effect the same class, so
    # its animation ran once; each element now swaps its own class
    assert 'el.classList.contains(`${base}-a`)' in src
    reader = (ROOT / "web" / "src" / "views" / "reader.ts").read_text("utf-8")
    assert "comics.step(" in reader and "comics.burst(" in reader


def test_manga_round_buttons_leave_text_blocks_alone():
    """Found on 2026-11-27: Manga Action made every button round, so the theme cards in Settings and the sections of
    the reader's map became ovals that cut into their text. Those two keep their normal shape."""
    css = (ROOT / "web" / "static" / "styles.css").read_text("utf-8")
    rule = next(line for line in css.splitlines() if 'data-look-variant="manga"] :is(button, .btn)' in line and "999px" in line)
    assert ":not(.theme-card)" in rule and ":not(.map-link)" in rule
    # the chosen theme stays marked under the comic ink (the selector must outrank the comic button rule)
    assert ':root[data-look="comics"] :is(button, .btn).theme-card.on:not(.link):not(.ghost):not(.star) {' in css
