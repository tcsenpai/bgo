"""Terminal-capability detection + table rendering smoke tests."""

import argparse
import os
import sys


def test_level_forced_plain(bgo):
    assert bgo._detect_table_level("plain") == bgo.LEVEL_PLAIN


def test_level_forced_fancy(bgo):
    assert bgo._detect_table_level("fancy") == bgo.LEVEL_FANCY


def test_level_forced_normal(bgo):
    assert bgo._detect_table_level("normal") == bgo.LEVEL_NORMAL


def test_level_env_override(bgo, monkeypatch):
    monkeypatch.setenv("BGO_TABLE", "plain")
    assert bgo._detect_table_level() == bgo.LEVEL_PLAIN


def test_level_env_override_invalid_ignored(bgo, monkeypatch):
    """Invalid BGO_TABLE values fall through to auto-detection."""
    monkeypatch.setenv("BGO_TABLE", "bogus")
    # Stdout in pytest is not a TTY -> plain
    assert bgo._detect_table_level() == bgo.LEVEL_PLAIN


def test_level_non_tty_is_plain(bgo, monkeypatch):
    """pytest captures stdout -> isatty is False -> plain."""
    monkeypatch.delenv("BGO_TABLE", raising=False)
    assert bgo._detect_table_level() == bgo.LEVEL_PLAIN


def test_level_dumb_term_is_plain(bgo, monkeypatch):
    monkeypatch.delenv("BGO_TABLE", raising=False)
    monkeypatch.setenv("TERM", "dumb")
    assert bgo._detect_table_level() == bgo.LEVEL_PLAIN


def test_glyphs_keys_consistent_across_levels(bgo):
    """All levels must expose the same keys so callers don't branch."""
    plain_keys = set(bgo.GLYPHS[bgo.LEVEL_PLAIN].keys())
    normal_keys = set(bgo.GLYPHS[bgo.LEVEL_NORMAL].keys())
    fancy_keys = set(bgo.GLYPHS[bgo.LEVEL_FANCY].keys())
    assert plain_keys == normal_keys == fancy_keys


def test_glyphs_plain_is_ascii_only(bgo):
    """Plain level must contain no codepoints above ASCII."""
    for v in bgo.GLYPHS[bgo.LEVEL_PLAIN].values():
        for ch in v:
            assert ord(ch) < 128, f"non-ASCII in plain glyph: {v!r}"


def test_visible_width_strips_ansi(bgo):
    assert bgo._visible_width("\033[31mhello\033[0m") == 5


def test_pad_left_align(bgo):
    assert bgo._pad("ab", 5) == "ab   "


def test_pad_right_align(bgo):
    assert bgo._pad("ab", 5, align="right") == "   ab"


def test_pad_ansi_safe(bgo):
    """Padding must account for invisible ANSI codes."""
    colored = "\033[31mab\033[0m"
    padded = bgo._pad(colored, 5)
    # Visible width should be 5
    assert bgo._visible_width(padded) == 5


def test_watch_cell_uses_level_glyph(bgo):
    """Plain watch cell should use ASCII glyphs for the watching state."""
    # Use the current pid so is_running() returns True (avoids "dead" branch)
    info = {"watch": {"enabled": True, "restarts": 3,
                       "watcher_pid": os.getpid(), "errored": False}}
    cell = bgo._watch_cell(info, level=bgo.LEVEL_PLAIN)
    assert "[W]" in cell
    assert "3" in cell


def test_watch_cell_none_uses_dash(bgo):
    """No watch config -> plain '-' or fancy '·'."""
    info = {"watch": None}
    assert bgo._watch_cell(info, level=bgo.LEVEL_PLAIN) == "-"
    assert bgo._watch_cell(info, level=bgo.LEVEL_FANCY) == "·"


def test_watch_cell_errored(bgo):
    """Errored state shows the errored glyph + label."""
    info = {"watch": {"enabled": True, "errored": True, "restarts": 5,
                       "watcher_pid": os.getpid()}}
    cell = bgo._watch_cell(info, level=bgo.LEVEL_PLAIN)
    assert "[!]" in cell
    assert "errored" in cell


def test_print_status_table_plain_smoke(bgo, capsys):
    """Smoke: plain rendering writes ASCII-only output."""
    rows = [{
        "name": "proc1", "pid": 1234, "status": "online",
        "cpu": "0.1", "mem": "0.2", "uptime": "01:23",
        "command": ["echo", "hi"], "cwd": "/", "started_at": "now",
        "watch": None,
    }]
    bgo._print_status_table(rows, level=bgo.LEVEL_PLAIN)
    out = capsys.readouterr().out
    assert "NAME" in out
    assert "proc1" in out
    assert "ON" in out  # plain online glyph
    # No non-ASCII (excluding any ANSI codes that might leak — but
    # color() is TTY-gated and capsys hides isatty=False)
    for ch in out:
        assert ord(ch) < 128, f"non-ASCII char in plain output: {ch!r}"


def test_print_status_table_fancy_smoke(bgo, capsys):
    rows = [{
        "name": "proc1", "pid": 1234, "status": "online",
        "cpu": "0.1", "mem": "0.2", "uptime": "01:23",
        "command": ["echo", "hi"], "cwd": "/", "started_at": "now",
        "watch": None,
    }]
    bgo._print_status_table(rows, level=bgo.LEVEL_FANCY)
    out = capsys.readouterr().out
    # Top-left corner box glyph must appear
    assert "┏" in out
    assert "┓" in out
    assert "┗" in out
    assert "┛" in out


def test_status_json_does_not_mutate_state(bgo, monkeypatch, capsys):
    """``bgo status --json`` must be read-only for dead procs."""
    bgo.save_proc("dead", {"name": "dead", "pid": 999999, "status": "running", "command": ["true"]})
    monkeypatch.setenv("BGO_TABLE", "plain")
    bgo.cmd_status(argparse.Namespace(json=True, name=None, watch=False, interval=None, plain=True, fancy=False))
    info = bgo.load_proc("dead")
    assert info["status"] == "running"
