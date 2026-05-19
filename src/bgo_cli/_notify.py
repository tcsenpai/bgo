"""Desktop notifications for bgo.

Zero-dependency, best-effort notifier. Shells out to native binaries
on each platform; silently no-ops if no backend is reachable. This
matches bgo's design rule of never adding a runtime Python dependency
to the core package.

Backends, in priority order:
    1. ``$BGO_NOTIFY_CMD`` — caller-provided override. Treated as a
       shell-style argv whose first token is the binary. ``{title}``
       and ``{body}`` placeholders are substituted before exec.
    2. ``notify-send`` (Linux, libnotify).
    3. ``osascript`` (macOS, AppleScript ``display notification``).
    4. ``terminal-notifier`` (macOS, optional brew package).

Gating env var ``$BGO_NOTIFY`` chooses *what* to notify about:
    * ``off``     — disable entirely.
    * ``errors``  — only ``level="error"`` notifications fire (default).
    * ``all``     — every call fires.

The public entrypoint is :func:`notify`. It never raises; callers can
fire-and-forget without try/except.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from typing import Literal, Sequence

Level = Literal["info", "warn", "error"]

_VALID_LEVELS: frozenset[str] = frozenset(("info", "warn", "error"))
_VALID_GATES: frozenset[str] = frozenset(("off", "errors", "all"))
_DEFAULT_GATE = "errors"

# macOS AppleScript template — escaped at substitution time, not formatted
# here, because the body may contain quotes that must be re-escaped per call.
_OSASCRIPT_TEMPLATE = 'display notification "{body}" with title "{title}"'


def _gate() -> str:
    """Return the active notification gate from ``$BGO_NOTIFY``.

    Unknown values fall back to the default (``errors``) so a typo in
    the user's shell config never silently disables notifications they
    expected to receive.
    """
    raw = (os.environ.get("BGO_NOTIFY") or "").strip().lower()
    return raw if raw in _VALID_GATES else _DEFAULT_GATE


def _should_fire(level: Level) -> bool:
    """Return whether a notification at ``level`` passes the gate."""
    gate = _gate()
    if gate == "off":
        return False
    if gate == "all":
        return True
    return level == "error"


def _escape_applescript(s: str) -> str:
    """Escape a string for safe embedding inside an AppleScript literal.

    AppleScript uses ``\\`` as the escape char inside double-quoted
    string literals. Backslashes must be doubled first, then quotes.
    """
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _resolve_backend() -> tuple[str, Sequence[str]] | None:
    """Pick a notifier backend.

    Returns ``(kind, argv_template)`` where ``kind`` is one of
    ``"override"``, ``"notify-send"``, ``"osascript"``,
    ``"terminal-notifier"``, and ``argv_template`` is the argv with
    ``{title}`` / ``{body}`` placeholders ready for substitution.

    Returns ``None`` if no backend is available.
    """
    override = (os.environ.get("BGO_NOTIFY_CMD") or "").strip()
    if override:
        # shlex.split respects shell-style quoting so the user can
        # group arguments containing spaces. We do not invoke a shell
        # at runtime, so injection is bounded to argv only.
        try:
            parts = shlex.split(override)
        except ValueError:
            # Unbalanced quotes etc. — fall through to platform detection.
            parts = []
        if parts:
            return "override", tuple(parts)

    if sys.platform.startswith("linux"):
        if shutil.which("notify-send"):
            return "notify-send", ("notify-send", "{title}", "{body}")

    if sys.platform == "darwin":
        if shutil.which("osascript"):
            return "osascript", ("osascript", "-e", _OSASCRIPT_TEMPLATE)
        if shutil.which("terminal-notifier"):
            return (
                "terminal-notifier",
                ("terminal-notifier", "-title", "{title}", "-message", "{body}"),
            )

    return None


def _format_argv(
    template: Sequence[str], title: str, body: str, kind: str
) -> list[str]:
    """Substitute ``{title}`` / ``{body}`` into the argv template.

    AppleScript needs its own escaping because the placeholders sit
    inside a quoted script literal, not as separate argv items. Every
    other backend receives the raw values as separate argv tokens, so
    no shell quoting concerns apply.
    """
    if kind == "osascript":
        safe_title = _escape_applescript(title)
        safe_body = _escape_applescript(body)
        return [tok.format(title=safe_title, body=safe_body) for tok in template]
    return [tok.format(title=title, body=body) for tok in template]


def notify(title: str, body: str, level: Level = "info") -> bool:
    """Send a desktop notification. Never raises.

    :param title: Short header line. Backends may truncate.
    :param body:  Longer message body.
    :param level: One of ``"info"``, ``"warn"``, ``"error"``. Controls
                  whether the gate (``$BGO_NOTIFY``) allows the call
                  through. Unknown values are treated as ``"info"``.
    :returns: ``True`` if a backend was found and exited 0. ``False``
              if the gate suppressed the call, no backend exists, or
              the backend failed.
    """
    if level not in _VALID_LEVELS:
        level = "info"
    if not _should_fire(level):
        return False

    backend = _resolve_backend()
    if backend is None:
        return False
    kind, template = backend

    try:
        argv = _format_argv(template, title, body, kind)
    except (KeyError, IndexError):
        # Malformed override template — placeholders missing.
        return False

    try:
        result = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return result.returncode == 0


__all__ = ["notify", "Level"]
