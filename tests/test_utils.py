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


# --- _resolve_watch_block ---

def test_resolve_watch_want_fresh(bgo):
    """want_watch=True with no prior -> fresh defaults."""
    block = bgo._resolve_watch_block(True, None, None)
    assert block is not None
    assert block["enabled"] is True
    assert block["restarts"] == 0


def test_resolve_watch_want_overrides_prior(bgo):
    """Explicit -w wins over prior; counters reset."""
    prior = bgo._default_watch_config()
    prior["restarts"] = 42
    block = bgo._resolve_watch_block(True, {"interval": 10}, prior)
    assert block["interval"] == 10
    assert block["restarts"] == 0  # fresh defaults


def test_resolve_watch_inherit_prior(bgo):
    """No -w but prior watch enabled -> carry forward, preserve counters."""
    prior = bgo._default_watch_config({"interval": 7})
    prior["restarts"] = 42
    prior["watcher_pid"] = 1234
    prior["errored"] = True
    prior["error_reason"] = "boom"
    block = bgo._resolve_watch_block(False, None, prior)
    assert block is not None
    assert block["interval"] == 7
    assert block["restarts"] == 42  # preserved
    assert block["watcher_pid"] is None  # runtime cleared
    assert block["errored"] is False  # runtime cleared
    assert block["error_reason"] is None


def test_resolve_watch_no_prior_no_want(bgo):
    """No -w and no prior -> None."""
    assert bgo._resolve_watch_block(False, None, None) is None


def test_resolve_watch_disabled_prior_returns_none(bgo):
    """Prior watch with enabled=False is treated as no prior."""
    prior = bgo._default_watch_config()
    prior["enabled"] = False
    assert bgo._resolve_watch_block(False, None, prior) is None


def test_resolve_watch_returns_new_dict(bgo):
    """Result should not be the same object as prior — caller mutates it."""
    prior = bgo._default_watch_config()
    block = bgo._resolve_watch_block(False, None, prior)
    assert block is not prior


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
