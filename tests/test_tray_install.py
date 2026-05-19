"""Tests for ``bgo_cli._tray_install``.

Verifies installer detection from ``sys.prefix``, command construction
per installer kind, and the prompt + subprocess flow when one of
``pystray`` / ``PIL`` is missing.
"""

from __future__ import annotations

from unittest import mock

import pytest

from bgo_cli import _tray_install


# --- detect_installer ---------------------------------------------------


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ("/home/u/.local/share/uv/tools/bgo-cli", "uv"),
        ("/home/u/.local/share/UV/Tools/bgo-cli", "uv"),
        ("/home/u/.local/share/pipx/venvs/bgo-cli", "pipx"),
        ("/usr/local", "pip"),
        ("/home/u/.venv", "pip"),
        ("", "pip"),
    ],
)
def test_detect_installer_from_prefix(
    monkeypatch: pytest.MonkeyPatch, prefix: str, expected: str
) -> None:
    """The path pattern in ``sys.prefix`` selects the installer kind."""
    monkeypatch.setattr(_tray_install.sys, "prefix", prefix)
    monkeypatch.delenv("UV_TOOL_DIR", raising=False)
    assert _tray_install.detect_installer() == expected


def test_detect_installer_honors_uv_tool_dir_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A custom ``UV_TOOL_DIR`` location is detected as uv."""
    monkeypatch.setenv("UV_TOOL_DIR", "/opt/custom/uv-tools")
    monkeypatch.setattr(
        _tray_install.sys, "prefix", "/opt/custom/uv-tools/bgo-cli"
    )
    assert _tray_install.detect_installer() == "uv"


# --- _command_for --------------------------------------------------------


def test_command_for_uv() -> None:
    argv = _tray_install._command_for("uv")
    assert argv[:3] == ["uv", "tool", "install"]
    assert "PySide6" in argv
    assert argv[-1] == "bgo-cli"


def test_command_for_pipx() -> None:
    assert _tray_install._command_for("pipx") == [
        "pipx", "inject", "bgo-cli", "PySide6"
    ]


def test_command_for_pip_uses_current_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_tray_install.sys, "executable", "/python")
    argv = _tray_install._command_for("pip")
    assert argv[:3] == ["/python", "-m", "pip"]
    assert "--user" in argv
    assert "PySide6" in argv


# --- _installer_available -----------------------------------------------


def test_installer_available_uv_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_tray_install.shutil, "which", lambda _: "/usr/bin/uv")
    assert _tray_install._installer_available("uv") is True


def test_installer_available_uv_no(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_tray_install.shutil, "which", lambda _: None)
    assert _tray_install._installer_available("uv") is False


def test_installer_available_pip_always_true() -> None:
    assert _tray_install._installer_available("pip") is True


# --- ensure_installed: short-circuits if deps present -------------------


def test_ensure_installed_short_circuits_when_deps_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If PySide6 imports cleanly, no install command runs."""
    fake_pyside = mock.MagicMock()
    fake_qtwidgets = mock.MagicMock()
    monkeypatch.setitem(_tray_install.sys.modules, "PySide6", fake_pyside)
    monkeypatch.setitem(
        _tray_install.sys.modules, "PySide6.QtWidgets", fake_qtwidgets
    )
    with mock.patch.object(_tray_install.subprocess, "run") as run:
        ok = _tray_install.ensure_installed(auto=False)
    assert ok is True
    run.assert_not_called()


# --- ensure_installed: install paths ------------------------------------


@pytest.fixture
def missing_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the ``import PySide6`` line inside ``ensure_installed`` to fail."""
    # Drop any cached modules from the importer.
    monkeypatch.delitem(_tray_install.sys.modules, "PySide6", raising=False)
    monkeypatch.delitem(
        _tray_install.sys.modules, "PySide6.QtWidgets", raising=False
    )

    real_import = __builtins__["__import__"] if isinstance(
        __builtins__, dict
    ) else __import__

    def fake_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "PySide6" or name.startswith("PySide6."):
            raise ImportError(f"no module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)


def test_ensure_installed_runs_install_when_auto_true(
    missing_deps: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``auto=True`` skips the prompt and invokes the install argv."""
    monkeypatch.setattr(_tray_install, "detect_installer", lambda: "pip")
    monkeypatch.setattr(_tray_install, "_installer_available", lambda _k: True)
    completed = mock.MagicMock(returncode=0)
    with mock.patch.object(_tray_install.subprocess, "run", return_value=completed) as run:
        ok = _tray_install.ensure_installed(auto=True)
    assert ok is True
    run.assert_called_once()


def test_ensure_installed_aborts_without_auto_or_yes(
    missing_deps: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without ``auto`` and without ``y``, we abort."""
    monkeypatch.setattr(_tray_install, "detect_installer", lambda: "pip")
    monkeypatch.setattr(_tray_install, "_installer_available", lambda _k: True)
    monkeypatch.setattr(_tray_install, "_prompt_yes_no", lambda *_a, **_k: False)
    with mock.patch.object(_tray_install.subprocess, "run") as run:
        ok = _tray_install.ensure_installed(auto=False)
    assert ok is False
    run.assert_not_called()


def test_ensure_installed_returns_false_when_installer_missing(
    missing_deps: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If ``uv``/``pipx`` is not on PATH, abort with a clear message."""
    monkeypatch.setattr(_tray_install, "detect_installer", lambda: "uv")
    monkeypatch.setattr(_tray_install, "_installer_available", lambda _k: False)
    with mock.patch.object(_tray_install.subprocess, "run") as run:
        ok = _tray_install.ensure_installed(auto=True)
    assert ok is False
    run.assert_not_called()


def test_ensure_installed_propagates_subprocess_failure(
    missing_deps: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-zero return code from the installer surfaces as ``False``."""
    monkeypatch.setattr(_tray_install, "detect_installer", lambda: "pip")
    monkeypatch.setattr(_tray_install, "_installer_available", lambda _k: True)
    completed = mock.MagicMock(returncode=1)
    with mock.patch.object(_tray_install.subprocess, "run", return_value=completed):
        ok = _tray_install.ensure_installed(auto=True)
    assert ok is False


def test_ensure_installed_handles_oserror(
    missing_deps: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If subprocess can't launch (OSError), we degrade gracefully."""
    monkeypatch.setattr(_tray_install, "detect_installer", lambda: "pip")
    monkeypatch.setattr(_tray_install, "_installer_available", lambda _k: True)
    with mock.patch.object(_tray_install.subprocess, "run", side_effect=OSError("x")):
        ok = _tray_install.ensure_installed(auto=True)
    assert ok is False
