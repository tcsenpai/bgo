"""Pure utility tests: command-shape detection, name derivation, liveness."""

import argparse
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


def test_looks_like_command_dotted_name_is_not_command(bgo):
    """Dotted process names like 'my.app' must not look like executables."""
    assert bgo._looks_like_command("my.app") is False


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


# --- autostart policy ---


def test_start_stores_default_autostart_policy(bgo, monkeypatch):
    monkeypatch.setattr(bgo, "is_running", lambda _pid: True)
    bgo.cmd_start(
        argparse.Namespace(
            name="demo",
            command=["python3", "-c", "import time; time.sleep(30)"],
            cwd=None,
            watch=False,
            interval=None,
            min_uptime=None,
            on_fast_crash=None,
            autostart=None,
        )
    )
    info = bgo.load_proc("demo")
    assert info["autostart"] == bgo.AUTOSTART_DEFAULT
    bgo.cmd_stop(argparse.Namespace(name="demo", force=True))


def test_start_honors_explicit_autostart_policy(bgo, monkeypatch):
    monkeypatch.setattr(bgo, "is_running", lambda _pid: True)
    bgo.cmd_start(
        argparse.Namespace(
            name="demo",
            command=["python3", "-c", "import time; time.sleep(30)"],
            cwd=None,
            watch=False,
            interval=None,
            min_uptime=None,
            on_fast_crash=None,
            autostart="never",
        )
    )
    info = bgo.load_proc("demo")
    assert info["autostart"] == "never"
    bgo.cmd_stop(argparse.Namespace(name="demo", force=True))


def test_resurrect_respects_autostart_policy(bgo, monkeypatch, capsys):
    bgo.save_proc("always", {"name": "always", "pid": 1, "status": "running", "command": ["true"], "autostart": "always"})
    bgo.save_proc("unless", {"name": "unless", "pid": 2, "status": "running", "command": ["true"], "autostart": "unless-stopped"})
    bgo.save_proc("stopped", {"name": "stopped", "pid": 3, "status": "stopped", "command": ["true"], "autostart": "unless-stopped"})
    bgo.save_proc("never", {"name": "never", "pid": 4, "status": "running", "command": ["true"], "autostart": "never"})

    started: list[str] = []
    monkeypatch.setattr(bgo, "cmd_start", lambda args: started.append(args.name) or 0)

    bgo.cmd_resurrect(argparse.Namespace())
    assert set(started) == {"always", "unless"}


def test_autostart_set_and_show(bgo, capsys):
    bgo.save_proc("demo", {"name": "demo", "pid": 1, "status": "running", "command": ["true"]})

    bgo.cmd_autostart(argparse.Namespace(action="set", name="demo", policy="never"))
    assert bgo.load_proc("demo")["autostart"] == "never"

    bgo.cmd_autostart(argparse.Namespace(action="show", name="demo"))
    assert "autostart=never" in capsys.readouterr().out
