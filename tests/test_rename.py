"""Foothold became Readhold on 2026-11-26 (the owner's decision, before the first public release). Someone who used
Foothold before keeps everything: the old data folder variable still works, the old database (with its write-ahead
files) is moved to its new name the first time, old daily backups are still pruned, and an API key saved under the
old name is found and moved. Nowhere else does the old name remain."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
OLD = "foot" + "hold"  # spelled so this file does not count itself


def test_the_data_folder_variable_has_a_new_name_and_the_old_one_still_works(monkeypatch, tmp_path):
    from readhold import config

    monkeypatch.delenv("READHOLD_HOME", raising=False)
    monkeypatch.setenv(OLD.upper() + "_HOME", str(tmp_path / "old"))
    assert config.home() == tmp_path / "old"
    monkeypatch.setenv("READHOLD_HOME", str(tmp_path / "new"))
    assert config.home() == tmp_path / "new"  # the new name wins when both are set


def test_an_old_database_is_moved_to_its_new_name_once(monkeypatch, tmp_path):
    from readhold import config

    monkeypatch.setenv("READHOLD_HOME", str(tmp_path))
    data = tmp_path / "data"
    data.mkdir()
    for suffix in ("", "-wal", "-shm"):
        (data / f"{OLD}.db{suffix}").write_bytes(b"x" + suffix.encode())
    path = config.db_path()
    assert path == data / "readhold.db" and path.read_bytes() == b"x"
    assert (data / "readhold.db-wal").read_bytes() == b"x-wal" and (data / "readhold.db-shm").exists()
    assert not any((data / f"{OLD}.db{s}").exists() for s in ("", "-wal", "-shm"))
    (data / f"{OLD}.db").write_bytes(b"stale")  # both there: the new one is kept and the old one is left alone
    assert config.db_path().read_bytes() == b"x"


def test_old_daily_backups_are_still_pruned(monkeypatch, tmp_path):
    from readhold import config
    from readhold.db import open_db

    monkeypatch.setenv("READHOLD_HOME", str(tmp_path))
    db = open_db()
    backups = config.backups_dir()
    for day in range(1, 21):
        (backups / f"{OLD}-daily-2026-10-{day:02d}.db").write_bytes(b"old")
    db.daily_backup()
    left = sorted(p.name for p in backups.iterdir() if "daily" in p.name)
    assert len(left) == 14 and any(n.startswith("readhold-daily-") for n in left)


def test_a_key_saved_under_the_old_name_is_found_and_moved():
    import keyring

    from readhold.ai import keys

    keyring.set_password(OLD.capitalize(), "ai-key:anthropic", "sk-ant-old-key-1234567890")
    assert keys.get("anthropic") == "sk-ant-old-key-1234567890"
    assert keyring.get_password(keys.SERVICE, "ai-key:anthropic") == "sk-ant-old-key-1234567890"
    assert keyring.get_password(OLD.capitalize(), "ai-key:anthropic") is None  # moved, not copied


def test_the_old_name_is_left_only_where_the_migration_needs_it():
    out = subprocess.run(["git", "grep", "-l", "-i", OLD, "--", "."], cwd=ROOT, capture_output=True, text=True).stdout.split()
    allowed = {"tests/test_rename.py", "readhold/config.py", "readhold/db.py", "readhold/ai/keys.py", "readhold/ai/api.py", "docs/PHASES.md",
               "docs/CODE_GUIDE.md", "docs/code/01-backend-core-and-import.md", "docs/code/03-backend-plan-notes-search-think.md"}
    assert set(out) <= allowed, sorted(set(out) - allowed)
