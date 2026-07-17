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
from pathlib import Path

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


def _probe_pid_start(pid: int) -> str:
    """Return the ``ps -o lstart=`` start-time string for pid ("" on failure).

    The string is recorded in state as ``pid_start`` at spawn time and
    re-probed before signalling, so a recycled pid can be told apart
    from the process that was actually started.
    """
    try:
        return subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except Exception:
        return ""


def is_running(pid: int | None, expected_start: str | None = None) -> bool:
    """Return True if pid is alive AND not a zombie/defunct process.

    When ``expected_start`` is provided (the ``ps -o lstart=`` string
    recorded at spawn time), the pid's current start time must match
    it — a mismatch means the pid was recycled by an unrelated process
    and we treat it as not ours. ``None`` keeps the legacy check.
    """
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OSError):
        return False
    if _is_zombie(pid):
        return False
    if expected_start is not None and _probe_pid_start(pid) != expected_start:
        return False
    return True


_BLANK_PINFO: dict[str, str] = {"cpu": "-", "mem": "-", "time": "-"}


def get_process_info(pid: int) -> dict:
    """Get CPU / MEM / uptime for a single pid via ps. Prefer batch."""
    return get_process_info_batch([pid]).get(pid, dict(_BLANK_PINFO))


def _parse_ps_info(output: str, result_map: dict[int, dict]) -> None:
    """Parse ``ps -o pid=,%cpu=,%mem=,etime=`` output into result_map."""
    for line in output.splitlines():
        parts = line.split(None, 3)
        if len(parts) >= 4:
            try:
                result_map[int(parts[0])] = {
                    "cpu": parts[1], "mem": parts[2], "time": parts[3],
                }
            except ValueError:
                continue


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
            _parse_ps_info(result.stdout, result_map)
        else:
            # macOS/BSD ps exits non-zero when ANY requested pid is
            # stale, which would otherwise blank every row. Fall back
            # to per-pid probes so live pids still report real data.
            for p in pids:
                single = subprocess.run(
                    ["ps", "-p", str(p), "-o", "pid=,%cpu=,%mem=,etime="],
                    capture_output=True,
                    text=True,
                    timeout=4,
                )
                if single.returncode == 0:
                    _parse_ps_info(single.stdout, result_map)
    except (subprocess.SubprocessError, OSError):
        pass
    # Fill misses with blanks so callers don't have to defensively .get()
    for p in pids:
        result_map.setdefault(p, dict(_BLANK_PINFO))
    return result_map


def _looks_like_command(arg: str) -> bool:
    """Return True if ``arg`` looks like an executable, not a plain name.

    A path separator, a known script/binary extension, or a hit on
    ``shutil.which`` each qualify. Bare dots (e.g. ``my.app``) are no
    longer treated as commands so dotted process names parse correctly
    in direct mode.
    """
    if os.sep in arg or arg.startswith("./"):
        return True
    if shutil.which(arg):
        return True
    known_exts = (".py", ".sh", ".js", ".ts", ".rb", ".pl", ".exe", ".bin")
    if any(arg.lower().endswith(ext) for ext in known_exts):
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


def resolve_bgo_binary() -> str:
    """Locate the ``bgo`` executable for re-invoking ourselves.

    Prefer ``shutil.which('bgo')`` so installed entrypoints (uv tool,
    pipx, pip user site) win over the raw script path. Fall back to
    ``sys.argv[0]`` resolved to an absolute path, which is correct when
    running ``./bgo`` from a source checkout.
    """
    found = shutil.which("bgo")
    if found:
        return str(Path(found).resolve())
    return str(Path(sys.argv[0]).resolve())


def kill_process(
    pid: int,
    pgid: int | None,
    force: bool = False,
    expected_start: str | None = None,
) -> bool:
    """Kill a process (and its process group). Returns True if dead.

    Sends SIGTERM (or SIGKILL with ``force=True``), waits up to 5
    seconds, then escalates to SIGKILL once if the gentler signal
    didn't take. Returning False means the process survived both
    rounds (probably because we lack permission).

    Hard guards refuse to signal pid <= 1, our own pid, or our own
    process group. When ``expected_start`` is provided (the recorded
    ``pid_start``), the pid's identity is verified before any signal
    is sent — a mismatch means the pid was recycled by an unrelated
    process and we refuse to touch it.
    """
    if pid <= 1 or pid == os.getpid():
        print(f"{color('red', '❌')} Refusing to kill PID {pid}")
        return False
    if pgid is not None and pgid == os.getpgid(0):
        print(f"{color('red', '❌')} Refusing to kill own process group {pgid}")
        return False
    if expected_start is not None:
        if not is_running(pid):
            return True
        if _probe_pid_start(pid) != expected_start:
            print(
                f"{color('red', '❌')} PID {pid} start time does not match the"
                " recorded value (pid recycled?); refusing to kill"
            )
            return False

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
        if not is_running(pid, expected_start=expected_start):
            return True
        time.sleep(0.1)

    # Escalate to SIGKILL if SIGTERM didn't work.
    if not force and is_running(pid, expected_start=expected_start):
        try:
            if pgid:
                os.killpg(pgid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
            time.sleep(0.3)
        except (ProcessLookupError, PermissionError):
            pass

    return not is_running(pid, expected_start=expected_start)


__all__ = [
    "_is_zombie", "_probe_pid_start", "is_running",
    "get_process_info", "get_process_info_batch", "_parse_ps_info",
    "_looks_like_command", "derive_name", "resolve_command",
    "resolve_bgo_binary", "kill_process",
]
