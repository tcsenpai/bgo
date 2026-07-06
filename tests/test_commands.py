"""Tests for the ``cmd_*`` handlers in the root ``bgo`` script.

These tests focus on the handlers that are not already covered in
``test_utils.py`` or ``test_table.py``. Process lifecycle is mocked so
no real background processes are spawned.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from unittest import mock

import pytest


def _running_info(name: str = "web", pid: int = 100) -> dict:
    return {
        "name": name,
        "pid": pid,
        "pgid": pid,
        "status": "running",
        "command": ["python3", "server.py"],
        "cwd": "/",
        "started_at": "2024-01-01T00:00:00+00:00",
    }


def _stopped_info(name: str = "web") -> dict:
    return {
        "name": name,
        "pid": 100,
        "pgid": 100,
        "status": "stopped",
        "command": ["python3", "server.py"],
        "cwd": "/",
        "started_at": "2024-01-01T00:00:00+00:00",
    }


# --- cmd_stop ---


def test_stop_running_proc(bgo, monkeypatch):
    info = _running_info()
    bgo.save_proc("web", info)
    killed: list[tuple[int, int | None, bool]] = []

    monkeypatch.setattr(bgo, "is_running", lambda pid: pid == 100)
    monkeypatch.setattr(bgo, "kill_process", lambda pid, pgid, force=False: killed.append((pid, pgid, force)) or True)

    rc = bgo.cmd_stop(argparse.Namespace(name="web", force=False))
    assert rc == 0
    assert killed == [(100, 100, False)]
    assert bgo.load_proc("web")["status"] == "stopped"


def test_stop_already_stopped_proc(bgo, monkeypatch, capsys):
    info = _stopped_info()
    bgo.save_proc("web", info)
    monkeypatch.setattr(bgo, "is_running", lambda _pid: False)

    rc = bgo.cmd_stop(argparse.Namespace(name="web", force=False))
    assert rc == 0
    assert "not running" in capsys.readouterr().out


def test_stop_unknown_proc(bgo, capsys):
    rc = bgo.cmd_stop(argparse.Namespace(name="nope", force=False))
    assert rc == 1
    assert "No process named" in capsys.readouterr().out


def test_stop_force_uses_sigkill(bgo, monkeypatch):
    info = _running_info()
    bgo.save_proc("web", info)
    killed: list[tuple[int, int | None, bool]] = []

    monkeypatch.setattr(bgo, "is_running", lambda pid: pid == 100)
    monkeypatch.setattr(bgo, "kill_process", lambda pid, pgid, force=False: killed.append((pid, pgid, force)) or True)

    bgo.cmd_stop(argparse.Namespace(name="web", force=True))
    assert killed == [(100, 100, True)]


# --- cmd_restart ---


def test_restart_stopped_proc(bgo, monkeypatch):
    info = _stopped_info()
    bgo.save_proc("web", info)
    started: list[argparse.Namespace] = []

    monkeypatch.setattr(bgo, "is_running", lambda _pid: False)
    monkeypatch.setattr(bgo, "kill_process", lambda _pid, _pgid, _force=False: True)
    monkeypatch.setattr(bgo, "cmd_start", lambda args: started.append(args) or 0)

    rc = bgo.cmd_restart(argparse.Namespace(name="web", reset_counters=False))
    assert rc == 0
    assert len(started) == 1
    assert started[0].name == "web"


def test_restart_preserves_autostart_policy(bgo, monkeypatch):
    info = _stopped_info()
    info["autostart"] = "never"
    bgo.save_proc("web", info)
    started: list[argparse.Namespace] = []

    monkeypatch.setattr(bgo, "is_running", lambda _pid: False)
    monkeypatch.setattr(bgo, "kill_process", lambda _pid, _pgid, _force=False: True)
    monkeypatch.setattr(bgo, "cmd_start", lambda args: started.append(args) or 0)

    bgo.cmd_restart(argparse.Namespace(name="web", reset_counters=False))
    assert started[0].autostart == "never"


def test_restart_resets_counters(bgo, monkeypatch):
    info = _stopped_info()
    info["watch"] = {"enabled": True, "errored": True, "restarts": 5}
    bgo.save_proc("web", info)
    started: list[argparse.Namespace] = []

    monkeypatch.setattr(bgo, "is_running", lambda _pid: False)
    monkeypatch.setattr(bgo, "kill_process", lambda _pid, _pgid, _force=False: True)
    monkeypatch.setattr(bgo, "cmd_start", lambda args: started.append(args) or 0)

    bgo.cmd_restart(argparse.Namespace(name="web", reset_counters=True))
    saved = bgo.load_proc("web")
    assert saved["watch"]["restarts"] == 0
    assert saved["watch"]["errored"] is False


# --- cmd_delete ---


def test_delete_stopped_proc(bgo, monkeypatch):
    info = _stopped_info()
    bgo.save_proc("web", info)
    bgo.log_path("web", "out").write_text("stdout")

    monkeypatch.setattr(bgo, "is_running", lambda _pid: False)
    rc = bgo.cmd_delete(argparse.Namespace(name="web", yes=True, keep_logs=False))
    assert rc == 0
    assert bgo.load_proc("web") is None
    assert not bgo.log_path("web", "out").exists()


def test_delete_keep_logs(bgo, monkeypatch):
    info = _stopped_info()
    bgo.save_proc("web", info)
    bgo.log_path("web", "out").write_text("stdout")

    monkeypatch.setattr(bgo, "is_running", lambda _pid: False)
    rc = bgo.cmd_delete(argparse.Namespace(name="web", yes=True, keep_logs=True))
    assert rc == 0
    assert bgo.load_proc("web") is None
    assert bgo.log_path("web", "out").exists()


def test_delete_running_proc_requires_confirmation(bgo, monkeypatch, capsys):
    info = _running_info()
    bgo.save_proc("web", info)
    monkeypatch.setattr(bgo, "is_running", lambda _pid: True)

    # User declines.
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    rc = bgo.cmd_delete(argparse.Namespace(name="web", yes=False, keep_logs=False))
    assert rc == 0
    assert bgo.load_proc("web") is not None
    assert "Cancelled" in capsys.readouterr().out


# --- cmd_clean ---


def test_clean_removes_only_stopped_procs(bgo, monkeypatch):
    running = _running_info("running", pid=100)
    stopped = _stopped_info("stopped")
    stopped["pid"] = 200
    bgo.save_proc("running", running)
    bgo.save_proc("stopped", stopped)
    monkeypatch.setattr(bgo, "is_running", lambda pid: pid == 100)

    bgo.cmd_clean(argparse.Namespace())
    assert bgo.load_proc("running") is not None
    assert bgo.load_proc("stopped") is None


# --- cmd_logs ---


def test_logs_prints_last_lines(bgo, capsys):
    bgo.save_proc("web", _running_info())
    out = bgo.log_path("web", "out")
    out.write_text("\n".join(f"line{i}" for i in range(60)))

    bgo.cmd_logs(argparse.Namespace(name="web", follow=False, lines=10, stdout=False, stderr=False, watcher=False))
    text = capsys.readouterr().out
    assert "line50" in text
    assert "line10" not in text


def test_logs_watcher_stream(bgo, capsys):
    bgo.save_proc("web", _running_info())
    watcher = bgo.watcher_log_path("web")
    watcher.write_text("[2024] crash\n")

    bgo.cmd_logs(argparse.Namespace(name="web", follow=False, lines=10, stdout=False, stderr=False, watcher=True))
    assert "crash" in capsys.readouterr().out


def test_logs_unknown_proc(bgo, capsys):
    rc = bgo.cmd_logs(argparse.Namespace(name="nope", follow=False, lines=10, stdout=False, stderr=False, watcher=False))
    assert rc == 1
    assert "No process named" in capsys.readouterr().out


# --- cmd_watch / cmd_unwatch ---


def test_watch_attaches_watcher(bgo, monkeypatch):
    info = _running_info()
    bgo.save_proc("web", info)
    spawned: list[str] = []

    def fake_spawn(name: str):
        spawned.append(name)
        return 200, 200

    monkeypatch.setattr(bgo, "is_running", lambda _pid: True)
    monkeypatch.setattr(bgo, "_kill_watcher", lambda _info: None)
    monkeypatch.setattr(bgo, "_spawn_watcher", fake_spawn)

    rc = bgo.cmd_watch(argparse.Namespace(
        name="web", interval=5, min_uptime=3, on_fast_crash="stop", reset=False
    ))
    assert rc == 0
    assert spawned == ["web"]
    saved = bgo.load_proc("web")
    assert saved["watch"]["enabled"] is True
    assert saved["watch"]["interval"] == 5


def test_watch_refuses_not_running_proc(bgo, monkeypatch, capsys):
    bgo.save_proc("web", _stopped_info())
    monkeypatch.setattr(bgo, "is_running", lambda _pid: False)

    rc = bgo.cmd_watch(argparse.Namespace(
        name="web", interval=None, min_uptime=None, on_fast_crash=None, reset=False
    ))
    assert rc == 1
    assert "not running" in capsys.readouterr().out


def test_unwatch_disables_watcher(bgo, monkeypatch):
    info = _running_info()
    info["watch"] = {"enabled": True}
    bgo.save_proc("web", info)
    monkeypatch.setattr(bgo, "_kill_watcher", lambda _info: None)

    rc = bgo.cmd_unwatch(argparse.Namespace(name="web"))
    assert rc == 0
    assert bgo.load_proc("web")["watch"]["enabled"] is False


# --- cmd_restart_stopped / cmd_restart_last ---


def test_restart_stopped_all(bgo, monkeypatch):
    bgo.save_proc("a", _stopped_info("a"))
    bgo.save_proc("b", _stopped_info("b"))
    started: list[str] = []

    monkeypatch.setattr(bgo, "is_running", lambda _pid: False)
    monkeypatch.setattr(bgo, "cmd_start", lambda args: started.append(args.name) or 0)

    bgo.cmd_restart_stopped(argparse.Namespace(names=[], all=True))
    assert set(started) == {"a", "b"}


def test_restart_stopped_named(bgo, monkeypatch):
    bgo.save_proc("a", _stopped_info("a"))
    bgo.save_proc("b", _stopped_info("b"))
    started: list[str] = []

    monkeypatch.setattr(bgo, "is_running", lambda _pid: False)
    monkeypatch.setattr(bgo, "cmd_start", lambda args: started.append(args.name) or 0)

    bgo.cmd_restart_stopped(argparse.Namespace(names=["a"], all=False))
    assert started == ["a"]


def test_restart_last_all(bgo, monkeypatch):
    a = _stopped_info("a")
    a["stopped_at"] = "2024-01-02T00:00:00+00:00"
    b = _stopped_info("b")
    b["stopped_at"] = "2024-01-01T00:00:00+00:00"
    bgo.save_proc("a", a)
    bgo.save_proc("b", b)
    started: list[str] = []

    monkeypatch.setattr(bgo, "is_running", lambda _pid: False)
    monkeypatch.setattr(bgo, "cmd_start", lambda args: started.append(args.name) or 0)

    bgo.cmd_restart_last(argparse.Namespace(all=True))
    assert started == ["a", "b"]


# --- cmd_status detail ---


def test_status_detail_prints_proc_info(bgo, monkeypatch, capsys):
    bgo.save_proc("web", _running_info())
    monkeypatch.setattr(bgo, "is_running", lambda _pid: True)
    monkeypatch.setattr(bgo, "get_process_info", lambda _pid: {"cpu": "1.2", "mem": "0.5", "time": "00:01"})

    bgo.cmd_status(argparse.Namespace(name="web", json=False, watch=False, interval=None, plain=False, fancy=False))
    out = capsys.readouterr().out
    assert "web" in out
    assert "python3 server.py" in out


def test_status_json_for_name(bgo, monkeypatch, capsys):
    info = _running_info()
    bgo.save_proc("web", info)
    monkeypatch.setattr(bgo, "is_running", lambda _pid: True)

    bgo.cmd_status(argparse.Namespace(name="web", json=True, watch=False, interval=None, plain=False, fancy=False))
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["name"] == "web"
