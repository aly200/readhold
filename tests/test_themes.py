"""Every theme's text colors must pass WCAG AA (4.5:1) in light and dark."""
import json
from pathlib import Path

import pytest

THEMES = sorted((Path(__file__).parent.parent / "themes").glob("*/theme.json"))
AMBIENT_SOUNDS = {"rain", "wind-birds", "breeze", "wind", "hum", "crickets", "lofi", "waves", "shore"}
REQUIRED = {"bg", "bg2", "panel", "panel2", "border", "text", "muted", "accent", "accent_text", "pacer", "word",
            "claim", "evidence", "definition", "confusing", "idea", "sand", "sand_dark"}


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_contrast_helper():
    assert round(contrast("#000000", "#ffffff"), 1) == 21.0


@pytest.mark.parametrize("theme_file", THEMES, ids=lambda p: p.parent.name)
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_theme_contrast(theme_file, mode):
    theme = json.loads(theme_file.read_text("utf-8"))
    t = theme["tokens"][mode]
    assert REQUIRED <= set(t), f"missing tokens: {REQUIRED - set(t)}"
    pairs = [("text", "panel"), ("muted", "panel"), ("text", "panel2"), ("muted", "panel2"), ("accent", "panel"),
             ("accent_text", "accent"), ("text", "pacer"), ("text", "word"), ("text", "bg"),
             ("text", "claim"), ("text", "evidence"), ("text", "definition"), ("text", "confusing"), ("text", "idea")]
    for fg, bg in pairs:
        ratio = contrast(t[fg], t[bg])
        assert ratio >= 4.5, f"{theme_file.parent.name}/{mode}: {fg} on {bg} is {ratio:.2f}:1"


@pytest.mark.parametrize("theme_file", THEMES, ids=lambda p: p.parent.name)
def test_theme_manifest(theme_file):
    theme = json.loads(theme_file.read_text("utf-8"))
    assert theme["name"] and theme["progress"] in {"sand-jar", "bar"}
    assert theme.get("sound") in (None, "") or (theme_file.parent / theme["sound"]).exists()
    # ambient sounds are generated in web/src/sound.ts (no audio files); the name must be a known recipe
    assert theme.get("ambient_sound") in (None, *AMBIENT_SOUNDS)
    if theme.get("motion") not in ("still", "none", None):
        assert (theme_file.parent / "scene.js").exists(), "an animated theme needs a scene.js"


SCENES = sorted((Path(__file__).parent.parent / "themes").glob("*/scene.js"))


@pytest.mark.parametrize("scene", SCENES, ids=lambda p: p.parent.name)
def test_scene_rules(scene):
    """Scenes are local, self-contained modules: no network, no eval, no storage, no DOM writes."""
    src = scene.read_text("utf-8")
    assert "export default" in src
    for banned in ("fetch(", "XMLHttpRequest", "WebSocket", "eval(", "new Function", "import(", "innerHTML",
                   "localStorage", "document.", "http://", "https://"):
        assert banned not in src, f"{scene.parent.name}/scene.js uses {banned}"


def test_sound_recipes_match_front_end():
    src = (Path(__file__).parent.parent / "web" / "src" / "sound.ts").read_text("utf-8")
    for name in AMBIENT_SOUNDS:
        assert f'"{name}"' in src or f"  {name}:" in src, f"sound recipe {name} missing from sound.ts"


# ---- see-through islands: with Panels set to "See-through", an island is the panel colour at --isle-a over the scene
def _mix(top: str, under: str, a: float) -> str:
    t, u = top.lstrip("#"), under.lstrip("#")
    return "#" + "".join(f"{round(int(t[i:i + 2], 16) * a + int(u[i:i + 2], 16) * (1 - a)):02x}" for i in (0, 2, 4))


def _see_through_alpha() -> float:
    import re

    css = (Path(__file__).parent.parent / "web" / "static" / "styles.css").read_text("utf-8")
    m = re.search(r':root\[data-glass="clear"\]\s*\{[^}]*--isle-a:\s*([\d.]+)%', css)
    assert m, "the See-through setting must set --isle-a"
    return float(m.group(1)) / 100


@pytest.mark.parametrize("theme_file", THEMES, ids=lambda p: p.parent.name)
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_see_through_islands_stay_readable(theme_file, mode):
    """Text on a see-through island passes AA over every colour the theme paints behind it.
    Body text must pass even over pure white or black (a sun, a night sky)."""
    t = json.loads(theme_file.read_text("utf-8"))["tokens"][mode]
    a = _see_through_alpha()
    for back in ("bg", "bg2", "sand", "sand_dark"):
        isle = _mix(t["panel"], t[back], a)
        for fg in ("text", "muted", "accent"):
            ratio = contrast(t[fg], isle)
            assert ratio >= 4.5, f"{theme_file.parent.name}/{mode}: {fg} on a see-through island over {back} is {ratio:.2f}:1"
    for back in ("#ffffff", "#000000"):
        ratio = contrast(t["text"], _mix(t["panel"], back, a))
        assert ratio >= 4.5, f"{theme_file.parent.name}/{mode}: text on a see-through island over {back} is {ratio:.2f}:1"
