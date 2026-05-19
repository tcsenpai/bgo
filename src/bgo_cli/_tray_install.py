"""Auto-install logic for the optional ``[tray]`` extra.

The tray UI needs ``pystray`` and ``Pillow`` — both heavy enough that
we intentionally keep them out of the default install. When the user
runs ``bgo tray`` without those deps present, this module detects how
``bgo`` itself was installed and proposes the matching install
command:

* ``uv tool``  -> ``uv tool install --upgrade --with pystray --with Pillow bgo-cli``
* ``pipx``     -> ``pipx inject bgo-cli pystray Pillow``
* anything else -> ``pip install --user pystray Pillow``

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
    """
    prefix = (sys.prefix or "").replace("\\", "/")
    lower = prefix.lower()
    if "/uv/tools/" in lower or "uv-tool" in lower:
        return "uv"
    if "/pipx/venvs/" in lower or "/pipx/" in lower:
        return "pipx"
    return "pip"


def _command_for(installer: InstallerKind) -> list[str]:
    """Return the argv that injects ``pystray`` + ``Pillow``."""
    if installer == "uv":
        return [
            "uv", "tool", "install", "--upgrade",
            "--with", "pystray", "--with", "Pillow",
            "bgo-cli",
        ]
    if installer == "pipx":
        return ["pipx", "inject", "bgo-cli", "pystray", "Pillow"]
    return [
        sys.executable, "-m", "pip", "install", "--user",
        "pystray", "Pillow",
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


def ensure_installed(auto: bool = False) -> bool:
    """Make sure ``pystray`` + ``PIL`` are importable. Install if not.

    :param auto: Skip the y/N prompt and run the install command.
    :returns:    ``True`` once both deps import cleanly. ``False`` if
                 the user declined or the install command failed.
    """
    try:
        import pystray  # noqa: F401  (presence check only)
        import PIL  # noqa: F401
        return True
    except ImportError:
        pass

    installer = detect_installer()
    argv = _command_for(installer)

    print(
        f"{_ansi('yellow', '⚠')}  Tray requires "
        f"{_ansi('bold', 'pystray')} and {_ansi('bold', 'Pillow')}. "
        f"Detected installer: {_ansi('bold', installer)}."
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
        return False

    # Verify the install actually delivered the deps. If the user is
    # running in a different env than the one we just modified (uv tool
    # case in particular), they need to re-exec via the installed
    # entrypoint — bgo handles that in cmd_tray's re-exec path.
    print(f"{_ansi('green', '✅')} install complete.")
    return True


__all__ = ["ensure_installed", "detect_installer", "InstallerKind"]
