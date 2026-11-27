"""Fold the reader's side panels (asked for on 2026-11-27): one button in the reader's top bar, or Ctrl+\\, folds away
the document map and the Questions/Notes panel, so the page sits alone in the middle and the theme's scene shows
on both sides. The reading page itself stays solid. The choice is a setting (`reader_panels_hidden`), so it holds
after a restart. The front end has no automated tests; these check the setting and that the pieces are wired."""
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_the_setting_is_off_by_default_and_kept(client):
    assert client.get("/api/settings").json()["reader_panels_hidden"] is False
    assert client.put("/api/settings", json={"reader_panels_hidden": True}).json()["reader_panels_hidden"] is True
    assert client.get("/api/settings").json()["reader_panels_hidden"] is True


def test_the_reader_has_a_fold_button_and_shortcut():
    src = (ROOT / "web" / "src" / "views" / "reader.ts").read_text("utf-8")
    assert "setPanelsHidden" in src and "reader_panels_hidden" in src
    assert "panels-hidden" in src  # the class on .reader that the styles use
    assert '"aria-label": this.panelsHidden ? "Show the side panels' in src
    assert 'e.key === "\\\\"' in src  # Ctrl+\ folds and unfolds them from the keyboard
    help_src = (ROOT / "web" / "src" / "views" / "reader-dialogs.ts").read_text("utf-8")
    assert '"Ctrl+\\\\"' in help_src  # listed in the Keys box


def test_the_styles_fold_both_panels_and_centre_the_page():
    css = (ROOT / "web" / "static" / "styles.css").read_text("utf-8")
    assert ".reader.panels-hidden .map" in css and ".reader.panels-hidden .side" in css
    assert ".reader.panels-hidden .reader-body" in css


def test_the_types_know_the_setting():
    assert "reader_panels_hidden" in (ROOT / "web" / "src" / "types.ts").read_text("utf-8")
