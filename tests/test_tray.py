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


@pytest.mark.parametrize(
    ("status", "errored", "expected_glyph"),
    [
        ("running", False, "●"),
        ("running", True, "⚠"),
        ("stopped", False, "○"),
    ],
)
def test_status_glyph_matrix(status: str, errored: bool, expected_glyph: str) -> None:
    """Each status maps to a distinct Unicode glyph for the menu."""
    snap = _tray.ProcSnapshot("x", status, 1, errored=errored)
    assert _tray._status_glyph(snap) == expected_glyph


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


# --- _run_bgo_in_thread ---------------------------------------------------


def test_run_bgo_in_thread_reports_rc_via_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worker thread runs run_bgo with the given args and hands the
    exit code to ``on_done`` — the seam the Qt Signal bridge relies on."""
    seen: dict[str, object] = {}

    def fake_run_bgo(*args: str) -> int:
        seen["args"] = args
        return 42

    monkeypatch.setattr(_tray, "run_bgo", fake_run_bgo)
    results: list[int] = []
    thread = _tray._run_bgo_in_thread("restart", "web", on_done=results.append)
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert seen["args"] == ("restart", "web")
    assert results == [42]


# --- _resolve_terminal --------------------------------------------------


def test_resolve_terminal_returns_none_when_nothing_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BGO_TERMINAL", raising=False)
    monkeypatch.setattr(_tray.shutil, "which", lambda _: None)
    assert _tray._resolve_terminal() is None


def test_resolve_terminal_picks_first_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Probes in order; the first hit wins."""
    monkeypatch.delenv("BGO_TERMINAL", raising=False)

    # Only ``foot`` is on PATH — it should win over later xterm even
    # though both are in the candidate list.
    def fake_which(binary: str) -> str | None:
        return "/usr/bin/foot" if binary == "foot" else None

    monkeypatch.setattr(_tray.shutil, "which", side_effect=fake_which) \
        if hasattr(monkeypatch, "setattr_side_effect") else monkeypatch.setattr(
            _tray.shutil, "which", fake_which
        )
    result = _tray._resolve_terminal()
    assert result == ("foot", "--")


def test_resolve_terminal_honors_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BGO_TERMINAL", "alacritty -e")
    monkeypatch.setattr(_tray.shutil, "which", lambda _: "/usr/bin/alacritty")
    assert _tray._resolve_terminal() == ("alacritty", "-e")


def test_resolve_terminal_override_defaults_to_dash_e_when_unspecified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BGO_TERMINAL", "weirdterm")
    monkeypatch.setattr(_tray.shutil, "which", lambda _: "/x/weirdterm")
    assert _tray._resolve_terminal() == ("weirdterm", "-e")


def test_resolve_terminal_override_not_found_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit override misses -> None, not silent fallback."""
    monkeypatch.setenv("BGO_TERMINAL", "missing-term")
    monkeypatch.setattr(_tray.shutil, "which", lambda _: None)
    assert _tray._resolve_terminal() is None


# --- _open_logs ---------------------------------------------------------


def test_open_logs_warns_when_no_log_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Missing log file -> stderr hint, no terminal launched."""
    monkeypatch.setattr(_tray, "BGO_DIR", tmp_path)
    with mock.patch.object(_tray.subprocess, "Popen") as popen:
        _tray._open_logs("nope")
    popen.assert_not_called()
    err = capsys.readouterr().err
    assert "no log file" in err


def test_open_logs_linux_spawns_terminal_with_follow_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Linux path: invoke the resolved terminal with ``bgo logs <name> -f``."""
    monkeypatch.setattr(_tray, "BGO_DIR", tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "web.out.log").write_text("")
    monkeypatch.setattr(_tray.sys, "platform", "linux")
    monkeypatch.setattr(_tray.shutil, "which", lambda b: "/bin/bgo" if b == "bgo" else "/usr/bin/kitty")
    monkeypatch.setattr(_tray, "_resolve_terminal", lambda: ("kitty", "--"))
    with mock.patch.object(_tray.subprocess, "Popen") as popen:
        _tray._open_logs("web")
    popen.assert_called_once()
    argv = popen.call_args.args[0]
    assert argv[0] == "kitty"
    assert argv[1] == "--"
    assert argv[-3:] == ["logs", "web", "-f"]


def test_open_logs_linux_no_terminal_writes_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(_tray, "BGO_DIR", tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "web.out.log").write_text("")
    monkeypatch.setattr(_tray.sys, "platform", "linux")
    monkeypatch.setattr(_tray, "_resolve_terminal", lambda: None)
    with mock.patch.object(_tray.subprocess, "Popen") as popen:
        _tray._open_logs("web")
    popen.assert_not_called()
    err = capsys.readouterr().err
    assert "BGO_TERMINAL" in err


def test_open_logs_darwin_uses_osascript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_tray, "BGO_DIR", tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "api.out.log").write_text("")
    monkeypatch.setattr(_tray.sys, "platform", "darwin")
    monkeypatch.delenv("BGO_TERMINAL", raising=False)
    monkeypatch.setattr(_tray.shutil, "which", lambda _: "/bin/bgo")
    with mock.patch.object(_tray.subprocess, "Popen") as popen:
        _tray._open_logs("api")
    argv = popen.call_args.args[0]
    assert argv[0] == "osascript"
    assert "Terminal" in argv[-1]
    assert "logs api -f" in argv[-1]


# --- _aggregate_status --------------------------------------------------


def test_aggregate_status_empty_is_idle() -> None:
    assert _tray._aggregate_status([]) == "idle"


def test_aggregate_status_all_stopped_is_idle() -> None:
    snaps = [
        _tray.ProcSnapshot("a", "stopped", None, errored=False),
        _tray.ProcSnapshot("b", "stopped", None, errored=False),
    ]
    assert _tray._aggregate_status(snaps) == "idle"


def test_aggregate_status_any_running_is_online() -> None:
    snaps = [
        _tray.ProcSnapshot("a", "stopped", None, errored=False),
        _tray.ProcSnapshot("b", "running", 100, errored=False),
    ]
    assert _tray._aggregate_status(snaps) == "online"


def test_aggregate_status_errored_dominates_running() -> None:
    """Errored is highest priority, even if other procs are healthy."""
    snaps = [
        _tray.ProcSnapshot("a", "running", 100, errored=False),
        _tray.ProcSnapshot("b", "stopped", None, errored=True),
    ]
    assert _tray._aggregate_status(snaps) == "errored"


# --- _icon_svg ----------------------------------------------------------


def test_icon_svg_embeds_requested_color() -> None:
    """The dot color reaches the rendered SVG verbatim."""
    svg = _tray._icon_svg("#3ddc84")
    assert b'fill="#3ddc84"' in svg
    assert svg.startswith(b"<?xml")


def test_icon_svg_known_status_colors_unique() -> None:
    """Three statuses produce three distinct icons."""
    seen = {_tray._icon_svg(c) for c in _tray._DOT_COLORS.values()}
    assert len(seen) == len(_tray._DOT_COLORS)


def test_open_logs_darwin_iterm_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_tray, "BGO_DIR", tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "api.out.log").write_text("")
    monkeypatch.setattr(_tray.sys, "platform", "darwin")
    monkeypatch.setenv("BGO_TERMINAL", "iterm")
    monkeypatch.setattr(_tray.shutil, "which", lambda _: "/bin/bgo")
    with mock.patch.object(_tray.subprocess, "Popen") as popen:
        _tray._open_logs("api")
    argv = popen.call_args.args[0]
    assert "iTerm" in argv[-1]


