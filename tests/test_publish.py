"""Ready to publish (2026-11-26): the licence, the notices for what the front end bundles, and CI actions pinned to
commit SHAs. These keep it so as files change."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_the_code_is_under_the_mit_license():
    text = (ROOT / "LICENSE").read_text("utf-8")
    assert text.startswith("MIT License") and "Permission is hereby granted, free of charge" in text
    assert json.loads((ROOT / "web" / "package.json").read_text("utf-8"))["license"] == "MIT"


def test_every_bundled_font_and_katex_has_its_notice():
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text("utf-8")
    copied = (ROOT / "web" / "scripts" / "copy-fonts.mjs").read_text("utf-8")
    for pkg in re.findall(r'\["([a-z-]+)", "[^"]+", \[', copied):  # each font the build copies into static/fonts
        assert f"`@fontsource/{pkg}`" in notices, pkg
    assert "SIL OPEN FONT LICENSE Version 1.1" in notices and "PERMISSION & CONDITIONS" in notices
    assert "## KaTeX (MIT License)" in notices and "Khan Academy" in notices


def test_every_ci_action_is_pinned_to_a_commit_sha_with_its_tag():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8")
    uses = re.findall(r"uses:\s*(\S+)(.*)", ci)
    assert uses
    for action, rest in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", action), action
        assert re.fullmatch(r"\s*# v\d+\.\d+\.\d+", rest), f"{action}: name the release tag in a comment"


def test_a_newcomer_finds_the_quick_start_and_the_ai_setup_steps():
    """Added on 2026-11-26: a short tour (docs/QUICKSTART.md) linked from the README and the guide, and the same
    five-minute AI setup in the quick start, the README, the guide and Settings → AI."""
    readme = (ROOT / "README.md").read_text("utf-8")
    guide = (ROOT / "docs" / "GUIDE.md").read_text("utf-8")
    quick = (ROOT / "docs" / "QUICKSTART.md").read_text("utf-8")
    assert "docs/QUICKSTART.md" in readme and "(QUICKSTART.md)" in guide and "(GUIDE.md)" in quick
    for text in (readme, guide, quick):
        assert "ollama pull llama3.2" in text and "Test connection" in text
    settings = (ROOT / "web" / "src" / "views" / "ai-settings.ts").read_text("utf-8")
    assert "New to AI?" in settings and "ollama pull llama3.2" in settings



def test_no_automatic_update_pull_requests():
    """Asked for on 2026-11-27: Readhold is a finished portfolio project, so no bot opens update pull requests; the
    versions stay as locked (uv.lock, web/package-lock.json), the ones the tests passed with."""
    assert not (ROOT / ".github" / "dependabot.yml").exists()
    assert (ROOT / "uv.lock").exists() and (ROOT / "web" / "package-lock.json").exists()


def test_no_security_policy_promising_upkeep():
    """Asked for on 2026-11-27: SECURITY.md promised a first answer within 7 days and fixes, which a portfolio project
    that may not be updated can't keep, so it was removed; the threat model stays in docs/ai/PLAN.md."""
    assert not (ROOT / "SECURITY.md").exists()
    assert "SECURITY.md" not in (ROOT / "README.md").read_text("utf-8")
