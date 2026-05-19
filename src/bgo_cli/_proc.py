"""Process inspection and lifecycle utilities.

Cross-platform helpers for:

* Detecting whether a PID is alive AND not a zombie (Linux reads
  ``/proc/<pid>/stat``; macOS shells out to ``ps -o stat=``).
* Pulling CPU / memory / uptime in one batched ``ps`` call regardless
  of how many PIDs need querying.
* Sending SIGTERM / SIGKILL with a wait-and-escalate fallback to a
  process group, so children spawned via ``start_new_session=True``
  are reliably reaped.
* Light command-shape helpers (``derive_name``, ``resolve_command``,
  ``_looks_like_command``) used by the start path.

Imports from ``_term`` for the one error message that needs color.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time

from bgo_cli._term import color


def _is_zombie(pid: int) -> bool:
    """Return True if pid is a zombie/defunct process. Platform-aware."""
    if sys.platform.startswith("linux"):
        try:
            with open(f"/proc/{pid}/stat", "r") as f:
                stat = f.read()
            # stat format: pid (comm) state ...  comm may contain
            # spaces/parens; rfind ')' anchors us past the comm field.
            rparen = stat.rfind(")")
            if rparen != -1:
                state = stat[rparen + 2 : rparen + 3]
                return state == "Z"
        except (OSError, IndexError):
            return False
        return False
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "stat=", ],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0:
                state = result.stdout.strip()
                # macOS ps stat: 'Z' is zombie; may be prefixed with flags
                return state.startswith("Z")
        except (subprocess.SubprocessError, OSError):
            return False
    return False


def is_running(pid: int | None) -> bool:
    """Return True if pid is alive AND not a zombie/defunct process."""
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OSError):
        return False
    return not _is_zombie(pid)


_BLANK_PINFO: dict[str, str] = {"cpu": "-", "mem": "-", "time": "-"}


def get_process_info(pid: int) -> dict:
    """Get CPU / MEM / uptime for a single pid via ps. Prefer batch."""
    return get_process_info_batch([pid]).get(pid, dict(_BLANK_PINFO))


def get_process_info_batch(pids: list[int]) -> dict[int, dict]:
    """Single ps call for many pids. Returns ``{pid: {cpu, mem, time}}``."""
    result_map: dict[int, dict] = {}
    if not pids:
        return result_map
    # ps -p accepts comma-separated pids on both Linux and macOS.
    pid_arg = ",".join(str(p) for p in pids)
    # POSIX-portable header suppression: setting each column's header
    # to an empty string (via "key=") tells ps to emit no header line.
    # macOS/BSD ps does not support GNU's --no-headers long option.
    try:
        result = subprocess.run(
            ["ps", "-p", pid_arg, "-o", "pid=,%cpu=,%mem=,etime="],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split(None, 3)
                if len(parts) >= 4:
                    try:
                        result_map[int(parts[0])] = {
                            "cpu": parts[1], "mem": parts[2], "time": parts[3],
                        }
                    except ValueError:
                        continue
    except (subprocess.SubprocessError, OSError):
        pass
    # Fill misses with blanks so callers don't have to defensively .get()
    for p in pids:
        result_map.setdefault(p, dict(_BLANK_PINFO))
    return result_map


def _looks_like_command(arg: str) -> bool:
    """Return True if ``arg`` looks like an executable, not a plain name.

    A path separator, a dot (extension), or a hit on ``shutil.which``
    each qualify. Used by direct-mode parsing to decide whether the
    first positional is a name or the start of the command.
    """
    if os.sep in arg or arg.startswith("./"):
        return True
    if "." in arg:
        return True
    if shutil.which(arg):
        return True
    return False


def derive_name(cmd: list[str]) -> str:
    """Derive a process name from the command (basename minus extension)."""
    base = os.path.basename(cmd[0])
    for ext in (".py", ".sh", ".js", ".ts", ".rb", ".pl", ".exe"):
        if base.endswith(ext):
            base = base[: -len(ext)]
    return base


def resolve_command(cmd: list[str]) -> list[str]:
    """Resolve ``cmd[0]`` to its full path via ``shutil.which`` if possible."""
    binary = shutil.which(cmd[0])
    if binary:
        cmd = cmd[:]
        cmd[0] = binary
    return cmd


def kill_process(pid: int, pgid: int | None, force: bool = False) -> bool:
    """Kill a process (and its process group). Returns True if dead.

    Sends SIGTERM (or SIGKILL with ``force=True``), waits up to 5
    seconds, then escalates to SIGKILL once if the gentler signal
    didn't take. Returning False means the process survived both
    rounds (probably because we lack permission).
    """
    sig = signal.SIGKILL if force else signal.SIGTERM

    try:
        if pgid:
            os.killpg(pgid, sig)
        else:
            os.kill(pid, sig)
    except ProcessLookupError:
        return True
    except PermissionError:
        print(f"{color('red', '❌')} Permission denied killing PID {pid}")
        return False

    # Wait for termination (5 seconds in 0.1s slices).
    for _ in range(50):
        if not is_running(pid):
            return True
        time.sleep(0.1)

    # Escalate to SIGKILL if SIGTERM didn't work.
    if not force and is_running(pid):
        try:
            if pgid:
                os.killpg(pgid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
            time.sleep(0.3)
        except (ProcessLookupError, PermissionError):
            pass

    return not is_running(pid)


__all__ = [
    "_is_zombie", "is_running",
    "get_process_info", "get_process_info_batch",
    "_looks_like_command", "derive_name", "resolve_command",
    "kill_process",
]
