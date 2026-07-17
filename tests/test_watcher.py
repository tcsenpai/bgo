"""Tests for ``bgo_cli._watcher``.

The watcher loop is time-sensitive and long-running, so these tests
heavily mock ``time``, ``subprocess``, and process-state functions.
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

from bgo_cli import _watcher


# --- _notify_errored ----------------------------------------------------


def test_notify_errored_fires_when_backend_available() -> None:
    calls: list[tuple[str, str]] = []

    def fake_notify(title: str, body: str, level: str) -> bool:
        calls.append((title, body))
        return True

    fake_mod = mock.MagicMock()
    fake_mod.notify = fake_notify
    with mock.patch.dict(sys.modules, {"bgo_cli._notify": fake_mod}):
        _watcher._notify_errored("web", "boom")
    assert len(calls) == 1
    assert "web" in calls[0][0]
    assert "boom" in calls[0][1]


def test_notify_errored_swallows_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "bgo_cli._notify", raising=False)

    def broken_import(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise ImportError("no notify")

    monkeypatch.setattr("builtins.__import__", broken_import)
    # Should not raise.
    _watcher._notify_errored("web", "boom")


def test_notify_errored_swallows_notify_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_mod = mock.MagicMock()
    fake_mod.notify.side_effect = RuntimeError("notify exploded")
    monkeypatch.setitem(sys.modules, "bgo_cli._notify", fake_mod)
    # Should not raise.
    _watcher._notify_errored("web", "boom")


# --- _spawn_watcher -----------------------------------------------------


def test_spawn_watcher_invokes_bgo_watcher(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(_watcher, "watcher_log_path", lambda name: tmp_path / f"{name}.watcher.log")
    fake_proc = mock.MagicMock()
    fake_proc.pid = 777
    popen_calls: list[list[str]] = []

    def fake_popen(argv, **kwargs):  # type: ignore[no-untyped-def]
        popen_calls.append(argv)
        return fake_proc

    monkeypatch.setattr(_watcher.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(_watcher.os, "getpgid", lambda pid: 888)
    monkeypatch.setattr(_watcher, "_bgo_entrypoint", lambda: "/usr/bin/bgo")

    pid, pgid = _watcher._spawn_watcher("web")
    assert pid == 777
    assert pgid == 888
    assert popen_calls == [[sys.executable, "/usr/bin/bgo", "__watcher__", "web"]]


def test_spawn_watcher_returns_none_on_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(_watcher, "watcher_log_path", lambda name: tmp_path / f"{name}.watcher.log")
    monkeypatch.setattr(
        _watcher.subprocess, "Popen", mock.MagicMock(side_effect=OSError("cannot fork"))
    )
    pid, pgid = _watcher._spawn_watcher("web")
    assert pid is None
    assert pgid is None


# --- _kill_watcher ------------------------------------------------------


def test_kill_watcher_kills_running_watcher_and_clears_pids(monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[tuple[int, int | None]] = []

    def fake_is_running(pid: int | None) -> bool:
        return pid == 100

    def fake_kill(pid: int, pgid: int | None) -> bool:
        killed.append((pid, pgid))
        return True

    monkeypatch.setattr(_watcher, "is_running", fake_is_running)
    monkeypatch.setattr(_watcher, "kill_process", fake_kill)

    info = {
        "name": "web",
        "watch": {"watcher_pid": 100, "watcher_pgid": 200},
    }
    _watcher._kill_watcher(info)
    assert killed == [(100, 200)]
    assert info["watch"]["watcher_pid"] is None
    assert info["watch"]["watcher_pgid"] is None


def test_kill_watcher_noop_when_no_watcher_pid() -> None:
    info = {"name": "web", "watch": {"watcher_pid": None}}
    # Should not raise.
    _watcher._kill_watcher(info)


# --- _tail_stderr -------------------------------------------------------


def test_tail_stderr_missing_file() -> None:
    assert _watcher._tail_stderr("nope") == ""


def test_tail_stderr_returns_clean_tail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_watcher, "log_path", lambda name, stream: tmp_path / f"{name}.{stream}.log")
    err = tmp_path / "web.err.log"
    err.write_text("line1\nline2\nline3\n")
    # nbytes=13 starts at the newline before line2, so the partial line1
    # is dropped and line2+line3 remain.
    assert _watcher._tail_stderr("web", nbytes=13) == "line2\nline3"


# --- _restart_proc_inplace ---------------------------------------------


def test_restart_proc_inplace_starts_command_and_writes_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bgo_cli import _state

    monkeypatch.setattr(_state, "log_path", lambda name, stream: tmp_path / f"{name}.{stream}.log")
    fake_proc = mock.MagicMock()
    fake_proc.pid = 555
    popen_calls: list[list[str]] = []

    def fake_popen(argv, **kwargs):  # type: ignore[no-untyped-def]
        popen_calls.append(argv)
        return fake_proc

    monkeypatch.setattr(_watcher.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(_watcher.os, "getpgid", lambda pid: 666)

    info = {"name": "web", "command": ["python3", "server.py"], "cwd": str(tmp_path)}
    pid, pgid, err = _watcher._restart_proc_inplace(info)
    assert pid == 555
    assert pgid == 666
    assert err is None
    assert popen_calls == [["python3", "server.py"]]

    out_log = tmp_path / "web.out.log"
    err_log = tmp_path / "web.err.log"
    assert out_log.exists() and err_log.exists()
    assert "watch restart" in out_log.read_text()


def test_restart_proc_inplace_returns_error_on_file_not_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(_watcher, "log_path", lambda name, stream: tmp_path / f"{name}.{stream}.log")
    monkeypatch.setattr(
        _watcher.subprocess, "Popen", mock.MagicMock(side_effect=FileNotFoundError("missing"))
    )

    info = {"name": "web", "command": ["nope"], "cwd": str(tmp_path)}
    pid, pgid, err = _watcher._restart_proc_inplace(info)
    assert pid is None
    assert "command not found" in err


# --- cmd_watcher_loop ---------------------------------------------------


def _make_info(
    *,
    name: str = "web",
    pid: int = 100,
    status: str = "running",
    enabled: bool = True,
    on_fast_crash: str = "backoff",
    interval: int = 3,
    min_uptime: int = 2,
    started_at: str | None = None,
) -> dict:
    if started_at is None:
        started_at = datetime.now(timezone.utc).isoformat()
    return {
        "name": name,
        "pid": pid,
        "status": status,
        "command": ["true"],
        "started_at": started_at,
        "watch": {
            "enabled": enabled,
            "interval": interval,
            "min_uptime": min_uptime,
            "on_fast_crash": on_fast_crash,
            "restarts": 0,
        },
    }


def test_watcher_loop_exits_when_watch_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    info = _make_info(enabled=False)
    monkeypatch.setattr(_watcher, "load_proc", lambda _name: info)
    monkeypatch.setattr(_watcher, "signal", mock.MagicMock())
    assert _watcher.cmd_watcher_loop("web") == 0


def test_watcher_loop_exits_when_proc_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    info = _make_info(status="stopped")
    monkeypatch.setattr(_watcher, "load_proc", lambda _name: info)
    monkeypatch.setattr(_watcher, "signal", mock.MagicMock())
    assert _watcher.cmd_watcher_loop("web") == 0


def test_watcher_loop_exits_when_state_vanishes(monkeypatch: pytest.MonkeyPatch) -> None:
    info = _make_info()
    calls: list[int] = []

    def load(name: str) -> dict | None:
        calls.append(len(calls))
        return info if len(calls) < 2 else None

    monkeypatch.setattr(_watcher, "load_proc", load)
    monkeypatch.setattr(_watcher, "is_running", lambda _pid, expected_start=None: True)
    monkeypatch.setattr(_watcher.time, "sleep", lambda _s: None)
    monkeypatch.setattr(_watcher, "signal", mock.MagicMock())
    assert _watcher.cmd_watcher_loop("web") == 0


def test_watcher_loop_fast_crash_stop_mode_marks_errored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    started_at = datetime.now(timezone.utc).isoformat()
    info = _make_info(on_fast_crash="stop", started_at=started_at)
    saved: dict | None = None

    def save(name: str, data: dict) -> None:
        nonlocal saved
        saved = data

    monkeypatch.setattr(_watcher, "load_proc", lambda _name: dict(info))
    monkeypatch.setattr(_watcher, "save_proc", save)
    monkeypatch.setattr(_watcher, "is_running", lambda _pid, expected_start=None: False)
    monkeypatch.setattr(_watcher, "_tail_stderr", lambda _name: "stderr tail")
    monkeypatch.setattr(_watcher, "_notify_errored", lambda _n, _r: None)
    monkeypatch.setattr(_watcher.time, "sleep", lambda _s: None)
    monkeypatch.setattr(_watcher, "signal", mock.MagicMock())

    assert _watcher.cmd_watcher_loop("web") == 0
    assert saved is not None
    assert saved["watch"]["errored"] is True
    assert "fast-crash" in saved["watch"]["error_reason"]
    assert saved["watch"]["last_stderr_tail"] == "stderr tail"
    assert saved["status"] == "stopped"
    assert saved["stop_reason"] == "crashed"


def test_watcher_loop_backoff_exits_after_repeated_fast_crashes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    started_at = datetime.now(timezone.utc).isoformat()
    info = _make_info(on_fast_crash="backoff", started_at=started_at)
    saved_states: list[dict] = []
    restart_count = 0

    def save(name: str, data: dict) -> None:
        saved_states.append(dict(data))

    def restart(info: dict):
        nonlocal restart_count
        restart_count += 1
        return 100 + restart_count, 200 + restart_count, None

    monkeypatch.setattr(_watcher, "load_proc", lambda _name: dict(info))
    monkeypatch.setattr(_watcher, "save_proc", save)
    monkeypatch.setattr(_watcher, "is_running", lambda _pid, expected_start=None: False)
    monkeypatch.setattr(_watcher, "_tail_stderr", lambda _name: "boom")
    monkeypatch.setattr(_watcher, "_restart_proc_inplace", restart)
    monkeypatch.setattr(_watcher, "_probe_pid_start", lambda _pid: "")
    monkeypatch.setattr(_watcher, "_notify_errored", lambda _n, _r: None)
    monkeypatch.setattr(_watcher.time, "sleep", lambda _s: None)
    monkeypatch.setattr(_watcher, "signal", mock.MagicMock())

    assert _watcher.cmd_watcher_loop("web") == 0
    # One initial death + three restarts that also die fast = 4 fast-crashes.
    assert restart_count == 3
    final = saved_states[-1]
    assert final["watch"]["errored"] is True
    assert "consecutive fast-crashes" in final["watch"]["error_reason"]
    assert final["status"] == "stopped"
    assert final["stop_reason"] == "crashed"


def test_watcher_loop_retry_mode_keeps_restarting_until_restart_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    started_at = datetime.now(timezone.utc).isoformat()
    info = _make_info(on_fast_crash="retry", started_at=started_at)
    saved_states: list[dict] = []
    restart_count = 0

    def save(name: str, data: dict) -> None:
        saved_states.append(dict(data))

    def restart(info: dict):
        nonlocal restart_count
        restart_count += 1
        if restart_count >= 2:
            return None, None, "gave up"
        return 200 + restart_count, 300 + restart_count, None

    monkeypatch.setattr(_watcher, "load_proc", lambda _name: dict(info))
    monkeypatch.setattr(_watcher, "save_proc", save)
    monkeypatch.setattr(_watcher, "is_running", lambda _pid, expected_start=None: False)
    monkeypatch.setattr(_watcher, "_tail_stderr", lambda _name: "")
    monkeypatch.setattr(_watcher, "_restart_proc_inplace", restart)
    monkeypatch.setattr(_watcher, "_probe_pid_start", lambda _pid: "")
    monkeypatch.setattr(_watcher, "_notify_errored", lambda _n, _r: None)
    monkeypatch.setattr(_watcher.time, "sleep", lambda _s: None)
    monkeypatch.setattr(_watcher, "signal", mock.MagicMock())

    assert _watcher.cmd_watcher_loop("web") == 0
    assert restart_count == 2
    final = saved_states[-1]
    assert final["watch"]["errored"] is True
    assert final["watch"]["error_reason"] == "gave up"
    assert final["stop_reason"] == "crashed"


def test_watcher_loop_restart_failure_marks_errored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    started_at = datetime.now(timezone.utc).isoformat()
    info = _make_info(on_fast_crash="backoff", started_at=started_at)
    saved: dict | None = None

    def save(name: str, data: dict) -> None:
        nonlocal saved
        saved = data

    monkeypatch.setattr(_watcher, "load_proc", lambda _name: dict(info))
    monkeypatch.setattr(_watcher, "save_proc", save)
    monkeypatch.setattr(_watcher, "is_running", lambda _pid, expected_start=None: False)
    monkeypatch.setattr(_watcher, "_tail_stderr", lambda _name: "boom")
    monkeypatch.setattr(
        _watcher, "_restart_proc_inplace", lambda _info: (None, None, "failed to start")
    )
    monkeypatch.setattr(_watcher, "_notify_errored", lambda _n, _r: None)
    monkeypatch.setattr(_watcher.time, "sleep", lambda _s: None)
    monkeypatch.setattr(_watcher, "signal", mock.MagicMock())

    assert _watcher.cmd_watcher_loop("web") == 0
    assert saved["watch"]["errored"] is True
    assert saved["watch"]["error_reason"] == "failed to start"
    assert saved["status"] == "stopped"
    assert saved["stop_reason"] == "crashed"


def test_watcher_loop_sets_sigchld_to_ignore(monkeypatch: pytest.MonkeyPatch) -> None:
    info = _make_info(enabled=False)
    sig_calls: list[tuple[int, int]] = []

    def fake_signal(sig: int, handler: int) -> None:
        sig_calls.append((sig, handler))

    monkeypatch.setattr(_watcher.signal, "signal", fake_signal)
    monkeypatch.setattr(_watcher, "load_proc", lambda _name: info)
    _watcher.cmd_watcher_loop("web")
    assert (signal.SIGCHLD, signal.SIG_IGN) in sig_calls


def test_watcher_loop_swallows_signal_setup_error(monkeypatch: pytest.MonkeyPatch) -> None:
    info = _make_info(enabled=False)
    monkeypatch.setattr(
        _watcher.signal, "signal", mock.MagicMock(side_effect=ValueError("no signals"))
    )
    monkeypatch.setattr(_watcher, "load_proc", lambda _name: info)
    # Should not raise.
    _watcher.cmd_watcher_loop("web")
