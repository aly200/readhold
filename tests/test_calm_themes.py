"""Clean, Meadow and Orbit (2026-11-26, chosen from a design canvas): a modern minimalist, a nature and a universe
theme, each comfortable in light and dark. Colour contrast and the scene rules are checked for every theme in
test_themes.py; this file checks what these three promise: both modes, no pure white or black panel, text that is
clear but not stark, and scenes that draw their progress and stay still when motion is off."""
import json
from pathlib import Path

import pytest

from tests.test_themes import _lum, contrast

THEMES = Path(__file__).parent.parent / "themes"
CALM = ("clean", "meadow", "orbit")


def _t(tid):
    return json.loads((THEMES / tid / "theme.json").read_text("utf-8"))


@pytest.mark.parametrize("tid", CALM)
def test_each_exists_with_a_scene_and_both_modes(tid):
    t = _t(tid)
    assert t["name"] and t["motion"] == "gentle" and (THEMES / tid / "scene.js").exists()
    assert _lum(t["tokens"]["light"]["bg"]) > 0.6 > 0.05 > _lum(t["tokens"]["dark"]["bg"])  # a real light and a real dark


@pytest.mark.parametrize("tid", CALM)
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_comfortable_on_the_eyes(tid, mode):
    """No glaring white or pure black page, and body text clear (7:1 or more) without being stark (16:1 or less)."""
    t = _t(tid)["tokens"][mode]
    assert t["panel"].lower() not in ("#ffffff", "#000000") and t["bg"].lower() not in ("#ffffff", "#000000")
    assert 7 <= contrast(t["text"], t["panel"]) <= 16, contrast(t["text"], t["panel"])


@pytest.mark.parametrize("tid", CALM)
def test_the_scene_draws_progress_and_respects_still(tid):
    src = (THEMES / tid / "scene.js").read_text("utf-8")
    assert "state.progress" in src and "state.still" in src and "export default" in src


def test_clean_is_the_default_theme():
    """Clean is what a new install starts with (Sand was until 2026-11-27), and the front end falls back to it."""
    from readhold.server import DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["theme"] == "clean" and (THEMES / "clean" / "theme.json").exists()
    src = (THEMES.parent / "web" / "src" / "themes.ts").read_text("utf-8")
    assert 'find("clean")' in src
