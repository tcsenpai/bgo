"""Terminal capability detection, ANSI colors, and glyph sets.

bgo renders output at three increasing levels of polish:

* ``plain``  — no color, ASCII-only dashes, no glyphs. Used for CI
  logs, ``TERM=dumb``, non-TTY pipes, or explicit ``--plain``.
* ``normal`` — ANSI color + ASCII rules. Default for color-capable
  TTYs without UTF-8.
* ``fancy``  — ANSI color + Unicode box-drawing. Default for
  UTF-8-capable TTYs.

The detection cascade lives in :func:`_detect_table_level`. Public
helpers :func:`color`, :func:`strip_ansi`, :func:`truncate`, and
:func:`glyphs` are imported by every renderer in the codebase.

This module has no dependencies on other ``bgo_cli`` modules — it
sits at the bottom of the import graph.
"""

from __future__ import annotations

import os
import re
import sys

# ANSI color escape codes. Looked up by name; unknown names yield no
# wrapping so callers can pass user-supplied keys without crashing.
COLORS: dict[str, str] = {
    "green": "\033[32m",
    "red": "\033[31m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "gray": "\033[90m",
    "reset": "\033[0m",
    "bold": "\033[1m",
}

ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def color(name: str, text: str) -> str:
    """Wrap text in color codes, only if stdout is a TTY.

    Unknown color names return the text unchanged (no reset code
    appended), preserving the documented "no wrapping" contract.
    """
    if not sys.stdout.isatty():
        return str(text)
    code = COLORS.get(name)
    if not code:
        return str(text)
    return f"{code}{text}{COLORS['reset']}"


def strip_ansi(s: str) -> str:
    """Remove ANSI escape codes from a string."""
    return ANSI_RE.sub("", s)


def truncate(s: str, width: int) -> str:
    """Truncate string to fit in width, accounting for ANSI codes.

    Edge cases for narrow columns:
      * ``width <= 0``  -> empty string
      * ``width <= 3``  -> ``"..."[:width]`` so output never exceeds
        ``width`` (the 3-char ellipsis would otherwise overflow).
    """
    if width <= 0:
        return ""
    if width <= 3:
        return "..."[:width]
    plain = strip_ansi(s)
    if len(plain) > width:
        return s[: width - 3] + "..."
    return s


# --- Terminal capability detection --------------------------------------

LEVEL_PLAIN = "plain"
LEVEL_NORMAL = "normal"
LEVEL_FANCY = "fancy"


def _detect_table_level(force: str | None = None) -> str:
    """Decide which rendering level to use.

    Resolution order:
      1. explicit ``force`` (from ``--plain`` / ``--fancy`` or
         ``$BGO_TABLE``)
      2. non-TTY stdout         -> plain
      3. ``$TERM=dumb``         -> plain
      4. ``$LANG`` / ``$LC_*`` lacks UTF-8 -> normal
      5. otherwise              -> fancy
    """
    if force in (LEVEL_PLAIN, LEVEL_NORMAL, LEVEL_FANCY):
        return force
    env_force = os.environ.get("BGO_TABLE", "").strip().lower()
    if env_force in (LEVEL_PLAIN, LEVEL_NORMAL, LEVEL_FANCY):
        return env_force
    if not sys.stdout.isatty():
        return LEVEL_PLAIN
    if os.environ.get("TERM", "") == "dumb":
        return LEVEL_PLAIN
    lc = (
        os.environ.get("LC_ALL")
        or os.environ.get("LC_CTYPE")
        or os.environ.get("LANG")
        or ""
    ).upper()
    if "UTF-8" not in lc and "UTF8" not in lc:
        return LEVEL_NORMAL
    return LEVEL_FANCY


# Glyph set per level. Keys must be identical across levels so callers
# can index without branching.
GLYPHS: dict[str, dict[str, str]] = {
    LEVEL_PLAIN: {
        "hline": "-", "vline": "|", "cross": "+",
        "tl": "+", "tr": "+", "bl": "+", "br": "+",
        "tdown": "+", "tup": "+", "tleft": "+", "tright": "+",
        "online": "ON", "stopped": "OFF",
        "watching": "[W]", "errored": "[!]", "watcher_dead": "[?]",
        "watch_none": "-",
        "ok": "OK", "fail": "FAIL", "warn": "WARN",
        "tombstone": "[X]", "rocket": "[+]", "eye": "[W]",
    },
    LEVEL_NORMAL: {
        "hline": "─", "vline": "│", "cross": "┼",
        "tl": "┌", "tr": "┐", "bl": "└", "br": "┘",
        "tdown": "┬", "tup": "┴", "tleft": "┤", "tright": "├",
        "online": "online", "stopped": "stopped",
        "watching": "✓", "errored": "⚠", "watcher_dead": "!",
        "watch_none": "-",
        "ok": "✅", "fail": "❌", "warn": "⚠️",
        "tombstone": "🗑️", "rocket": "🚀", "eye": "👁",
    },
    LEVEL_FANCY: {
        "hline": "━", "vline": "┃", "cross": "╋",
        "tl": "┏", "tr": "┓", "bl": "┗", "br": "┛",
        "tdown": "┳", "tup": "┻", "tleft": "┫", "tright": "┣",
        "online": "● online", "stopped": "○ stopped",
        "watching": "✓", "errored": "⚠", "watcher_dead": "!",
        "watch_none": "·",
        "ok": "✅", "fail": "❌", "warn": "⚠️",
        "tombstone": "🗑️", "rocket": "🚀", "eye": "👁",
    },
}


def glyphs(level: str | None = None) -> dict[str, str]:
    """Return the glyph set for a level (default: auto-detect)."""
    return GLYPHS[level or _detect_table_level()]


__all__ = [
    "COLORS", "ANSI_RE",
    "color", "strip_ansi", "truncate",
    "LEVEL_PLAIN", "LEVEL_NORMAL", "LEVEL_FANCY",
    "_detect_table_level", "GLYPHS", "glyphs",
]
