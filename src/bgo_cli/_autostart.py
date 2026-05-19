"""Login/boot autostart integration for bgo.

Installs a per-user service that runs ``bgo resurrect`` on session
start, restoring every process that was registered as ``running`` at
shutdown. Optionally installs an autostart entry for the tray icon.

Backends are detected automatically:

* **Linux** -> systemd user manager (``systemctl --user``). The unit
  is written to ``~/.config/systemd/user/`` and enabled with the
  ``default.target`` Wants= link. Boot-time start without an active
  login session requires ``loginctl enable-linger <user>``; we print
  a hint rather than running it ourselves (it touches system state).

* **macOS** -> launchd user agent. The plist is written to
  ``~/Library/LaunchAgents/`` and loaded via ``launchctl bootstrap``.
  ``RunAtLoad=true`` triggers on login.

The tray target writes a separate desktop-autostart entry:

* **Linux** -> ``~/.config/autostart/bgo-tray.desktop`` (XDG spec).
* **macOS** -> a second LaunchAgent plist for the tray binary.

All write paths are idempotent: re-running ``install`` overwrites the
unit content but does not duplicate registrations. ``uninstall`` is
safe to call when nothing is installed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal

Target = Literal["resurrect", "tray"]
Backend = Literal["systemd-user", "launchd"]

# --- Unit / plist templates ---------------------------------------------

_SYSTEMD_UNIT = """\
[Unit]
Description=bgo — restore background processes on login (resurrect)
After=default.target

[Service]
Type=oneshot
ExecStart={bgo} resurrect
RemainAfterExit=no

[Install]
WantedBy=default.target
"""

_LAUNCHD_PLIST = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{bgo}</string>
{extra_args}
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
  <key>StandardOutPath</key><string>{home}/.bgo/logs/{label}.out.log</string>
  <key>StandardErrorPath</key><string>{home}/.bgo/logs/{label}.err.log</string>
</dict>
</plist>
"""

_XDG_DESKTOP = """\
[Desktop Entry]
Type=Application
Name=bgo tray
Comment=Background process manager tray icon
Exec={bgo} tray
Icon=utilities-system-monitor
Terminal=false
Categories=Utility;System;
X-GNOME-Autostart-enabled=true
"""

_LAUNCHD_LABEL_RESURRECT = "sh.discus.bgo.resurrect"
_LAUNCHD_LABEL_TRAY = "sh.discus.bgo.tray"


# --- Path resolution -----------------------------------------------------


def detect_backend() -> Backend | None:
    """Return the autostart backend for this OS, or ``None``."""
    if sys.platform.startswith("linux"):
        return "systemd-user"
    if sys.platform == "darwin":
        return "launchd"
    return None


def _systemd_dir() -> Path:
    """Directory for user-scope systemd units."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "systemd" / "user"


def _xdg_autostart_dir() -> Path:
    """Directory for XDG desktop-autostart entries."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "autostart"


def _launchd_dir() -> Path:
    """Directory for per-user launchd agents."""
    return Path.home() / "Library" / "LaunchAgents"


def _resolve_bgo_binary() -> str:
    """Locate the ``bgo`` executable to embed in the unit file.

    Falls back to ``sys.argv[0]`` only if ``shutil.which`` cannot find
    the command on PATH — this happens when bgo is installed in a
    sandboxed venv (e.g. ``uv tool``) whose bin dir is on the user's
    PATH but not the test runner's PATH.
    """
    found = shutil.which("bgo")
    if found:
        # ``which`` already returns absolute paths on all supported
        # platforms, but harden against PATH entries that contain
        # ``..`` or are themselves relative (rare but legal).
        return str(Path(found).resolve())
    # Fall back to the script that invoked us. resolve() collapses
    # symlinks; we want the absolute, canonical path.
    return str(Path(sys.argv[0]).resolve())


def _path_for(backend: Backend, target: Target) -> Path:
    """Return the on-disk path for the (backend, target) pair."""
    if backend == "systemd-user":
        if target == "resurrect":
            return _systemd_dir() / "bgo-resurrect.service"
        return _xdg_autostart_dir() / "bgo-tray.desktop"
    # launchd
    label = _LAUNCHD_LABEL_RESURRECT if target == "resurrect" else _LAUNCHD_LABEL_TRAY
    return _launchd_dir() / f"{label}.plist"


# --- Content rendering ---------------------------------------------------


def _render_systemd_unit(bgo: str) -> str:
    """Render the resurrect systemd unit."""
    return _SYSTEMD_UNIT.format(bgo=bgo)


def _render_xdg_desktop(bgo: str) -> str:
    """Render the tray XDG autostart entry."""
    return _XDG_DESKTOP.format(bgo=bgo)


def _render_launchd_plist(target: Target, bgo: str) -> str:
    """Render a launchd plist for resurrect or tray."""
    if target == "resurrect":
        label = _LAUNCHD_LABEL_RESURRECT
        extra = "    <string>resurrect</string>"
    else:
        label = _LAUNCHD_LABEL_TRAY
        extra = "    <string>tray</string>"
    return _LAUNCHD_PLIST.format(
        label=label, bgo=bgo, extra_args=extra, home=str(Path.home())
    )


# --- Filesystem + service-manager wiring --------------------------------


def _write_file(path: Path, content: str) -> None:
    """Atomic write: create parent dirs, tmp + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    os.replace(tmp, path)


def _run(argv: list[str]) -> tuple[int, str]:
    """Run a command capturing combined output. Never raises."""
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _systemd_reload_and_enable(unit: str) -> tuple[bool, str]:
    """Reload the user manager and enable+start the given unit."""
    rc, out = _run(["systemctl", "--user", "daemon-reload"])
    if rc != 0:
        return False, f"daemon-reload failed: {out.strip()}"
    rc, out = _run(["systemctl", "--user", "enable", "--now", unit])
    if rc != 0:
        return False, f"enable failed: {out.strip()}"
    return True, ""


def _systemd_disable(unit: str) -> tuple[bool, str]:
    """Disable + stop a user unit. Missing units are not an error."""
    rc, out = _run(["systemctl", "--user", "disable", "--now", unit])
    if rc != 0 and "does not exist" not in out and "No such file" not in out:
        return False, f"disable failed: {out.strip()}"
    return True, ""


def _launchctl_load(plist: Path) -> tuple[bool, str]:
    """Bootstrap a per-user agent. Falls back to legacy ``load`` cmd."""
    uid = os.getuid()
    rc, out = _run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)])
    if rc == 0:
        return True, ""
    # Older macOS / already-loaded states return non-zero — try legacy
    # ``load`` as a fallback so we don't error on cleanly reusable
    # plists.
    rc2, out2 = _run(["launchctl", "load", "-w", str(plist)])
    if rc2 == 0:
        return True, ""
    return False, f"bootstrap failed: {out.strip()}; load failed: {out2.strip()}"


def _launchctl_unload(plist: Path) -> tuple[bool, str]:
    """Tear down a per-user agent. Missing agents are not an error.

    Tries the modern ``bootout`` first, then falls back to the legacy
    ``unload -w`` form. We accept either success because users on
    older macOS won't have ``bootout``. A failure from *both* is
    surfaced so callers don't silently leave a registered agent
    behind after the plist file is removed.
    """
    uid = os.getuid()
    rc_b, out_b = _run(["launchctl", "bootout", f"gui/{uid}", str(plist)])
    if rc_b == 0:
        return True, ""
    rc_u, out_u = _run(["launchctl", "unload", "-w", str(plist)])
    if rc_u == 0:
        return True, ""
    # macOS reports "Could not find specified service" when the agent
    # is already absent — treat that as success so uninstall stays
    # idempotent.
    combined = (out_b + out_u).lower()
    for phrase in (
        "could not find",
        "no such file",
        "service is not loaded",
    ):
        if phrase in combined:
            return True, ""
    return False, f"bootout: {out_b.strip()}; unload: {out_u.strip()}"


# --- Public API ----------------------------------------------------------


def install(target: Target) -> tuple[bool, str]:
    """Install the autostart entry for ``target``.

    :returns: ``(ok, message)`` where ``message`` is empty on success
              and contains a human-readable error otherwise.
    """
    backend = detect_backend()
    if backend is None:
        return False, f"unsupported platform: {sys.platform}"

    bgo = _resolve_bgo_binary()
    path = _path_for(backend, target)

    if backend == "systemd-user":
        if target == "resurrect":
            _write_file(path, _render_systemd_unit(bgo))
            ok, err = _systemd_reload_and_enable("bgo-resurrect.service")
            if not ok:
                return False, err
            return True, str(path)
        # tray -> XDG desktop autostart (no systemctl needed)
        _write_file(path, _render_xdg_desktop(bgo))
        return True, str(path)

    # launchd
    _write_file(path, _render_launchd_plist(target, bgo))
    ok, err = _launchctl_load(path)
    if not ok:
        return False, err
    return True, str(path)


def uninstall(target: Target) -> tuple[bool, str]:
    """Remove the autostart entry for ``target``. Idempotent."""
    backend = detect_backend()
    if backend is None:
        return False, f"unsupported platform: {sys.platform}"

    path = _path_for(backend, target)

    if backend == "systemd-user":
        if target == "resurrect":
            ok, err = _systemd_disable("bgo-resurrect.service")
            path.unlink(missing_ok=True)
            if not ok:
                return False, err
            return True, ""
        path.unlink(missing_ok=True)
        return True, ""

    # launchd
    if path.exists():
        _launchctl_unload(path)
        path.unlink(missing_ok=True)
    return True, ""


def status() -> dict[str, object]:
    """Report the current install status of each target.

    :returns: ``{"backend": str|None, "resurrect": bool, "tray": bool,
              "resurrect_path": str|None, "tray_path": str|None}``.
    """
    backend = detect_backend()
    if backend is None:
        return {
            "backend": None,
            "resurrect": False,
            "tray": False,
            "resurrect_path": None,
            "tray_path": None,
        }
    rp = _path_for(backend, "resurrect")
    tp = _path_for(backend, "tray")
    return {
        "backend": backend,
        "resurrect": rp.exists(),
        "tray": tp.exists(),
        "resurrect_path": str(rp) if rp.exists() else None,
        "tray_path": str(tp) if tp.exists() else None,
    }


__all__ = ["install", "uninstall", "status", "detect_backend", "Target", "Backend"]
