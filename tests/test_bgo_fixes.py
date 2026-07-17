"""Regression tests for the core-fix batch in the root ``bgo`` script.

Covers: M3 (no-command start), M4 (name validation at the CLI
boundary), H3/M1 (stop_reason + status write-back race), M5 (delete
ordering), M7 (failed stop semantics), H1 (stale watcher kill on
start), H4 (tray dependency probe), H5 (friendly standalone error),
L9 (log tailing), L10 (direct-mode -w passthrough), L13 (honest
watch cell), and pid_start recording.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

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


def _start_ns(name: str = "web", command: list[str] | None = None, watch: bool = False):
    return argparse.Namespace(
        name=name,
        command=command or ["python3", "-c", "import time; time.sleep(30)"],
        cwd=None,
        watch=watch,
        interval=None,
        min_uptime=None,
        on_fast_crash=None,
        autostart=None,
    )


# --- M3: `bgo start <name>` with no command must not execute "start" ---


def test_start_without_command_errors_cleanly(bgo, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["bgo", "start", "foo"])
    rc = bgo.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "No command specified" in out
    # No start markers may be written and no state may be created.
    assert list(bgo.LOGS_DIR.glob("*.log")) == []
    assert list(bgo.PROCS_DIR.glob("*.json")) == []


# --- M4: proc names are validated at the CLI boundary ---


def test_start_rejects_path_separator_name(bgo, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["bgo", "start", "foo/bar", "--", "echo", "hi"])
    rc = bgo.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "invalid process name" in out
    assert "Traceback" not in out
    assert list(bgo.PROCS_DIR.glob("*.json")) == []


def test_start_rejects_dotdot_name(bgo, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["bgo", "start", "../x", "--", "echo", "hi"])
    rc = bgo.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "invalid process name" in out
    # Nothing may escape the sandboxed state dir.
    assert list(bgo.PROCS_DIR.glob("*.json")) == []


def test_stop_rejects_invalid_name(bgo, capsys):
    rc = bgo.cmd_stop(argparse.Namespace(name="foo/bar", force=False))
    assert rc == 1
    assert "invalid process name" in capsys.readouterr().out


def test_direct_single_token_invalid_name(bgo, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["bgo", "foo/bar"])
    rc = bgo.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "invalid process name" in out


def test_logs_rejects_invalid_name(bgo, capsys):
    rc = bgo.cmd_logs(argparse.Namespace(
        name="../x", follow=False, lines=10, stdout=False, stderr=False, watcher=False
    ))
    assert rc == 1
    assert "invalid process name" in capsys.readouterr().out


# --- H3/M1: observed-dead write-back marks "crashed", races are skipped ---


def test_status_snapshot_marks_observed_dead_as_crashed(bgo, monkeypatch):
    bgo.save_proc("web", _running_info())
    monkeypatch.setattr(bgo, "is_running", lambda _pid, expected_start=None: False)
    monkeypatch.setattr(bgo, "get_process_info_batch", lambda _pids: {})

    rows = bgo._status_snapshot({"web": bgo.load_proc("web")}, persist=True)

    assert rows[0]["status"] == "stopped"
    saved = bgo.load_proc("web")
    assert saved["status"] == "stopped"
    assert saved["stop_reason"] == "crashed"


def test_status_snapshot_skips_writeback_when_pid_changed(bgo, monkeypatch):
    """A watcher restarting the proc between liveness check and save
    must not have its fresh state clobbered by the stale write-back."""
    bgo.save_proc("web", _running_info())
    monkeypatch.setattr(bgo, "is_running", lambda _pid, expected_start=None: False)
    monkeypatch.setattr(bgo, "get_process_info_batch", lambda _pids: {})
    # On-disk state now carries a NEW pid (watcher won the race).
    monkeypatch.setattr(
        bgo, "load_proc",
        lambda _name: {"name": "web", "pid": 200, "status": "running"},
    )
    saves = []
    monkeypatch.setattr(bgo, "save_proc", lambda n, i: saves.append((n, i)))

    rows = bgo._status_snapshot({"web": _running_info()}, persist=True)

    assert rows[0]["status"] == "stopped"  # snapshot still reports what we saw
    assert saves == []  # but nothing was persisted over the fresh state


def test_resurrect_skips_only_user_stops(bgo, monkeypatch):
    """stop_reason contract: crashed -> resurrected, user -> skipped,
    legacy absent -> skipped (old behavior preserved)."""
    bgo.save_proc("crashed", {
        "name": "crashed", "pid": 1, "status": "stopped",
        "stop_reason": "crashed", "command": ["true"], "autostart": "unless-stopped",
    })
    bgo.save_proc("userstop", {
        "name": "userstop", "pid": 2, "status": "stopped",
        "stop_reason": "user", "command": ["true"], "autostart": "unless-stopped",
    })
    bgo.save_proc("legacy", {
        "name": "legacy", "pid": 3, "status": "stopped",
        "command": ["true"], "autostart": "unless-stopped",
    })
    monkeypatch.setattr(bgo, "is_running", lambda _pid, expected_start=None: False)
    started = []
    monkeypatch.setattr(bgo, "cmd_start", lambda args: started.append(args.name) or 0)

    rc = bgo.cmd_resurrect(argparse.Namespace())

    assert rc == 0
    assert started == ["crashed"]


# --- M7: stop only marks stopped after the kill succeeds ---


def test_stop_failure_leaves_state_running_and_watched(bgo, monkeypatch, capsys):
    info = _running_info()
    info["watch"] = {"enabled": True, "watcher_pid": 200, "watcher_pgid": 200}
    bgo.save_proc("web", info)
    monkeypatch.setattr(bgo, "is_running", lambda pid, expected_start=None: pid in (100, 200))
    watcher_kills = []
    monkeypatch.setattr(bgo, "_kill_watcher", lambda i: watcher_kills.append(i))
    monkeypatch.setattr(bgo, "kill_process", lambda pid, pgid, force=False, expected_start=None: False)

    rc = bgo.cmd_stop(argparse.Namespace(name="web", force=False))

    assert rc == 1
    assert "Failed to stop" in capsys.readouterr().out
    saved = bgo.load_proc("web")
    assert saved["status"] == "running"
    assert "stop_reason" not in saved
    assert saved["watch"]["watcher_pid"] == 200
    assert watcher_kills == []


def test_stop_success_marks_user_then_kills_watcher(bgo, monkeypatch):
    info = _running_info()
    info["watch"] = {"enabled": True, "watcher_pid": 200, "watcher_pgid": 200}
    bgo.save_proc("web", info)
    monkeypatch.setattr(bgo, "is_running", lambda pid, expected_start=None: pid in (100, 200))
    events = []

    def fake_kill_watcher(i):
        # By the time the watcher is killed the state must already say stopped.
        events.append(("kill_watcher", bgo.load_proc("web")["status"]))

    monkeypatch.setattr(bgo, "_kill_watcher", fake_kill_watcher)
    monkeypatch.setattr(bgo, "kill_process", lambda pid, pgid, force=False, expected_start=None: True)

    rc = bgo.cmd_stop(argparse.Namespace(name="web", force=False))

    assert rc == 0
    assert events == [("kill_watcher", "stopped")]
    saved = bgo.load_proc("web")
    assert saved["status"] == "stopped"
    assert saved["stop_reason"] == "user"
    assert saved.get("stopped_at")


def test_stop_already_dead_kills_watcher_and_marks_user(bgo, monkeypatch):
    info = _stopped_info()
    info["watch"] = {"enabled": True, "watcher_pid": 200, "watcher_pgid": 200}
    bgo.save_proc("web", info)
    monkeypatch.setattr(bgo, "is_running", lambda _pid, expected_start=None: False)
    watcher_kills = []
    monkeypatch.setattr(bgo, "_kill_watcher", lambda i: watcher_kills.append(i))

    rc = bgo.cmd_stop(argparse.Namespace(name="web", force=False))

    assert rc == 0
    assert watcher_kills != []
    saved = bgo.load_proc("web")
    assert saved["status"] == "stopped"
    assert saved["stop_reason"] == "user"


# --- M5: delete marks stopped -> kills watcher -> kills proc -> unlinks ---


def test_delete_marks_stopped_before_killing(bgo, monkeypatch):
    info = _running_info()
    info["watch"] = {"enabled": True, "watcher_pid": 200, "watcher_pgid": 200}
    bgo.save_proc("web", info)
    monkeypatch.setattr(bgo, "is_running", lambda pid, expected_start=None: pid in (100, 200))
    events = []

    def fake_kill_watcher(i):
        on_disk = bgo.load_proc("web")
        events.append(("kill_watcher", on_disk["status"], on_disk.get("stop_reason")))

    def fake_kill_process(pid, pgid, force=False, expected_start=None):
        events.append(("kill_proc", pid))
        return True

    monkeypatch.setattr(bgo, "_kill_watcher", fake_kill_watcher)
    monkeypatch.setattr(bgo, "kill_process", fake_kill_process)

    rc = bgo.cmd_delete(argparse.Namespace(name="web", yes=True, keep_logs=False))

    assert rc == 0
    # Watcher kill happens after the stopped+user write; proc kill after that.
    assert events == [("kill_watcher", "stopped", "user"), ("kill_proc", 100)]
    assert bgo.load_proc("web") is None


def test_delete_eof_on_stdin_cancels_cleanly(bgo, monkeypatch, capsys):
    bgo.save_proc("web", _running_info())
    monkeypatch.setattr(bgo, "is_running", lambda _pid, expected_start=None: True)

    def eof_input(_prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof_input)
    rc = bgo.cmd_delete(argparse.Namespace(name="web", yes=False, keep_logs=False))

    assert rc == 0
    assert "Cancelled" in capsys.readouterr().out
    assert bgo.load_proc("web") is not None


# --- H1: cmd_start kills a stale watcher before spawning a new one ---


def test_start_kills_stale_watcher_before_spawning(bgo, monkeypatch):
    existing = _stopped_info()
    existing["watch"] = {
        "enabled": True,
        "watcher_pid": 999,
        "watcher_pgid": 999,
        "interval": 3,
        "min_uptime": 2,
        "on_fast_crash": "backoff",
    }
    bgo.save_proc("web", existing)
    # Old proc (pid 100) is dead; everything else (old watcher 999, the
    # real spawned proc) reports alive.
    monkeypatch.setattr(bgo, "is_running", lambda pid, expected_start=None: pid != 100)
    events = []
    monkeypatch.setattr(bgo, "_kill_watcher", lambda i: events.append("kill"))
    monkeypatch.setattr(
        bgo, "_spawn_watcher", lambda _name: events.append("spawn") or (555, 555)
    )

    rc = bgo.cmd_start(_start_ns())

    assert rc == 0
    assert events == ["kill", "spawn"]
    saved = bgo.load_proc("web")
    assert saved["watch"]["watcher_pid"] == 555
    assert "stop_reason" not in saved  # successful (re)start clears it
    bgo.cmd_stop(argparse.Namespace(name="web", force=True))


# --- pid_start recording on start ---


def test_start_records_pid_start(bgo, monkeypatch):
    monkeypatch.setattr(bgo, "is_running", lambda _pid, expected_start=None: True)
    rc = bgo.cmd_start(_start_ns(name="demo"))
    assert rc == 0

    info = bgo.load_proc("demo")
    expected = subprocess.run(
        ["ps", "-o", "lstart=", "-p", str(info["pid"])],
        capture_output=True, text=True,
    ).stdout.strip()
    assert expected  # sanity: ps probe works on this platform
    assert info.get("pid_start") == expected
    bgo.cmd_stop(argparse.Namespace(name="demo", force=True))


# --- L10: direct mode no longer eats the managed command's -w ---


def test_direct_mode_keeps_command_w_flag(bgo, monkeypatch):
    calls = []
    monkeypatch.setattr(bgo, "cmd_start", lambda args: calls.append(args) or 0)
    monkeypatch.setattr(bgo, "load_proc", lambda _name: None)
    monkeypatch.setattr(sys, "argv", ["bgo", "ping", "-w", "5", "localhost"])
    bgo.main()
    assert len(calls) == 1
    assert calls[0].command == ["ping", "-w", "5", "localhost"]
    assert calls[0].watch is False


def test_direct_mode_separator_keeps_command_w_flag(bgo, monkeypatch):
    calls = []
    monkeypatch.setattr(bgo, "cmd_start", lambda args: calls.append(args) or 0)
    monkeypatch.setattr(bgo, "load_proc", lambda _name: None)
    monkeypatch.setattr(sys, "argv", ["bgo", "myapp", "--", "ping", "-w", "5", "localhost"])
    bgo.main()
    assert len(calls) == 1
    assert calls[0].name == "myapp"
    assert calls[0].command == ["ping", "-w", "5", "localhost"]
    assert calls[0].watch is False


def test_direct_mode_leading_w_flag_still_works(bgo, monkeypatch):
    calls = []
    monkeypatch.setattr(bgo, "cmd_start", lambda args: calls.append(args) or 0)
    monkeypatch.setattr(bgo, "load_proc", lambda _name: None)
    monkeypatch.setattr(sys, "argv", ["bgo", "-w", "myapp", "--", "python3", "server.py"])
    bgo.main()
    assert len(calls) == 1
    assert calls[0].name == "myapp"
    assert calls[0].watch is True


# --- L9: cmd_logs tails from the end instead of slurping ---


def test_logs_tails_large_file(bgo, capsys):
    bgo.save_proc("web", _running_info())
    out = bgo.log_path("web", "out")
    # ~46KB: forces the chunked seek-from-end path (> 8192 bytes).
    lines = [f"line{i:04d} " + "x" * 200 for i in range(200)]
    out.write_text("\n".join(lines) + "\n")

    bgo.cmd_logs(argparse.Namespace(
        name="web", follow=False, lines=5, stdout=True, stderr=False, watcher=False
    ))
    text = capsys.readouterr().out
    assert "showing last 5 lines" in text
    assert "line0199" in text
    assert "line0195" in text
    assert "line0194" not in text
    assert "line0000" not in text


def test_logs_tail_without_trailing_newline(bgo, capsys):
    bgo.save_proc("web", _running_info())
    bgo.log_path("web", "out").write_text("aaa\nbbb\nccc")

    bgo.cmd_logs(argparse.Namespace(
        name="web", follow=False, lines=2, stdout=True, stderr=False, watcher=False
    ))
    text = capsys.readouterr().out
    assert "bbb\nccc" in text
    assert "aaa" not in text


def test_logs_small_file_no_truncation_notice(bgo, capsys):
    bgo.save_proc("web", _running_info())
    bgo.log_path("web", "out").write_text("one\ntwo\n")

    bgo.cmd_logs(argparse.Namespace(
        name="web", follow=False, lines=50, stdout=True, stderr=False, watcher=False
    ))
    text = capsys.readouterr().out
    assert "one\ntwo\n" in text
    assert "showing last" not in text


def test_logs_stderr_companion_is_tailed(bgo, capsys):
    bgo.save_proc("web", _running_info())
    bgo.log_path("web", "out").write_text("out-line\n")
    bgo.log_path("web", "err").write_text(
        "\n".join(f"err{i}" for i in range(30)) + "\n"
    )

    bgo.cmd_logs(argparse.Namespace(
        name="web", follow=False, lines=3, stdout=False, stderr=False, watcher=False
    ))
    text = capsys.readouterr().out
    assert "stderr" in text
    assert "err29" in text
    assert "err27" in text
    assert "err26" not in text


# --- L13: watch cell renders honestly when the watcher never spawned ---


def test_watch_cell_without_watcher_pid_is_not_green(bgo, monkeypatch):
    cell = bgo._watch_cell(
        {"watch": {"enabled": True, "watcher_pid": None, "restarts": 0}},
        level="plain",
    )
    assert "no watcher" in bgo.strip_ansi(cell)

    monkeypatch.setattr(bgo, "is_running", lambda _pid, expected_start=None: True)
    cell = bgo._watch_cell(
        {"watch": {"enabled": True, "watcher_pid": 123, "restarts": 2}},
        level="plain",
    )
    assert "[W] 2" in bgo.strip_ansi(cell)


# --- H4: tray probes for the real dependency, one-shot auto-install ---


@pytest.fixture
def _find_spec_patched(monkeypatch):
    """Patch importlib.util.find_spec; returns a setter for the PySide6 result."""
    real_find_spec = importlib.util.find_spec

    def set_result(result):
        monkeypatch.setattr(
            importlib.util,
            "find_spec",
            lambda name, *a, **k: result if name == "PySide6" else real_find_spec(name, *a, **k),
        )

    return set_result


def test_tray_autoinstall_fires_when_pyside6_missing(bgo, monkeypatch, _find_spec_patched):
    import bgo_cli._tray_install as tray_install

    _find_spec_patched(None)
    monkeypatch.delenv("BGO_TRAY_AUTOINSTALL_DONE", raising=False)
    monkeypatch.delenv("BGO_TRAY_AUTOINSTALL", raising=False)
    ensure_calls = []
    monkeypatch.setattr(
        tray_install, "ensure_installed",
        lambda auto=False: ensure_calls.append(auto) or True,
    )
    exec_calls = []
    monkeypatch.setattr(bgo.os, "execvp", lambda *a: exec_calls.append(a))

    rc = bgo.cmd_tray(argparse.Namespace(poll=None, auto_install=True))

    assert rc == 0
    assert ensure_calls == [True]
    assert len(exec_calls) == 1
    # Sentinel is set before the re-exec so the next process won't loop.
    assert bgo.os.environ.get("BGO_TRAY_AUTOINSTALL_DONE") == "1"


def test_tray_autoinstall_one_shot_guard(bgo, monkeypatch, capsys, _find_spec_patched):
    _find_spec_patched(None)
    monkeypatch.setenv("BGO_TRAY_AUTOINSTALL_DONE", "1")
    exec_calls = []
    monkeypatch.setattr(bgo.os, "execvp", lambda *a: exec_calls.append(a))

    rc = bgo.cmd_tray(argparse.Namespace(poll=None, auto_install=True))

    out = capsys.readouterr().out
    assert rc == 1
    assert "manually" in out
    assert exec_calls == []


def test_tray_runs_when_pyside6_present(bgo, monkeypatch, _find_spec_patched):
    import bgo_cli._tray as tray_mod

    _find_spec_patched(object())
    runs = []
    monkeypatch.setattr(tray_mod, "run", lambda poll_seconds=None: runs.append(poll_seconds) or 0)

    rc = bgo.cmd_tray(argparse.Namespace(poll=5, auto_install=False))

    assert rc == 0
    assert runs == [5]


# --- H5: bare script without the package fails with a clean message ---


def test_standalone_script_without_package_prints_friendly_error():
    repo = Path(__file__).resolve().parent.parent
    script = repo / "bgo"
    runner = (
        "import sys\n"
        "sys.modules['bgo_cli'] = None\n"
        "sys.modules['bgo_cli._state'] = None\n"
        f"source = open({str(script)!r}).read()\n"
        "exec(compile(source, 'bgo', 'exec'), {'__name__': '__main__'})\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", runner],
        capture_output=True, text=True, cwd=repo,
    )
    assert proc.returncode == 1
    assert "bgo requires the bgo-cli package" in proc.stderr
    assert "Traceback" not in proc.stderr
