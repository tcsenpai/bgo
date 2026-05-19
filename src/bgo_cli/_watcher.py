"""Watcher process: auto-restart on crash with fast-crash backoff.

Each ``bgo start -w …`` spawns a *watcher* — a detached sidecar that
polls the target PID and decides what to do when it dies:

* ``backoff`` (default): wait 2s, then 4s, then 8s between retries.
  After 4 consecutive fast-crashes (sub-``min_uptime`` lifetime),
  mark the proc ``errored`` and exit.
* ``stop``: any fast-crash transitions straight to ``errored``.
* ``retry``: keep restarting forever, capped at 8s backoff.

On errored transitions, a best-effort desktop notification is fired
via :func:`bgo_cli._notify.notify`. Watch-config helpers
(:func:`_resolve_watch_block`, :func:`_default_watch_config`) are
pure functions used by the start path.

Depends on :mod:`bgo_cli._state`, :mod:`bgo_cli._proc`, and the
optional :mod:`bgo_cli._notify`. Avoids :mod:`_term` because the
watcher runs detached with no TTY.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

from bgo_cli._proc import is_running, kill_process
from bgo_cli._state import (
    load_proc,
    log_path,
    save_proc,
    watcher_log,
    watcher_log_path,
)

# Defaults for a fresh watch block. ``WATCH_DEFAULTS`` is consulted at
# many sites; keeping it module-level mirrors how the script-era code
# treated it.
WATCH_DEFAULTS: dict[str, object] = {
    "interval": 3,
    "min_uptime": 2,
    "on_fast_crash": "backoff",  # backoff | stop | retry
}
BACKOFF_SCHEDULE: list[int] = [2, 4, 8]
TAIL_BYTES: int = 2048


def _notify_errored(name: str, reason: str) -> None:
    """Best-effort desktop notification on an errored transition.

    Lazy-imports :mod:`bgo_cli._notify`; any failure (including a
    missing module in stripped builds) is swallowed — notifications
    must never break the watcher loop.
    """
    try:
        from bgo_cli._notify import notify
    except ImportError:
        return
    try:
        notify(f"bgo: {name} errored", reason, level="error")
    except Exception:
        pass


def _resolve_watch_block(
    want_watch: bool,
    overrides: dict | None,
    prior_watch: dict | None,
) -> dict | None:
    """Decide what watch block a (re)starting proc should have.

    Three paths, in priority order:

    1. ``want_watch=True`` -> fresh default block, optionally with overrides.
    2. ``prior_watch`` enabled (internal restart path) -> carry forward,
       clear runtime fields (watcher_pid, errored, error_reason,
       last_stderr_tail) but PRESERVE restart counters.
    3. otherwise -> ``None`` (no watch).

    Pure: no side effects. Returns a new dict in all non-None cases.
    """
    if want_watch:
        return _default_watch_config(overrides)
    if prior_watch and prior_watch.get("enabled"):
        carried = dict(prior_watch)
        carried["watcher_pid"] = None
        carried["watcher_pgid"] = None
        carried["errored"] = False
        carried["error_reason"] = None
        carried["last_stderr_tail"] = None
        return carried
    return None


def _default_watch_config(overrides: dict | None = None) -> dict:
    """Build a fresh watch config block with defaults applied."""
    cfg: dict = {
        "enabled": True,
        "interval": WATCH_DEFAULTS["interval"],
        "min_uptime": WATCH_DEFAULTS["min_uptime"],
        "on_fast_crash": WATCH_DEFAULTS["on_fast_crash"],
        "watcher_pid": None,
        "watcher_pgid": None,
        "restarts": 0,
        "last_restart_at": None,
        "errored": False,
        "error_reason": None,
        "last_stderr_tail": None,
    }
    if overrides:
        for k, v in overrides.items():
            if v is not None and k in cfg:
                cfg[k] = v
    return cfg


def _bgo_entrypoint() -> str:
    """Resolve the ``bgo`` binary path for re-invoking the watcher loop.

    Prefer ``shutil.which("bgo")`` so we hit the installed entrypoint
    (uv tool / pipx / pip's user site). Fall back to the script path
    via ``sys.argv[0]`` resolved through :func:`os.path.realpath`,
    which is correct when running ``./bgo`` from the repo.
    """
    found = shutil.which("bgo")
    if found:
        return found
    return os.path.realpath(sys.argv[0]) if sys.argv else ""


def _spawn_watcher(name: str) -> tuple[int | None, int | None]:
    """Detach a watcher subprocess for ``name``. Returns ``(pid, pgid)``."""
    wlog = None
    try:
        wlog = open(watcher_log_path(name), "a")
        bgo_bin = _bgo_entrypoint()
        proc = subprocess.Popen(
            [sys.executable, bgo_bin, "__watcher__", name],
            stdout=wlog,
            stderr=wlog,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        watcher_log(name, f"failed to spawn watcher: {e}")
        return None, None
    finally:
        if wlog is not None:
            wlog.close()
    try:
        pgid = os.getpgid(proc.pid)
    except OSError:
        pgid = None
    return proc.pid, pgid


def _kill_watcher(info: dict) -> None:
    """Kill the watcher associated with ``info`` (if any).

    Mutates ``info["watch"]`` in place to clear the recorded pids so
    the caller's subsequent ``save_proc`` reflects the kill.
    """
    w = info.get("watch") or {}
    wpid = w.get("watcher_pid")
    wpgid = w.get("watcher_pgid")
    if wpid and is_running(wpid):
        kill_process(wpid, wpgid)
    if "watch" in info:
        info["watch"]["watcher_pid"] = None
        info["watch"]["watcher_pgid"] = None


def _tail_stderr(name: str, nbytes: int = TAIL_BYTES) -> str:
    """Return the last ``nbytes`` of the stderr log, stripped."""
    lf = log_path(name, "err")
    if not lf.exists():
        return ""
    try:
        with open(lf, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - nbytes))
            data = f.read().decode("utf-8", errors="replace")
        # Drop the leading partial line so the tail starts cleanly.
        if size > nbytes and "\n" in data:
            data = data[data.index("\n") + 1:]
        return data.strip()
    except OSError:
        return ""


def _restart_proc_inplace(info: dict) -> tuple[int | None, int | None, str | None]:
    """Spawn ``info["command"]`` again. Returns ``(pid, pgid, err_msg)``."""
    name = info["name"]
    command = info["command"]
    cwd = info.get("cwd") or os.getcwd()
    stdout_log = log_path(name, "out")
    stderr_log = log_path(name, "err")
    out_f = None
    err_f = None
    try:
        out_f = open(stdout_log, "a")
        err_f = open(stderr_log, "a")
        ts = datetime.now().isoformat()
        marker = f"\n=== [{ts}] [watch restart] {' '.join(command)} ===\n"
        out_f.write(marker)
        err_f.write(marker)
        out_f.flush()
        err_f.flush()
        proc = subprocess.Popen(
            command,
            stdout=out_f,
            stderr=err_f,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=cwd,
        )
    except FileNotFoundError:
        return None, None, f"command not found: {command[0]}"
    except PermissionError:
        return None, None, f"permission denied: {command[0]}"
    except Exception as e:
        return None, None, f"failed to start: {e}"
    finally:
        if out_f is not None:
            out_f.close()
        if err_f is not None:
            err_f.close()
    try:
        pgid = os.getpgid(proc.pid)
    except OSError:
        pgid = None
    return proc.pid, pgid, None


def cmd_watcher_loop(name: str) -> int:
    """Watcher entry point. Invoked as ``bgo __watcher__ <name>``."""
    # Auto-reap children so dead procs disappear instead of lingering
    # as zombies in our process group.
    try:
        signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    except (ValueError, OSError):
        pass

    info = load_proc(name)
    if not info or not info.get("watch", {}).get("enabled"):
        return 0

    watcher_log(name, f"watcher started for pid={info.get('pid')}")
    backoff_idx = 0
    current_started_at = info.get("started_at")
    needs_early_check = True

    def _start_epoch() -> float:
        try:
            s = current_started_at.replace("Z", "+00:00")
            return datetime.fromisoformat(s).timestamp()
        except Exception:
            return time.time()

    while True:
        interval = info.get("watch", {}).get("interval", WATCH_DEFAULTS["interval"])
        min_uptime_cfg = info.get("watch", {}).get(
            "min_uptime", WATCH_DEFAULTS["min_uptime"]
        )

        if needs_early_check:
            # High-frequency poll during the min_uptime window so
            # fast-crashes are caught with accurate short uptime
            # readings (even when the routine poll interval is larger
            # than min_uptime).
            deadline = _start_epoch() + min_uptime_cfg
            died_early = False
            while time.time() < deadline:
                time.sleep(0.2)
                cur_pid = info.get("pid")
                if not is_running(cur_pid):
                    died_early = True
                    break
            needs_early_check = False
            if not died_early:
                # Sleep the remainder of the normal interval
                remaining = max(
                    0.0,
                    (_start_epoch() + min_uptime_cfg + interval) - time.time(),
                )
                if remaining > 0:
                    time.sleep(min(remaining, interval))
        else:
            time.sleep(max(1, interval))

        info = load_proc(name)
        if not info:
            watcher_log(name, "proc state vanished; exiting")
            return 0
        w = info.get("watch") or {}
        if not w.get("enabled"):
            watcher_log(name, "watch disabled; exiting")
            return 0
        if info.get("status") == "stopped":
            watcher_log(name, "proc manually stopped; exiting")
            return 0

        pid = info.get("pid")
        if is_running(pid):
            continue

        # Process died. Compute uptime.
        try:
            started = datetime.fromisoformat(current_started_at.replace("Z", "+00:00"))
            uptime = (datetime.now(timezone.utc) - started).total_seconds()
        except Exception:
            uptime = 0.0

        min_uptime = w.get("min_uptime", WATCH_DEFAULTS["min_uptime"])
        mode = w.get("on_fast_crash", WATCH_DEFAULTS["on_fast_crash"])
        fast = uptime < min_uptime

        if fast:
            tail = _tail_stderr(name)
            watcher_log(name, f"fast-crash: uptime={uptime:.2f}s mode={mode}")

            if mode == "stop":
                reason = f"fast-crash (uptime {uptime:.2f}s, mode=stop)"
                info["watch"]["errored"] = True
                info["watch"]["error_reason"] = reason
                info["watch"]["last_stderr_tail"] = tail
                info["watch"]["watcher_pid"] = None
                info["watch"]["watcher_pgid"] = None
                info["status"] = "stopped"
                save_proc(name, info)
                watcher_log(name, "errored; exiting")
                _notify_errored(name, reason)
                return 0

            if mode == "backoff":
                if backoff_idx >= len(BACKOFF_SCHEDULE):
                    reason = (
                        f"{len(BACKOFF_SCHEDULE) + 1} consecutive fast-crashes"
                    )
                    info["watch"]["errored"] = True
                    info["watch"]["error_reason"] = reason
                    info["watch"]["last_stderr_tail"] = tail
                    info["watch"]["watcher_pid"] = None
                    info["watch"]["watcher_pgid"] = None
                    info["status"] = "stopped"
                    save_proc(name, info)
                    watcher_log(name, "backoff exhausted; errored; exiting")
                    _notify_errored(name, reason)
                    return 0
                wait = BACKOFF_SCHEDULE[backoff_idx]
                watcher_log(
                    name,
                    f"backoff sleep {wait}s "
                    f"(step {backoff_idx + 1}/{len(BACKOFF_SCHEDULE)})",
                )
                time.sleep(wait)
                backoff_idx += 1
            elif mode == "retry":
                wait = BACKOFF_SCHEDULE[min(backoff_idx, len(BACKOFF_SCHEDULE) - 1)]
                watcher_log(name, f"retry mode: sleep {wait}s")
                time.sleep(wait)
                backoff_idx = min(backoff_idx + 1, len(BACKOFF_SCHEDULE) - 1)
        else:
            backoff_idx = 0

        # Reload (state may have shifted during sleep).
        info = load_proc(name)
        if (
            not info
            or info.get("status") == "stopped"
            or not info.get("watch", {}).get("enabled")
        ):
            watcher_log(name, "state changed during backoff; exiting")
            return 0

        new_pid, new_pgid, err = _restart_proc_inplace(info)
        if err:
            watcher_log(name, f"restart failed: {err}")
            info["watch"]["errored"] = True
            info["watch"]["error_reason"] = err
            info["watch"]["last_stderr_tail"] = _tail_stderr(name)
            info["watch"]["watcher_pid"] = None
            info["watch"]["watcher_pgid"] = None
            info["status"] = "stopped"
            save_proc(name, info)
            _notify_errored(name, err)
            return 0

        now_iso = datetime.now(timezone.utc).isoformat()
        info["pid"] = new_pid
        info["pgid"] = new_pgid
        info["started_at"] = now_iso
        info["status"] = "running"
        info["watch"]["restarts"] = info["watch"].get("restarts", 0) + 1
        info["watch"]["last_restart_at"] = now_iso
        save_proc(name, info)
        current_started_at = now_iso
        needs_early_check = True
        watcher_log(
            name,
            f"restart #{info['watch']['restarts']} pid={new_pid} "
            f"(prev uptime {uptime:.2f}s)",
        )


__all__ = [
    "WATCH_DEFAULTS", "BACKOFF_SCHEDULE", "TAIL_BYTES",
    "_notify_errored",
    "_resolve_watch_block", "_default_watch_config",
    "_spawn_watcher", "_kill_watcher", "_tail_stderr",
    "_restart_proc_inplace", "cmd_watcher_loop",
]
