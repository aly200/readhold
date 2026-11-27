"""Hide the menu (asked for on 2026-11-26): on Study, or any page with the side menu, one button hides the menu so
the page gets the whole window, and a small Menu button brings it back. The choice is a setting (`nav_hidden`, kept
in Readhold's database like the others), so it holds after a restart. The front end has no automated tests; these
check the setting and that the pieces are wired."""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_the_setting_is_off_by_default_and_kept(client):
    assert client.get("/api/settings").json()["nav_hidden"] is False
    assert client.put("/api/settings", json={"nav_hidden": True}).json()["nav_hidden"] is True
    assert client.get("/api/settings").json()["nav_hidden"] is True


def test_the_menu_has_a_hide_button_and_a_way_back():
    src = (ROOT / "web" / "src" / "main.ts").read_text("utf-8")
    assert "nav-hide" in src and "nav-show" in src
    assert 'dataset.nav' in src and "nav_hidden" in src
    assert re.search(r'"aria-label": "Hide the menu', src) and re.search(r'"aria-label": "Show the menu', src)
    assert 'e.key === "\\\\"' in src  # Ctrl+\ hides and shows it from the keyboard


def test_the_styles_hide_it_and_give_the_page_the_room():
    css = (ROOT / "web" / "static" / "styles.css").read_text("utf-8")
    assert ':root[data-nav="hidden"] .topnav' in css
    assert ':root[data-nav="hidden"] #app:has(> .topnav)' in css  # the page takes the menu's place
    assert ".nav-show" in css and ':root[data-nav="hidden"] .nav-show' in css
