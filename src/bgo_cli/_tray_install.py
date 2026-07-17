"""Auto-install logic for the optional ``[tray]`` extra.

The tray UI needs ``PySide6`` (Qt for Python, LGPL). It's heavy
enough that we intentionally keep it out of the default install.
When the user runs ``bgo tray`` without it present, this module
detects how ``bgo`` itself was installed and proposes the matching
install command:

* ``uv tool``  -> ``uv tool install --force --with PySide6 bgo-cli==<version>``
* ``pipx``     -> ``pipx inject bgo-cli PySide6``
* anything else -> ``pip install --user PySide6``

The uv command pins ``bgo-cli`` to the currently-running version and
uses ``--force`` (reinstall) instead of ``--upgrade``, so injecting
PySide6 can never silently bump (or re-resolve) the installed bgo.

Detection is heuristic but reliable in practice: each installer
leaves its name in ``sys.prefix`` (e.g. ``~/.local/share/uv/tools/bgo-cli``).

The user is always asked before we run a command that mutates their
Python environment, unless ``auto=True`` (set via ``--auto-install``
or ``$BGO_TRAY_AUTOINSTALL=1``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Literal

InstallerKind = Literal["uv", "pipx", "pip"]


def _ansi(name: str, text: str) -> str:
    """Tiny ANSI wrapper so this module stays dep-free of ``_core``.

    Falls back to plain text when stdout is not a TTY.
    """
    if not sys.stdout.isatty():
        return text
    codes = {"red": "31", "green": "32", "yellow": "33", "bold": "1"}
    code = codes.get(name, "")
    return f"\033[{code}m{text}\033[0m" if code else text


def detect_installer() -> InstallerKind:
    """Guess which installer owns this Python environment.

    Uses ``sys.prefix`` because every installer roots bgo's venv
    inside its own per-tool tree. We check the most specific markers
    first (``uv tool``, ``pipx``) and fall through to plain ``pip``.

    The ``UV_TOOL_DIR`` env var is honored when set, so users who
    have moved uv's tool root outside the default ``~/.local/share``
    location are still detected.
    """
    prefix = (sys.prefix or "").replace("\\", "/")
    lower = prefix.lower()
    uv_tool_dir = (os.environ.get("UV_TOOL_DIR") or "").strip()
    if uv_tool_dir:
        normalized = uv_tool_dir.replace("\\", "/").rstrip("/").lower()
        # Compare on a path-component boundary: an unanchored substring
        # match would false-positive when the tool dir is a prefix of an
        # unrelated path (e.g. UV_TOOL_DIR=/opt/uv vs /opt/uvx/...).
        if normalized and (
            lower == normalized or lower.startswith(normalized + "/")
        ):
            return "uv"
    if "/uv/tools/" in lower or "uv-tool" in lower:
        return "uv"
    if "/pipx/venvs/" in lower or "/pipx/" in lower:
        return "pipx"
    return "pip"


def _pinned_bgo_cli_spec() -> str:
    """Pin ``bgo-cli`` to the currently-running version.

    Without a pin, ``uv tool install`` re-resolves bgo-cli from PyPI and
    would silently swap the running install for whatever version (or
    provenance) the index serves. Function-level import matches the
    lazy-import style used elsewhere in this package.
    """
    from bgo_cli import __version__

    return f"bgo-cli=={__version__}"


def _command_for(installer: InstallerKind) -> list[str]:
    """Return the argv that injects ``PySide6``."""
    if installer == "uv":
        # ``--force`` reinstalls the tool (required when it's already
        # installed) while the pinned spec keeps the exact same bgo-cli
        # version — unlike ``--upgrade``, which would bump it. If the
        # running version isn't on PyPI (dev build), the command fails
        # and ensure_installed prints manual instructions.
        return [
            "uv", "tool", "install", "--force",
            "--with", "PySide6",
            _pinned_bgo_cli_spec(),
        ]
    if installer == "pipx":
        # ``inject`` adds packages to the existing venv; it never
        # touches the bgo-cli package itself.
        return ["pipx", "inject", "bgo-cli", "PySide6"]
    return [
        sys.executable, "-m", "pip", "install", "--user",
        "PySide6",
    ]


def _prompt_yes_no(question: str, default: bool = False) -> bool:
    """Ask a y/N question on stdin. Returns ``default`` on EOF / non-TTY."""
    if not sys.stdin.isatty():
        return default
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        answer = input(question + suffix).strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer in ("y", "yes")


def _installer_available(installer: InstallerKind) -> bool:
    """Check whether the proposed installer binary is on PATH."""
    if installer == "uv":
        return shutil.which("uv") is not None
    if installer == "pipx":
        return shutil.which("pipx") is not None
    # ``pip`` runs as ``python -m pip``; always available if Python is.
    return True


def _verify_pyside6_importable() -> bool:
    """Best-effort check that the install actually delivered PySide6.

    ``detect_installer`` keys off ``sys.prefix``, so ``sys.executable``
    is the interpreter of the environment the install command just
    modified (the uv tool venv, the pipx venv, or the current
    user-site python). A *fresh* subprocess re-reads site-packages at
    startup, so a clean import here means the caller's re-exec will
    see PySide6 too — an honest check, unlike trusting rc==0 from the
    installer.
    """
    argv = [sys.executable, "-c", "import PySide6"]
    try:
        result = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"{_ansi('yellow', '⚠')}  could not verify PySide6 import: {exc}")
        return False
    if result.returncode != 0:
        print(
            f"{_ansi('red', '❌')} install finished but PySide6 still "
            f"does not import in the target environment."
        )
        detail = (result.stderr or b"").decode(errors="replace").strip()
        if detail:
            print(f"   {detail.splitlines()[-1]}")
        return False
    return True


def ensure_installed(auto: bool = False) -> bool:
    """Make sure ``PySide6`` is importable. Install if not.

    :param auto: Skip the y/N prompt and run the install command.
    :returns:    ``True`` once PySide6 imports cleanly. ``False`` if
                 the user declined or the install command failed.

    .. important::
       For ``uv tool`` and ``pipx`` install contexts, a successful
       return value indicates the dependencies were installed into the
       *target* environment, **not** the current Python process.
       The caller is responsible for re-execing the appropriate ``bgo``
       binary (``shutil.which("bgo")``) so the new interpreter picks
       up the freshly injected deps. ``cmd_tray`` in the root ``bgo``
       script implements this re-exec. The plain ``pip`` path installs
       into the current Python's user site and the caller can usually
       continue in-process — but re-exec is still the safe default.
    """
    try:
        import PySide6  # noqa: F401  (presence check only)
        # PySide6 imports lazily; verify the QtWidgets submodule loads
        # too so we catch broken installs early.
        from PySide6 import QtWidgets  # noqa: F401
        return True
    except ImportError:
        pass

    installer = detect_installer()
    argv = _command_for(installer)

    print(
        f"{_ansi('yellow', '⚠')}  Tray requires {_ansi('bold', 'PySide6')} "
        f"(Qt for Python, LGPL). Detected installer: "
        f"{_ansi('bold', installer)}."
    )
    print(f"   Proposed command: {_ansi('bold', ' '.join(argv))}")

    if not _installer_available(installer):
        print(
            f"{_ansi('red', '❌')} {installer} not found on PATH. "
            f"Install it first, or run the equivalent command manually."
        )
        return False

    if not auto and not _prompt_yes_no("Run it now?", default=False):
        print("   Aborted. Install manually and re-run `bgo tray`.")
        return False

    print(f"{_ansi('green', '▶')} Running: {' '.join(argv)}")
    try:
        result = subprocess.run(argv, check=False)
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"{_ansi('red', '❌')} install failed to launch: {exc}")
        return False

    if result.returncode != 0:
        print(
            f"{_ansi('red', '❌')} install exited with code "
            f"{result.returncode}."
        )
        if installer == "uv":
            print(
                f"   The pinned spec {_ansi('bold', argv[-1])} could not "
                f"be resolved — you may be running a dev or pre-release\n"
                f"   version that is not on PyPI. Add PySide6 manually "
                f"against your original install source, e.g.:\n"
                f"     uv tool install --force --with PySide6 <source-you-installed-bgo-from>"
            )
        return False

    # Verify the install actually delivered the deps before telling the
    # caller it's safe to re-exec — a false positive here would loop
    # cmd_tray's re-exec path forever.
    if not _verify_pyside6_importable():
        print(
            f"   Re-run `bgo tray` to retry, or install PySide6 manually "
            f"with the command above."
        )
        return False

    print(f"{_ansi('green', '✅')} install complete and verified.")
    return True


__all__ = ["ensure_installed", "detect_installer", "InstallerKind"]
