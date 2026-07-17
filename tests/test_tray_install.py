"""Tests for ``bgo_cli._tray_install``.

Verifies installer detection from ``sys.prefix`` (including
``UV_TOOL_DIR`` path-boundary matching), command construction per
installer kind (the uv path must pin the running ``bgo-cli`` version
so injecting PySide6 can never silently upgrade bgo itself), and the
prompt + subprocess + import-verification flow when ``PySide6`` is
missing.
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


def test_detect_installer_uv_tool_dir_matches_on_path_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``UV_TOOL_DIR`` must not match as a bare substring.

    ``/opt/uv`` is a prefix of ``/opt/uvx/...`` but not a parent
    directory of it — an unanchored substring check would misdetect.
    """
    monkeypatch.setenv("UV_TOOL_DIR", "/opt/uv")
    monkeypatch.setattr(_tray_install.sys, "prefix", "/opt/uvx/tools/bgo-cli")
    assert _tray_install.detect_installer() == "pip"


# --- _command_for --------------------------------------------------------


def test_command_for_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _tray_install, "_pinned_bgo_cli_spec", lambda: "bgo-cli==9.9.9"
    )
    argv = _tray_install._command_for("uv")
    assert argv[:3] == ["uv", "tool", "install"]
    assert "PySide6" in argv
    assert argv[-1] == "bgo-cli==9.9.9"


def test_command_for_uv_never_upgrades(monkeypatch: pytest.MonkeyPatch) -> None:
    """The uv argv pins the running bgo-cli version and drops
    ``--upgrade`` — injecting PySide6 must not bump bgo itself."""
    monkeypatch.setattr(
        _tray_install, "_pinned_bgo_cli_spec", lambda: "bgo-cli==9.9.9"
    )
    argv = _tray_install._command_for("uv")
    assert "--upgrade" not in argv
    assert "--force" in argv


def test_pinned_spec_uses_running_version() -> None:
    """Default pin comes from ``bgo_cli.__version__``."""
    from bgo_cli import __version__

    assert _tray_install._pinned_bgo_cli_spec() == f"bgo-cli=={__version__}"


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
    # Two subprocess invocations: the install command itself, then the
    # post-install ``import PySide6`` verification.
    assert run.call_count == 2


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


# --- ensure_installed: post-install verification -------------------------


def test_ensure_installed_verifies_import_after_install(
    missing_deps: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a successful install, we really try to import PySide6 in a
    fresh subprocess of the target interpreter."""
    monkeypatch.setattr(_tray_install, "detect_installer", lambda: "pip")
    monkeypatch.setattr(_tray_install, "_installer_available", lambda _k: True)
    monkeypatch.setattr(_tray_install.sys, "executable", "/python")
    ok_install = mock.MagicMock(returncode=0)
    ok_verify = mock.MagicMock(returncode=0)
    with mock.patch.object(
        _tray_install.subprocess, "run", side_effect=[ok_install, ok_verify]
    ) as run:
        ok = _tray_install.ensure_installed(auto=True)
    assert ok is True
    assert run.call_count == 2
    verify_argv = run.call_args_list[1].args[0]
    assert verify_argv == ["/python", "-c", "import PySide6"]


def test_ensure_installed_fails_when_verification_fails(
    missing_deps: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clean installer exit code is not enough: if PySide6 still does
    not import in the target env, ensure_installed must return False so
    cmd_tray does not re-exec into a loop."""
    monkeypatch.setattr(_tray_install, "detect_installer", lambda: "pip")
    monkeypatch.setattr(_tray_install, "_installer_available", lambda _k: True)
    ok_install = mock.MagicMock(returncode=0)
    bad_verify = mock.MagicMock(
        returncode=1, stderr=b"ModuleNotFoundError: No module named 'PySide6'"
    )
    with mock.patch.object(
        _tray_install.subprocess, "run", side_effect=[ok_install, bad_verify]
    ):
        ok = _tray_install.ensure_installed(auto=True)
    assert ok is False


def test_ensure_installed_fails_when_verification_crashes(
    missing_deps: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An OSError/timeout during verification is reported, not trusted."""
    monkeypatch.setattr(_tray_install, "detect_installer", lambda: "pip")
    monkeypatch.setattr(_tray_install, "_installer_available", lambda _k: True)
    ok_install = mock.MagicMock(returncode=0)
    with mock.patch.object(
        _tray_install.subprocess, "run", side_effect=[ok_install, OSError("x")]
    ):
        ok = _tray_install.ensure_installed(auto=True)
    assert ok is False
