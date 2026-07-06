"""State persistence + atomic write tests."""

import json
import os
from pathlib import Path

import pytest


def test_save_load_roundtrip(bgo):
    info = {"name": "demo", "pid": 1234, "command": ["echo", "hi"]}
    bgo.save_proc("demo", info)
    loaded = bgo.load_proc("demo")
    assert loaded == info


def test_save_atomic_no_tmp_left_behind(bgo):
    info = {"name": "demo", "pid": 1}
    bgo.save_proc("demo", info)
    procs = list(bgo.PROCS_DIR.iterdir())
    # exactly one file, no orphan .tmp
    assert len(procs) == 1
    assert procs[0].name == "demo.json"


def test_save_overwrite_preserves_contents(bgo):
    bgo.save_proc("demo", {"name": "demo", "pid": 1})
    bgo.save_proc("demo", {"name": "demo", "pid": 2})
    loaded = bgo.load_proc("demo")
    assert loaded["pid"] == 2


def test_load_missing_returns_none(bgo):
    assert bgo.load_proc("nonexistent") is None


def test_load_corrupt_returns_none(bgo):
    pf = bgo.proc_file("broken")
    pf.write_text("not valid json {{{")
    assert bgo.load_proc("broken") is None


def test_load_all_procs_skips_corrupt(bgo):
    bgo.save_proc("good", {"name": "good", "pid": 1})
    bgo.proc_file("bad").write_text("garbage")
    procs = bgo.load_all_procs()
    assert "good" in procs
    assert "bad" not in procs


def test_delete_proc_removes_state_and_logs(bgo):
    bgo.save_proc("demo", {"name": "demo", "pid": 1})
    bgo.log_path("demo", "out").write_text("stdout")
    bgo.log_path("demo", "err").write_text("stderr")
    bgo.watcher_log_path("demo").write_text("watcher")
    bgo.delete_proc("demo")
    assert not bgo.proc_file("demo").exists()
    assert not bgo.log_path("demo", "out").exists()
    assert not bgo.log_path("demo", "err").exists()
    assert not bgo.watcher_log_path("demo").exists()


def test_delete_proc_keep_logs(bgo):
    """delete_proc(keep_logs=True) leaves log files in place."""
    bgo.save_proc("demo", {"name": "demo", "pid": 1})
    bgo.log_path("demo", "out").write_text("stdout")
    bgo.log_path("demo", "err").write_text("stderr")
    bgo.watcher_log_path("demo").write_text("watcher")
    bgo.delete_proc("demo", keep_logs=True)
    assert not bgo.proc_file("demo").exists()
    assert bgo.log_path("demo", "out").exists()
    assert bgo.log_path("demo", "err").exists()
    assert bgo.watcher_log_path("demo").exists()


def test_watcher_log_uses_utc_iso(bgo):
    """Watcher log timestamps must carry a UTC offset for consistency."""
    bgo.watcher_log("demo", "hello")
    text = bgo.watcher_log_path("demo").read_text()
    assert text.startswith("[")
    assert "+00:00" in text or "Z" in text
    assert "hello" in text
