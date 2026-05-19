"""Proc state files: load, save, delete, and directory layout.

bgo stores one JSON file per process under ``~/.bgo/procs/<name>.json``
and three log files per process under ``~/.bgo/logs/``. Writes go
through :func:`save_proc`, which is atomic via tmp + ``os.replace``
so a torn JSON never lands on disk even if the watcher and the CLI
race.

The module-level paths (``BGO_DIR``, ``PROCS_DIR``, ``LOGS_DIR``) are
mutable so the test fixture can redirect them into a sandbox before
calling :func:`init_dirs`.

No dependencies on other ``bgo_cli`` modules.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

# Default storage layout. Tests override these by monkeypatching the
# module attributes before calling init_dirs().
BGO_DIR = Path.home() / ".bgo"
PROCS_DIR = BGO_DIR / "procs"
LOGS_DIR = BGO_DIR / "logs"


def init_dirs() -> None:
    """Create the per-user state and log directories if missing."""
    PROCS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def proc_file(name: str) -> Path:
    """Path of the JSON state file for ``name``."""
    return PROCS_DIR / f"{name}.json"


def log_path(name: str, stream: str = "out") -> Path:
    """Path of the stdout / stderr log file for ``name``."""
    return LOGS_DIR / f"{name}.{stream}.log"


def watcher_log_path(name: str) -> Path:
    """Path of the watcher event log file for ``name``."""
    return LOGS_DIR / f"{name}.watcher.log"


def watcher_log(name: str, msg: str) -> None:
    """Append one timestamped line to the watcher log. Never raises."""
    try:
        ts = datetime.now().isoformat(timespec="seconds")
        with open(watcher_log_path(name), "a") as f:
            f.write(f"[{ts}] {msg}\n")
    except OSError:
        pass


def load_proc(name: str) -> dict | None:
    """Return parsed state for ``name``, or ``None`` if missing/corrupt.

    Non-object JSON (lists, strings, numbers) is treated as corrupt
    because the rest of the codebase assumes a mapping (``.get(...)``).
    """
    pf = proc_file(name)
    if not pf.exists():
        return None
    try:
        data = json.loads(pf.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def save_proc(name: str, info: dict) -> None:
    """Atomically write ``info`` as ``name``'s state file.

    Uses a unique tmp file in the same directory plus ``os.replace``
    so concurrent writers (CLI + watcher) cannot stomp on each other's
    in-flight tmp file. ``os.replace`` is atomic on POSIX when src and
    dst share a filesystem, which is true here (both under
    ``~/.bgo/procs/``).
    """
    pf = proc_file(name)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{pf.stem}.", suffix=".tmp", dir=str(pf.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, pf)
    finally:
        tmp.unlink(missing_ok=True)


def delete_proc(name: str, keep_logs: bool = False) -> None:
    """Remove ``name``'s state file. Drops logs unless ``keep_logs``."""
    proc_file(name).unlink(missing_ok=True)
    if keep_logs:
        return
    for stream in ("out", "err"):
        log_path(name, stream).unlink(missing_ok=True)
    watcher_log_path(name).unlink(missing_ok=True)


def load_all_procs() -> dict[str, dict]:
    """Return ``{name: info}`` for every state file under PROCS_DIR."""
    procs: dict[str, dict] = {}
    for pf in sorted(PROCS_DIR.glob("*.json")):
        try:
            info = json.loads(pf.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(info, dict):
            continue
        procs[info.get("name", pf.stem)] = info
    return procs


__all__ = [
    "BGO_DIR", "PROCS_DIR", "LOGS_DIR",
    "init_dirs",
    "proc_file", "log_path", "watcher_log_path", "watcher_log",
    "load_proc", "save_proc", "delete_proc", "load_all_procs",
]
