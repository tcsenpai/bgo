"""Tests for ``bgo_cli._autostart``.

All filesystem writes target ``tmp_path``. All service-manager calls
(``systemctl``, ``launchctl``) are mocked. No real autostart entry is
ever installed on the test host.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from bgo_cli import _autostart, _proc


@pytest.fixture
def linux_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pretend we're on Linux and reroute config dirs to ``tmp_path``."""
    monkeypatch.setattr(_autostart.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(_autostart.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(_proc.shutil, "which", lambda _name: "/usr/local/bin/bgo")
    return tmp_path


@pytest.fixture
def darwin_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pretend we're on macOS and reroute ``$HOME`` to ``tmp_path``."""
    monkeypatch.setattr(_autostart.sys, "platform", "darwin")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(_autostart.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(_proc.shutil, "which", lambda _name: "/opt/bin/bgo")
    return tmp_path


# --- Backend detection ---------------------------------------------------


def test_detect_backend_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_autostart.sys, "platform", "linux")
    assert _autostart.detect_backend() == "systemd-user"


def test_detect_backend_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_autostart.sys, "platform", "darwin")
    assert _autostart.detect_backend() == "launchd"


def test_detect_backend_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_autostart.sys, "platform", "win32")
    assert _autostart.detect_backend() is None


# --- Path resolution -----------------------------------------------------


def test_path_systemd_resurrect(linux_env: Path) -> None:
    path = _autostart._path_for("systemd-user", "resurrect")
    assert path == linux_env / "config" / "systemd" / "user" / "bgo-resurrect.service"


def test_path_systemd_tray(linux_env: Path) -> None:
    path = _autostart._path_for("systemd-user", "tray")
    assert path == linux_env / "config" / "autostart" / "bgo-tray.desktop"


def test_path_launchd_resurrect(darwin_env: Path) -> None:
    path = _autostart._path_for("launchd", "resurrect")
    assert path == darwin_env / "Library" / "LaunchAgents" / "sh.discus.bgo.resurrect.plist"


def test_path_launchd_tray(darwin_env: Path) -> None:
    path = _autostart._path_for("launchd", "tray")
    assert path == darwin_env / "Library" / "LaunchAgents" / "sh.discus.bgo.tray.plist"


# --- Rendering -----------------------------------------------------------


def test_render_systemd_unit_embeds_bgo_path() -> None:
    content = _autostart._render_systemd_unit("/usr/local/bin/bgo")
    assert "ExecStart=/usr/local/bin/bgo resurrect" in content
    assert "[Install]" in content
    assert "WantedBy=default.target" in content


def test_render_xdg_desktop_embeds_bgo_path() -> None:
    content = _autostart._render_xdg_desktop("/opt/bgo")
    assert "Exec=/opt/bgo tray" in content
    assert "Type=Application" in content


def test_render_launchd_plist_resurrect() -> None:
    content = _autostart._render_launchd_plist("resurrect", "/opt/bgo")
    assert "sh.discus.bgo.resurrect" in content
    assert "<string>/opt/bgo</string>" in content
    assert "<string>resurrect</string>" in content
    assert "<key>RunAtLoad</key><true/>" in content


def test_render_launchd_plist_tray() -> None:
    content = _autostart._render_launchd_plist("tray", "/opt/bgo")
    assert "sh.discus.bgo.tray" in content
    assert "<string>tray</string>" in content


# --- Atomic write --------------------------------------------------------


def test_write_file_creates_parents_and_content(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c.txt"
    _autostart._write_file(target, "hello\n")
    assert target.read_text() == "hello\n"


def test_write_file_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "f"
    _autostart._write_file(target, "first")
    _autostart._write_file(target, "second")
    assert target.read_text() == "second"


# --- install / uninstall (linux) ----------------------------------------


def test_install_resurrect_linux_writes_unit_and_enables(linux_env: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str]) -> tuple[int, str]:
        calls.append(argv)
        return 0, ""

    with mock.patch.object(_autostart, "_run", side_effect=fake_run):
        ok, msg = _autostart.install("resurrect")

    assert ok, msg
    unit = linux_env / "config" / "systemd" / "user" / "bgo-resurrect.service"
    assert unit.exists()
    assert "ExecStart=/usr/local/bin/bgo resurrect" in unit.read_text()
    assert calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "bgo-resurrect.service"],
    ]


def test_install_resurrect_linux_propagates_systemctl_failure(linux_env: Path) -> None:
    with mock.patch.object(
        _autostart, "_run", return_value=(1, "boom")
    ):
        ok, msg = _autostart.install("resurrect")
    assert ok is False
    assert "daemon-reload failed" in msg


def test_install_tray_linux_writes_desktop_entry_no_systemctl(linux_env: Path) -> None:
    with mock.patch.object(_autostart, "_run") as run:
        ok, msg = _autostart.install("tray")
    assert ok, msg
    run.assert_not_called()
    desktop = linux_env / "config" / "autostart" / "bgo-tray.desktop"
    assert desktop.exists()
    assert "Exec=/usr/local/bin/bgo tray" in desktop.read_text()


def test_uninstall_resurrect_linux_removes_unit(linux_env: Path) -> None:
    unit = linux_env / "config" / "systemd" / "user" / "bgo-resurrect.service"
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text("dummy")

    with mock.patch.object(_autostart, "_run", return_value=(0, "")):
        ok, msg = _autostart.uninstall("resurrect")

    assert ok, msg
    assert not unit.exists()


def test_uninstall_tray_linux_removes_desktop_entry(linux_env: Path) -> None:
    desktop = linux_env / "config" / "autostart" / "bgo-tray.desktop"
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text("dummy")

    ok, _ = _autostart.uninstall("tray")
    assert ok
    assert not desktop.exists()


def test_uninstall_idempotent_when_missing(linux_env: Path) -> None:
    with mock.patch.object(_autostart, "_run", return_value=(0, "")):
        ok, _ = _autostart.uninstall("resurrect")
    assert ok


# --- install / uninstall (darwin) ---------------------------------------


def test_install_resurrect_darwin_writes_plist_and_bootstraps(darwin_env: Path) -> None:
    with mock.patch.object(_autostart, "_run", return_value=(0, "")) as run:
        ok, msg = _autostart.install("resurrect")
    assert ok, msg
    plist = darwin_env / "Library" / "LaunchAgents" / "sh.discus.bgo.resurrect.plist"
    assert plist.exists()
    # First call should be the bootstrap; we don't check the exact uid
    # because os.getuid() varies in CI.
    first = run.call_args_list[0].args[0]
    assert first[0:2] == ["launchctl", "bootstrap"]
    assert first[-1] == str(plist)


def test_install_darwin_falls_back_to_legacy_load(darwin_env: Path) -> None:
    def fake_run(argv: list[str]) -> tuple[int, str]:
        if argv[1] == "bootstrap":
            return 1, "already loaded"
        if argv[1] == "load":
            return 0, ""
        return 0, ""

    with mock.patch.object(_autostart, "_run", side_effect=fake_run):
        ok, msg = _autostart.install("resurrect")
    assert ok, msg


def test_install_darwin_reports_both_failures(darwin_env: Path) -> None:
    with mock.patch.object(_autostart, "_run", return_value=(1, "nope")):
        ok, msg = _autostart.install("resurrect")
    assert ok is False
    assert "bootstrap failed" in msg
    assert "load failed" in msg


def test_uninstall_darwin_removes_plist(darwin_env: Path) -> None:
    plist = darwin_env / "Library" / "LaunchAgents" / "sh.discus.bgo.tray.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text("dummy")
    with mock.patch.object(_autostart, "_run", return_value=(0, "")):
        ok, _ = _autostart.uninstall("tray")
    assert ok
    assert not plist.exists()


def test_launchctl_unload_falls_back_to_legacy(tmp_path: Path) -> None:
    """``bootout`` failing triggers a ``unload -w`` retry."""
    calls: list[list[str]] = []

    def fake_run(argv: list[str]) -> tuple[int, str]:
        calls.append(argv)
        if argv[1] == "bootout":
            return 1, "bootout: not supported"
        return 0, ""  # unload succeeds

    with mock.patch.object(_autostart, "_run", side_effect=fake_run):
        ok, _ = _autostart._launchctl_unload(tmp_path / "x.plist")
    assert ok is True
    assert calls[0][1] == "bootout"
    assert calls[1][1] == "unload"


def test_launchctl_unload_treats_missing_agent_as_success(tmp_path: Path) -> None:
    """``Could not find specified service`` is benign — idempotent uninstall."""
    def fake_run(argv: list[str]) -> tuple[int, str]:
        return 1, "Could not find specified service"

    with mock.patch.object(_autostart, "_run", side_effect=fake_run):
        ok, msg = _autostart._launchctl_unload(tmp_path / "x.plist")
    assert ok is True
    assert msg == ""


def test_launchctl_unload_surfaces_real_failure(tmp_path: Path) -> None:
    """Both bootout and unload failing with unknown errors -> ok=False."""
    def fake_run(argv: list[str]) -> tuple[int, str]:
        return 1, "permission denied"

    with mock.patch.object(_autostart, "_run", side_effect=fake_run):
        ok, msg = _autostart._launchctl_unload(tmp_path / "x.plist")
    assert ok is False
    assert "permission denied" in msg


# --- status --------------------------------------------------------------


def test_status_reports_nothing_installed(linux_env: Path) -> None:
    s = _autostart.status()
    assert s["backend"] == "systemd-user"
    assert s["resurrect"] is False
    assert s["tray"] is False
    assert s["resurrect_path"] is None


def test_status_reports_installed_paths(linux_env: Path) -> None:
    unit = _autostart._path_for("systemd-user", "resurrect")
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text("x")
    s = _autostart.status()
    assert s["resurrect"] is True
    assert s["resurrect_path"] == str(unit)


def test_status_unsupported_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_autostart.sys, "platform", "win32")
    s = _autostart.status()
    assert s["backend"] is None
    assert s["resurrect"] is False
    assert s["tray"] is False


# --- _resolve_bgo_binary --------------------------------------------------


def test_resolve_bgo_binary_prefers_which(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_proc.shutil, "which", lambda _: "/found/bgo")
    assert _autostart._resolve_bgo_binary() == "/found/bgo"


def test_resolve_bgo_binary_falls_back_to_argv0(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = tmp_path / "bgo"
    fake.touch()
    monkeypatch.setattr(_proc.shutil, "which", lambda _: None)
    monkeypatch.setattr(_proc.sys, "argv", [str(fake)])
    assert _autostart._resolve_bgo_binary() == str(fake.resolve())
