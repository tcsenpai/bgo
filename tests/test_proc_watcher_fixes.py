"""Regression tests for the final fix batch.

Covers: H2 (PID/PGID reuse — expected_start identity checks in
``is_running``/``kill_process`` plus hard kill guards), H1 (watcher
post-backoff re-verification before restarting), stop_reason-aware
manual-stop detection, watcher-side ``stop_reason="crashed"`` writes,
watcher-recorded ``pid_start`` on restart, and L5
(``get_process_info_batch`` per-pid fallback when the batched ps call
fails on one stale pid).
"""

from __future__ import annotations

import argparse
import os
import subprocess
from datetime import datetime, timezone
from unittest import mock

import pytest

from bgo_cli import _proc, _watcher


# --- _proc: is_running identity checks (H2) ---------------------------


def test_is_running_legacy_mode_skips_identity_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    probe_calls: list[int] = []
    monkeypatch.setattr(_proc, "_probe_pid_start", lambda p: probe_calls.append(p) or "X")
    assert _proc.is_running(os.getpid()) is True
    assert _proc.is_running(None) is False
    assert probe_calls == []


def test_is_running_expected_start_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_proc, "_probe_pid_start", lambda _pid: "START")
    assert _proc.is_running(os.getpid(), expected_start="START") is True


def test_is_running_expected_start_mismatch_is_not_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_proc, "_probe_pid_start", lambda _pid: "SOMEONE ELSE")
    assert _proc.is_running(os.getpid(), expected_start="START") is False


def test_is_running_dead_pid_never_probed(monkeypatch: pytest.MonkeyPatch) -> None:
    probe_calls: list[int] = []
    monkeypatch.setattr(_proc, "_probe_pid_start", lambda p: probe_calls.append(p) or "X")
    assert _proc.is_running(999999, expected_start="X") is False
    assert probe_calls == []


# --- _proc: kill_process guards + identity (H2) -----------------------


def test_kill_process_refuses_recycled_pid(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    signaled: list[tuple[int, int]] = []
    monkeypatch.setattr(_proc.os, "kill", lambda p, s: signaled.append((p, s)))
    monkeypatch.setattr(_proc, "_is_zombie", lambda _pid: False)
    monkeypatch.setattr(_proc, "_probe_pid_start", lambda _pid: "SOMEONE ELSE")

    assert _proc.kill_process(4242, None, expected_start="START") is False
    # Only liveness probes (sig 0) may have been attempted.
    assert all(sig == 0 for _, sig in signaled)
    assert "refusing to kill" in capsys.readouterr().out


def test_kill_process_expected_start_dead_pid_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_proc, "is_running", lambda _pid, expected_start=None: False)
    assert _proc.kill_process(4242, None, expected_start="START") is True


def test_kill_process_refuses_pid_zero_and_one() -> None:
    assert _proc.kill_process(0, None) is False
    assert _proc.kill_process(1, None) is False


def test_kill_process_refuses_own_pid() -> None:
    assert _proc.kill_process(os.getpid(), None) is False


def test_kill_process_refuses_own_process_group() -> None:
    assert _proc.kill_process(4242, os.getpgid(0)) is False


# --- _proc: get_process_info_batch fallback (L5) -----------------------


def test_get_process_info_batch_falls_back_to_per_pid_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        pid_arg = argv[2]
        if "," in pid_arg:
            # One stale pid fails the whole batch (macOS/BSD behavior).
            return subprocess.CompletedProcess(argv, 1, "", "")
        if pid_arg == "111":
            return subprocess.CompletedProcess(argv, 0, "  111  2.5  0.4 01:02:03\n", "")
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(_proc.subprocess, "run", fake_run)
    result = _proc.get_process_info_batch([111, 222])
    assert result[111] == {"cpu": "2.5", "mem": "0.4", "time": "01:02:03"}
    assert result[222] == {"cpu": "-", "mem": "-", "time": "-"}


def test_get_process_info_batch_real_stale_pid_keeps_live_row() -> None:
    """End-to-end: our own (live) pid plus a stale one — the live row
    must still carry real data regardless of ps's exit code."""
    result = _proc.get_process_info_batch([os.getpid(), 999999])
    assert result[os.getpid()]["cpu"] != "-"
    assert result[999999] == {"cpu": "-", "mem": "-", "time": "-"}


# --- watcher: post-backoff re-verification (H1) ------------------------


def _watching_info(
    *,
    pid: int = 100,
    pid_start: str | None = "START1",
    status: str = "running",
    stop_reason: str | None = None,
    enabled: bool = True,
) -> dict:
    info = {
        "name": "web",
        "pid": pid,
        "status": status,
        "command": ["true"],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "watch": {
            "enabled": enabled,
            "interval": 3,
            "min_uptime": 2,
            "on_fast_crash": "backoff",
            "restarts": 0,
        },
    }
    if pid_start is not None:
        info["pid_start"] = pid_start
    if stop_reason is not None:
        info["stop_reason"] = stop_reason
    return info


def _run_watcher(
    monkeypatch: pytest.MonkeyPatch,
    states: list[dict],
    alive: list[bool],
    probe_result: str = "NEWSTART",
):
    """Run cmd_watcher_loop against scripted load_proc states.

    ``alive`` is consumed in is_running call order (default True once
    exhausted). Returns (rc, restart_calls, saved_states, liveness_seen).
    """
    loaded = iter(states)
    monkeypatch.setattr(_watcher, "load_proc", lambda _name: next(loaded, None))
    alive_iter = iter(alive)
    seen: list[tuple[int | None, str | None]] = []

    def fake_is_running(pid: int | None, expected_start: str | None = None) -> bool:
        seen.append((pid, expected_start))
        return next(alive_iter, True)

    monkeypatch.setattr(_watcher, "is_running", fake_is_running)
    restart_calls: list[dict] = []
    monkeypatch.setattr(
        _watcher,
        "_restart_proc_inplace",
        lambda info: restart_calls.append(info) or (900, 900, None),
    )
    saved: list[dict] = []
    monkeypatch.setattr(_watcher, "save_proc", lambda _n, data: saved.append(dict(data)))
    monkeypatch.setattr(_watcher, "_tail_stderr", lambda _name: "")
    monkeypatch.setattr(_watcher, "_probe_pid_start", lambda _pid: probe_result)
    monkeypatch.setattr(_watcher, "_notify_errored", lambda _n, _r: None)
    monkeypatch.setattr(_watcher, "watcher_log", lambda *_a: None)
    monkeypatch.setattr(_watcher.time, "sleep", lambda _s: None)
    monkeypatch.setattr(_watcher, "signal", mock.MagicMock())
    rc = _watcher.cmd_watcher_loop("web")
    return rc, restart_calls, saved, seen


def test_watcher_exits_when_pid_changed_during_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    base = _watching_info(pid=100, pid_start="START1")
    changed = _watching_info(pid=200, pid_start="START2")
    rc, restarts, _saved, _seen = _run_watcher(
        monkeypatch, [base, base, changed], alive=[False, False]
    )
    assert rc == 0
    assert restarts == []


def test_watcher_exits_when_pid_start_changed_during_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    base = _watching_info(pid=100, pid_start="START1")
    recycled = _watching_info(pid=100, pid_start="START2")
    rc, restarts, _saved, _seen = _run_watcher(
        monkeypatch, [base, base, recycled], alive=[False, False]
    )
    assert rc == 0
    assert restarts == []


def test_watcher_exits_when_user_stopped_during_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    base = _watching_info()
    stopped = _watching_info(status="stopped", stop_reason="user")
    rc, restarts, _saved, _seen = _run_watcher(
        monkeypatch, [base, base, stopped], alive=[False, False]
    )
    assert rc == 0
    assert restarts == []


def test_watcher_exits_when_legacy_stopped_during_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stopped proc without stop_reason is legacy — treat as user stop."""
    base = _watching_info()
    legacy = _watching_info(status="stopped")
    rc, restarts, _saved, _seen = _run_watcher(
        monkeypatch, [base, base, legacy], alive=[False, False]
    )
    assert rc == 0
    assert restarts == []


def test_watcher_resumes_monitoring_when_pid_alive_again(monkeypatch: pytest.MonkeyPatch) -> None:
    base = _watching_info(pid=100, pid_start="START1")
    disabled = _watching_info(enabled=False)
    rc, restarts, _saved, seen = _run_watcher(
        monkeypatch, [base, base, base, disabled], alive=[False, False, True]
    )
    assert rc == 0
    assert restarts == []  # no duplicate restart
    # The post-sleep liveness re-check must carry the recorded identity.
    assert (100, "START1") in seen


def test_watcher_restarts_crashed_marked_proc_and_records_pid_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stop_reason=crashed is NOT a user stop: the watcher must still
    restart, clear stop_reason, and record the new pid_start."""
    base = _watching_info(pid=100, pid_start="START1")
    crashed = _watching_info(pid=100, pid_start="START1", status="stopped", stop_reason="crashed")
    disabled = _watching_info(enabled=False)
    rc, restarts, saved, _seen = _run_watcher(
        monkeypatch, [base, base, crashed, disabled], alive=[False, False, False, False]
    )
    assert rc == 0
    assert len(restarts) == 1
    assert saved, "restart must persist fresh state"
    final = saved[-1]
    assert final["status"] == "running"
    assert final["pid"] == 900
    assert final["pid_start"] == "NEWSTART"
    assert "stop_reason" not in final


def test_watcher_restart_omits_pid_start_when_probe_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    base = _watching_info(pid=100, pid_start="OLD")
    disabled = _watching_info(enabled=False)
    rc, restarts, saved, _seen = _run_watcher(
        monkeypatch, [base, base, base, disabled],
        alive=[False, False, False, False],
        probe_result="",
    )
    assert rc == 0
    assert len(restarts) == 1
    # The stale pid_start of the previous pid must not carry over.
    assert "pid_start" not in saved[-1]


def test_watcher_loop_top_crashed_stop_is_not_a_manual_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    """status=stopped + stop_reason=crashed at the loop-top check must
    fall through to crash handling instead of exiting as a user stop."""
    base = _watching_info()
    crashed = _watching_info(status="stopped", stop_reason="crashed")
    disabled = _watching_info(enabled=False)
    rc, restarts, _saved, _seen = _run_watcher(
        monkeypatch, [base, crashed, crashed, disabled], alive=[False, False, False, False]
    )
    assert rc == 0
    assert len(restarts) == 1  # restarted, not exited


def test_watcher_loop_top_user_stop_exits_without_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    base = _watching_info()
    stopped = _watching_info(status="stopped", stop_reason="user")
    rc, restarts, _saved, _seen = _run_watcher(
        monkeypatch, [base, stopped], alive=[False]
    )
    assert rc == 0
    assert restarts == []


# --- bgo script wiring: expected_start reaches kill/liveness sites -----


def _bgo_running_info() -> dict:
    return {
        "name": "web",
        "pid": 100,
        "pgid": 100,
        "status": "running",
        "command": ["python3", "server.py"],
        "cwd": "/",
        "started_at": "2024-01-01T00:00:00+00:00",
        "pid_start": "START1",
    }


def test_cmd_stop_passes_expected_start_through(bgo, monkeypatch: pytest.MonkeyPatch) -> None:
    bgo.save_proc("web", _bgo_running_info())
    seen: dict = {}
    monkeypatch.setattr(
        bgo,
        "is_running",
        lambda pid, expected_start=None: seen.setdefault("liveness", expected_start) or True,
    )

    def fake_kill(pid, pgid, force=False, expected_start=None):  # type: ignore[no-untyped-def]
        seen["kill"] = (pid, pgid, expected_start)
        return True

    monkeypatch.setattr(bgo, "kill_process", fake_kill)

    rc = bgo.cmd_stop(argparse.Namespace(name="web", force=False))
    assert rc == 0
    assert seen["liveness"] == "START1"
    assert seen["kill"] == (100, 100, "START1")


def test_status_snapshot_passes_expected_start(bgo, monkeypatch: pytest.MonkeyPatch) -> None:
    bgo.save_proc("web", _bgo_running_info())
    seen: list[str | None] = []
    monkeypatch.setattr(
        bgo,
        "is_running",
        lambda pid, expected_start=None: seen.append(expected_start) or False,
    )
    monkeypatch.setattr(bgo, "get_process_info_batch", lambda _pids: {})

    rows = bgo._status_snapshot({"web": bgo.load_proc("web")}, persist=True)

    assert seen == ["START1"]
    assert rows[0]["status"] == "stopped"
    saved = bgo.load_proc("web")
    assert saved["stop_reason"] == "crashed"
