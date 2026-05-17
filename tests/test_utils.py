"""Pure utility tests: command-shape detection, name derivation, liveness."""

import os
import sys
import time

import pytest


# --- _looks_like_command ---

def test_looks_like_command_path_separator(bgo):
    assert bgo._looks_like_command("/usr/bin/python3") is True


def test_looks_like_command_dot_slash(bgo):
    assert bgo._looks_like_command("./script.sh") is True


def test_looks_like_command_extension(bgo):
    assert bgo._looks_like_command("script.py") is True


def test_looks_like_command_resolved_via_which(bgo):
    # python3 should resolve on any test host
    assert bgo._looks_like_command("python3") is True


def test_looks_like_command_plain_name_not_executable(bgo):
    assert bgo._looks_like_command("myapp") is False


# --- derive_name ---

def test_derive_name_strips_py(bgo):
    assert bgo.derive_name(["python3.py"]) == "python3"


def test_derive_name_strips_sh(bgo):
    assert bgo.derive_name(["./server.sh"]) == "server"


def test_derive_name_basename(bgo):
    assert bgo.derive_name(["/usr/local/bin/myapp"]) == "myapp"


def test_derive_name_no_extension(bgo):
    assert bgo.derive_name(["plainname"]) == "plainname"


# --- is_running ---

def test_is_running_none(bgo):
    assert bgo.is_running(None) is False


def test_is_running_self(bgo):
    assert bgo.is_running(os.getpid()) is True


def test_is_running_nonexistent(bgo):
    # PID 999999 almost certainly doesn't exist; if it does, picosec window.
    assert bgo.is_running(999999) is False


def test_is_zombie_self_is_false(bgo):
    """Our own running test process is not a zombie."""
    assert bgo._is_zombie(os.getpid()) is False


def test_is_zombie_nonexistent_pid_is_false(bgo):
    """Non-existent PID returns False (not a zombie, not running)."""
    assert bgo._is_zombie(999999) is False


# --- _default_watch_config ---

def test_default_watch_config_no_overrides(bgo):
    cfg = bgo._default_watch_config()
    assert cfg["enabled"] is True
    assert cfg["interval"] == bgo.WATCH_DEFAULTS["interval"]
    assert cfg["min_uptime"] == bgo.WATCH_DEFAULTS["min_uptime"]
    assert cfg["on_fast_crash"] == bgo.WATCH_DEFAULTS["on_fast_crash"]
    assert cfg["restarts"] == 0
    assert cfg["errored"] is False


def test_default_watch_config_with_overrides(bgo):
    cfg = bgo._default_watch_config({
        "interval": 10,
        "min_uptime": 5,
        "on_fast_crash": "stop",
    })
    assert cfg["interval"] == 10
    assert cfg["min_uptime"] == 5
    assert cfg["on_fast_crash"] == "stop"


def test_default_watch_config_ignores_none_overrides(bgo):
    """None values must not clobber defaults — used by argparse-default=None."""
    cfg = bgo._default_watch_config({"interval": None})
    assert cfg["interval"] == bgo.WATCH_DEFAULTS["interval"]


def test_default_watch_config_rejects_unknown_keys(bgo):
    cfg = bgo._default_watch_config({"bogus_key": "x"})
    assert "bogus_key" not in cfg


# --- _tail_stderr ---

def test_tail_stderr_missing_file(bgo):
    assert bgo._tail_stderr("nope") == ""


def test_tail_stderr_small_file(bgo):
    bgo.log_path("demo", "err").write_text("hello\nworld\n")
    assert bgo._tail_stderr("demo") == "hello\nworld"


def test_tail_stderr_truncates_to_nbytes(bgo):
    big = "x" * 5000 + "\nlast line\n"
    bgo.log_path("demo", "err").write_text(big)
    tail = bgo._tail_stderr("demo", nbytes=64)
    assert "last line" in tail
    assert len(tail) <= 100  # rough — strip + leading-partial trim


def test_tail_stderr_strips_leading_partial_line(bgo):
    bgo.log_path("demo", "err").write_text("aaaa\nbbbb\ncccc\n")
    tail = bgo._tail_stderr("demo", nbytes=8)
    # Should not include the truncated "aa" prefix
    assert not tail.startswith("aaaa")
