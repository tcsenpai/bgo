"""Tests for ``bgo_cli._notify``.

These tests mock platform detection (``sys.platform``), binary
discovery (``shutil.which``), and subprocess invocation. They never
fire a real notification.
"""

from __future__ import annotations

from unittest import mock

import pytest

from bgo_cli import _notify


# --- Gate logic ----------------------------------------------------------


@pytest.mark.parametrize(
    ("env", "level", "expected"),
    [
        ("off", "error", False),
        ("off", "info", False),
        ("errors", "error", True),
        ("errors", "warn", False),
        ("errors", "info", False),
        ("all", "info", True),
        ("all", "warn", True),
        ("all", "error", True),
        ("", "error", True),  # default == errors
        ("", "info", False),
        ("garbage", "info", False),  # garbage -> default
        ("garbage", "error", True),
    ],
)
def test_should_fire_respects_gate(env: str, level: str, expected: bool) -> None:
    """The gate env var controls which levels pass through."""
    with mock.patch.dict(_notify.os.environ, {"BGO_NOTIFY": env}, clear=False):
        assert _notify._should_fire(level) is expected  # type: ignore[arg-type]


# --- Backend resolution --------------------------------------------------


def test_resolve_backend_override_wins() -> None:
    """``$BGO_NOTIFY_CMD`` short-circuits platform detection."""
    env = {"BGO_NOTIFY_CMD": "my-notifier {title} {body}"}
    with mock.patch.dict(_notify.os.environ, env, clear=False):
        result = _notify._resolve_backend()
    assert result is not None
    kind, argv = result
    assert kind == "override"
    assert argv == ("my-notifier", "{title}", "{body}")


def test_resolve_backend_override_respects_quotes() -> None:
    """Quoted args in ``$BGO_NOTIFY_CMD`` stay grouped."""
    env = {"BGO_NOTIFY_CMD": '"/opt/bin/notify ng" --json {title}'}
    with mock.patch.dict(_notify.os.environ, env, clear=False):
        result = _notify._resolve_backend()
    assert result is not None
    kind, argv = result
    assert kind == "override"
    assert argv == ("/opt/bin/notify ng", "--json", "{title}")


def test_resolve_backend_override_with_unbalanced_quotes_falls_through(
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    """Malformed override is ignored; platform detection still runs."""
    monkeypatch.setenv("BGO_NOTIFY_CMD", 'broken "quote')
    monkeypatch.setattr(_notify.sys, "platform", "linux")
    monkeypatch.setattr(_notify.shutil, "which", lambda _name: None)
    assert _notify._resolve_backend() is None


def test_resolve_backend_linux_notify_send() -> None:
    """On Linux, ``notify-send`` is picked when present."""
    with mock.patch.dict(_notify.os.environ, {}, clear=True), \
         mock.patch.object(_notify.sys, "platform", "linux"), \
         mock.patch.object(_notify.shutil, "which", return_value="/usr/bin/notify-send"):
        result = _notify._resolve_backend()
    assert result is not None
    kind, _ = result
    assert kind == "notify-send"


def test_resolve_backend_macos_osascript() -> None:
    """On macOS, ``osascript`` is preferred over ``terminal-notifier``."""
    def fake_which(binary: str) -> str | None:
        return "/usr/bin/osascript" if binary == "osascript" else None

    with mock.patch.dict(_notify.os.environ, {}, clear=True), \
         mock.patch.object(_notify.sys, "platform", "darwin"), \
         mock.patch.object(_notify.shutil, "which", side_effect=fake_which):
        result = _notify._resolve_backend()
    assert result is not None
    kind, _ = result
    assert kind == "osascript"


def test_resolve_backend_macos_terminal_notifier_fallback() -> None:
    """Without ``osascript``, ``terminal-notifier`` is used."""
    def fake_which(binary: str) -> str | None:
        return "/opt/bin/terminal-notifier" if binary == "terminal-notifier" else None

    with mock.patch.dict(_notify.os.environ, {}, clear=True), \
         mock.patch.object(_notify.sys, "platform", "darwin"), \
         mock.patch.object(_notify.shutil, "which", side_effect=fake_which):
        result = _notify._resolve_backend()
    assert result is not None
    kind, _ = result
    assert kind == "terminal-notifier"


def test_resolve_backend_none_available() -> None:
    """Returns ``None`` when no backend can be found."""
    with mock.patch.dict(_notify.os.environ, {}, clear=True), \
         mock.patch.object(_notify.sys, "platform", "linux"), \
         mock.patch.object(_notify.shutil, "which", return_value=None):
        assert _notify._resolve_backend() is None


# --- Escaping ------------------------------------------------------------


def test_escape_applescript_quotes_and_backslashes() -> None:
    """AppleScript escaping handles both ``"`` and ``\\``."""
    assert _notify._escape_applescript('he said "hi"\\') == 'he said \\"hi\\"\\\\'


def test_format_argv_substitutes_placeholders() -> None:
    """``{title}`` and ``{body}`` are replaced in non-AppleScript backends."""
    argv = _notify._format_argv(
        ("notify-send", "{title}", "{body}"),
        title="T",
        body="B",
        kind="notify-send",
    )
    assert argv == ["notify-send", "T", "B"]


def test_format_argv_escapes_for_osascript() -> None:
    """AppleScript backend receives pre-escaped placeholders."""
    argv = _notify._format_argv(
        ("osascript", "-e", _notify._OSASCRIPT_TEMPLATE),
        title='a "b"',
        body="c",
        kind="osascript",
    )
    assert argv[0:2] == ["osascript", "-e"]
    assert 'display notification "c"' in argv[2]
    assert 'with title "a \\"b\\""' in argv[2]


# --- End-to-end public API ----------------------------------------------


def test_notify_returns_false_when_gate_off() -> None:
    """``BGO_NOTIFY=off`` short-circuits before backend lookup."""
    with mock.patch.dict(_notify.os.environ, {"BGO_NOTIFY": "off"}, clear=False):
        assert _notify.notify("t", "b", "error") is False


def test_notify_returns_false_when_no_backend() -> None:
    """No reachable binary => silent ``False``, no raise."""
    with mock.patch.dict(_notify.os.environ, {"BGO_NOTIFY": "all"}, clear=False), \
         mock.patch.object(_notify, "_resolve_backend", return_value=None):
        assert _notify.notify("t", "b", "info") is False


def test_notify_runs_backend_and_returns_true_on_success() -> None:
    """Backend invoked with substituted argv; rc=0 maps to ``True``."""
    completed = mock.MagicMock(returncode=0)
    with mock.patch.dict(_notify.os.environ, {"BGO_NOTIFY": "all"}, clear=False), \
         mock.patch.object(
             _notify,
             "_resolve_backend",
             return_value=("notify-send", ("notify-send", "{title}", "{body}")),
         ), \
         mock.patch.object(_notify.subprocess, "run", return_value=completed) as run:
        ok = _notify.notify("hello", "world", "info")
    assert ok is True
    run.assert_called_once()
    argv = run.call_args.args[0]
    assert argv == ["notify-send", "hello", "world"]


def test_notify_subprocess_failure_returns_false() -> None:
    """Non-zero rc => ``False``."""
    completed = mock.MagicMock(returncode=1)
    with mock.patch.dict(_notify.os.environ, {"BGO_NOTIFY": "all"}, clear=False), \
         mock.patch.object(
             _notify,
             "_resolve_backend",
             return_value=("notify-send", ("notify-send", "{title}", "{body}")),
         ), \
         mock.patch.object(_notify.subprocess, "run", return_value=completed):
        assert _notify.notify("t", "b", "info") is False


def test_notify_subprocess_exception_swallowed() -> None:
    """OSError from subprocess is caught; never propagates."""
    with mock.patch.dict(_notify.os.environ, {"BGO_NOTIFY": "all"}, clear=False), \
         mock.patch.object(
             _notify,
             "_resolve_backend",
             return_value=("notify-send", ("notify-send", "{title}", "{body}")),
         ), \
         mock.patch.object(_notify.subprocess, "run", side_effect=OSError("boom")):
        assert _notify.notify("t", "b", "info") is False


def test_notify_unknown_level_treated_as_info() -> None:
    """Out-of-spec level downgrades to info (gated by ``errors`` default)."""
    with mock.patch.dict(_notify.os.environ, {"BGO_NOTIFY": "errors"}, clear=False):
        # info doesn't pass 'errors' gate => returns False without backend
        assert _notify.notify("t", "b", "garbage") is False  # type: ignore[arg-type]
