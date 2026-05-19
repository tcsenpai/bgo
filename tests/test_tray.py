"""Tests for the pure (toolkit-free) helpers in ``bgo_cli._tray``.

Anything that needs ``PySide6`` (Qt) lives in ``_run_tray`` and is
intentionally not covered here — it requires the optional extra
``bgo-cli[tray]`` and is exercised by the smoke-run in a dev install.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from bgo_cli import _tray


# --- load_snapshots ------------------------------------------------------


def _write_proc(d: Path, name: str, **fields: object) -> None:
    """Write a fake proc JSON file."""
    data = {"name": name, "status": "running", "pid": 100, **fields}
    (d / f"{name}.json").write_text(json.dumps(data))


def test_load_snapshots_empty_when_dir_missing(tmp_path: Path) -> None:
    assert _tray.load_snapshots(tmp_path / "nope") == []


def test_load_snapshots_reads_and_sorts(tmp_path: Path) -> None:
    _write_proc(tmp_path, "zeta", pid=2)
    _write_proc(tmp_path, "alpha", pid=1)
    snaps = _tray.load_snapshots(tmp_path)
    assert [s.name for s in snaps] == ["alpha", "zeta"]
    assert snaps[0].pid == 1
    assert snaps[1].pid == 2


def test_load_snapshots_skips_malformed(tmp_path: Path) -> None:
    _write_proc(tmp_path, "good")
    (tmp_path / "bad.json").write_text("{ not json")
    snaps = _tray.load_snapshots(tmp_path)
    assert len(snaps) == 1
    assert snaps[0].name == "good"


def test_load_snapshots_normalizes_missing_fields(tmp_path: Path) -> None:
    (tmp_path / "x.json").write_text(json.dumps({}))
    snaps = _tray.load_snapshots(tmp_path)
    assert len(snaps) == 1
    assert snaps[0].name == "x"
    assert snaps[0].status == "unknown"
    assert snaps[0].pid is None
    assert snaps[0].errored is False


def test_load_snapshots_detects_errored(tmp_path: Path) -> None:
    _write_proc(
        tmp_path,
        "crash",
        status="stopped",
        watch={"enabled": True, "errored": True},
    )
    snaps = _tray.load_snapshots(tmp_path)
    assert snaps[0].errored is True


# --- build_menu_spec -----------------------------------------------------


def test_menu_spec_counts_online_and_stopped() -> None:
    snaps = [
        _tray.ProcSnapshot("a", "running", 1, errored=False),
        _tray.ProcSnapshot("b", "stopped", None, errored=False),
        _tray.ProcSnapshot("c", "running", 3, errored=True),  # errored != online
    ]
    spec = _tray.build_menu_spec(snaps)
    assert spec.title == "bgo — 1 online / 2 stopped"
    assert len(spec.procs) == 3
    labels = [a[0] for a in spec.actions]
    assert labels == ["Resurrect all", "Refresh now", "Quit"]


def test_menu_spec_empty_when_no_procs() -> None:
    spec = _tray.build_menu_spec([])
    assert "0 online / 0 stopped" in spec.title
    assert spec.procs == []


@pytest.mark.parametrize(
    ("status", "errored", "expected"),
    [
        ("running", False, "online"),
        ("running", True, "errored"),
        ("stopped", False, "stopped"),
        ("anything-else", False, "stopped"),
    ],
)
def test_status_label_matrix(status: str, errored: bool, expected: str) -> None:
    snap = _tray.ProcSnapshot("x", status, 1, errored=errored)
    assert _tray._status_label(snap) == expected


# --- _poll_interval -----------------------------------------------------


def test_poll_interval_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BGO_TRAY_POLL", raising=False)
    assert _tray._poll_interval() == _tray._DEFAULT_POLL_SECONDS


def test_poll_interval_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BGO_TRAY_POLL", "10")
    assert _tray._poll_interval() == 10


def test_poll_interval_ignores_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BGO_TRAY_POLL", "garbage")
    assert _tray._poll_interval() == _tray._DEFAULT_POLL_SECONDS


def test_poll_interval_ignores_zero_or_negative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BGO_TRAY_POLL", "0")
    assert _tray._poll_interval() == _tray._DEFAULT_POLL_SECONDS
    monkeypatch.setenv("BGO_TRAY_POLL", "-5")
    assert _tray._poll_interval() == _tray._DEFAULT_POLL_SECONDS


# --- run_bgo -------------------------------------------------------------


def test_run_bgo_invokes_subprocess_with_resolved_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_tray.shutil, "which", lambda _: "/x/bgo")
    completed = mock.MagicMock(returncode=0)
    with mock.patch.object(_tray.subprocess, "run", return_value=completed) as run:
        rc = _tray.run_bgo("restart", "web")
    assert rc == 0
    argv = run.call_args.args[0]
    assert argv == ["/x/bgo", "restart", "web"]


def test_run_bgo_returns_127_on_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_tray.shutil, "which", lambda _: "/x/bgo")
    with mock.patch.object(_tray.subprocess, "run", side_effect=OSError("x")):
        assert _tray.run_bgo("start", "x") == 127


def test_run_bgo_falls_back_to_argv0_when_which_misses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(_tray.shutil, "which", lambda _: None)
    fake = tmp_path / "bgo"
    fake.touch()
    monkeypatch.setattr(_tray.sys, "argv", [str(fake)])
    completed = mock.MagicMock(returncode=0)
    with mock.patch.object(_tray.subprocess, "run", return_value=completed) as run:
        _tray.run_bgo("ls")
    assert run.call_args.args[0][0] == str(fake.resolve())


