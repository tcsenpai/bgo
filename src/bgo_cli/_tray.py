"""System-tray icon for bgo (optional extra ``bgo-cli[tray]``).

This module is imported lazily by ``cmd_tray`` and is the only place
PySide6 (Qt) is referenced at runtime. Splitting the import-bearing
glue (``_run_tray``) from the pure menu construction
(``build_menu_spec``) lets us unit-test the menu without Qt installed.

Why PySide6
===========
We tried ``pystray`` first. Its default Xorg backend cannot dock under
Wayland (no XEMBED system-tray manager), and its AppIndicator backend
needs distro-specific GI typelibs plus a GNOME shell extension. Qt's
``QSystemTrayIcon`` speaks the StatusNotifierItem (SNI) protocol
natively, so it works on **KDE Plasma 6**, **Hyprland + waybar**, and
other SNI-capable bars without extra setup, and falls back to native
``NSStatusItem`` on **macOS**. GNOME Wayland still requires the
``AppIndicator and KStatusNotifierItem Support`` shell extension, but
that's a GNOME limitation; no Python library can paper over it.

UI model
========
We poll ``~/.bgo/procs/*.json`` every ``poll_seconds`` (default 3,
overridable by ``$BGO_TRAY_POLL`` or ``--poll``) on a Qt ``QTimer`` so
all menu rebuilds happen on the GUI thread. Actions never duplicate
state-management logic from the core script — every click shells out
to the ``bgo`` binary, so behavior matches the CLI exactly.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

BGO_DIR = Path.home() / ".bgo"
PROCS_DIR = BGO_DIR / "procs"

_DEFAULT_POLL_SECONDS = 3


# --- Pure data model -----------------------------------------------------


@dataclass(frozen=True)
class ProcSnapshot:
    """A read-only view of one proc's state file, for menu rendering."""

    name: str
    status: str  # "running" | "stopped" | "errored" | other
    pid: int | None
    errored: bool


@dataclass
class MenuSpec:
    """Declarative description of the tray menu.

    The ``run`` layer translates this into ``pystray.Menu`` objects;
    tests inspect the spec directly. Keeping this layer
    framework-agnostic means swapping pystray for another toolkit in
    the future touches only ``_run_tray``.
    """

    title: str
    procs: list[ProcSnapshot] = field(default_factory=list)
    actions: list[tuple[str, str]] = field(default_factory=list)
    # actions is a list of (label, command) pairs for global entries
    # like Resurrect-all or Quit. Per-proc actions are derived from
    # ``procs`` at render time.


# --- Snapshot loading ----------------------------------------------------


def _load_one(path: Path) -> ProcSnapshot | None:
    """Parse a single proc JSON file. Returns ``None`` on any I/O error."""
    try:
        info = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    name = info.get("name") or path.stem
    status = info.get("status", "unknown")
    pid = info.get("pid")
    watch = info.get("watch") or {}
    errored = bool(watch.get("errored"))
    return ProcSnapshot(
        name=name,
        status=status,
        pid=pid if isinstance(pid, int) else None,
        errored=errored,
    )


def load_snapshots(procs_dir: Path = PROCS_DIR) -> list[ProcSnapshot]:
    """Load every proc state file as a snapshot, sorted by name."""
    if not procs_dir.exists():
        return []
    out: list[ProcSnapshot] = []
    for pf in sorted(procs_dir.glob("*.json")):
        snap = _load_one(pf)
        if snap is not None:
            out.append(snap)
    return out


# --- Menu construction ---------------------------------------------------


def _status_label(snap: ProcSnapshot) -> str:
    """Short human label for a proc's status, used in the menu."""
    if snap.errored:
        return "errored"
    if snap.status == "running":
        return "online"
    return "stopped"


def build_menu_spec(snapshots: Iterable[ProcSnapshot]) -> MenuSpec:
    """Render snapshots into a :class:`MenuSpec` for the toolkit layer.

    Side-effect-free; safe to call in tests without pystray installed.
    """
    procs = list(snapshots)
    online = sum(1 for s in procs if s.status == "running" and not s.errored)
    stopped = len(procs) - online
    title = f"bgo — {online} online / {stopped} stopped"
    actions = [
        ("Resurrect all", "resurrect"),
        ("Refresh now", "__refresh__"),
        ("Quit", "__quit__"),
    ]
    return MenuSpec(title=title, procs=procs, actions=actions)


# --- Subprocess actions --------------------------------------------------


def _bgo_binary() -> str:
    """Resolve the ``bgo`` binary to shell out to.

    Mirrors ``_autostart._resolve_bgo_binary`` but kept local to avoid
    importing autostart just for one helper.
    """
    found = shutil.which("bgo")
    if found:
        return found
    return str(Path(sys.argv[0]).resolve())


def run_bgo(*args: str) -> int:
    """Invoke ``bgo`` with the given args. Returns the exit code.

    Output is suppressed; the tray surfaces feedback via subsequent
    snapshot refreshes, not via terminal output.
    """
    argv = [_bgo_binary(), *args]
    try:
        proc = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return 127
    return proc.returncode


def _open_logs(name: str) -> None:
    """Open the proc's stdout log in ``$EDITOR`` or the OS default.

    Failures are reported to stderr so the user has *some* signal when
    both the editor and the OS default opener fail (e.g. headless
    server with no xdg-open). They do not propagate — the tray loop
    must stay alive.
    """
    log = BGO_DIR / "logs" / f"{name}.out.log"
    if not log.exists():
        sys.stderr.write(f"bgo tray: no log file for {name}\n")
        return
    editor = os.environ.get("EDITOR")
    if editor:
        try:
            subprocess.Popen([editor, str(log)])
            return
        except OSError as exc:
            sys.stderr.write(f"bgo tray: $EDITOR ({editor}) failed: {exc}\n")
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        subprocess.Popen([opener, str(log)])
    except OSError as exc:
        sys.stderr.write(f"bgo tray: {opener} failed: {exc}\n")


def _poll_interval() -> int:
    """Resolve the poll interval, env var > default."""
    raw = os.environ.get("BGO_TRAY_POLL") or ""
    try:
        v = int(raw)
        if v > 0:
            return v
    except ValueError:
        pass
    return _DEFAULT_POLL_SECONDS


# --- PySide6 glue --------------------------------------------------------


# SVG icon embedded as a string so we don't ship binary assets. Rendered
# in monochrome white-on-transparent, sized 64×64 so Qt downscales
# cleanly to 16/22/24 px tray slots.
_ICON_SVG = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect x="10" y="14" width="44" height="8" rx="2" fill="#ffffff"/>
  <rect x="10" y="28" width="44" height="8" rx="2" fill="#ffffff"/>
  <rect x="10" y="42" width="44" height="8" rx="2" fill="#ffffff"/>
</svg>
"""


def _print_gnome_extension_hint() -> None:
    """Hint shown when QSystemTrayIcon.isSystemTrayAvailable is False.

    The most common culprit on Linux is GNOME without the AppIndicator
    extension. On macOS this path is essentially unreachable. On other
    Wayland desktops (KDE / Hyprland / sway+waybar) the SNI host is
    typically already running, so a False reading usually means the
    user is in a non-graphical session (sshd, ttyN).
    """
    sys.stderr.write(
        "\nbgo tray: no system tray is currently available.\n"
        "  GNOME Wayland users need the AppIndicator shell extension:\n"
        "    sudo dnf install gnome-shell-extension-appindicator   # Fedora\n"
        "    sudo apt install gnome-shell-extension-appindicator   # Debian\n"
        "    gnome-extensions enable appindicatorsupport@rgcjonas.gmail.com\n"
        "  KDE Plasma, Hyprland + waybar, and macOS should work out of the\n"
        "  box — if they don't, make sure you're running in a graphical\n"
        "  session (not over plain SSH).\n"
    )


def _run_tray(poll_seconds: int) -> int:  # pragma: no cover — needs Qt
    """Run the Qt event loop until the user quits.

    This function is the only place PySide6 is touched. Everything
    else in the module is framework-agnostic and unit-tested without
    Qt installed.
    """
    try:
        from PySide6.QtCore import QByteArray, QTimer
        from PySide6.QtGui import QAction, QIcon, QPixmap
        from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtCore import QSize, Qt
        from PySide6.QtGui import QPainter
    except ImportError as exc:
        sys.stderr.write(
            f"bgo tray: PySide6 not available: {exc}\n"
            "  Install the tray extra with one of:\n"
            "    uv tool install bgo-cli --with PySide6\n"
            "    pipx inject bgo-cli PySide6\n"
            "    pip install 'bgo-cli[tray]'\n"
        )
        return 1

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # tray-only apps have no window

    if not QSystemTrayIcon.isSystemTrayAvailable():
        _print_gnome_extension_hint()
        return 1

    # Render the embedded SVG into a QIcon at a useful base size. Qt
    # picks the closest match for the tray slot at draw time.
    renderer = QSvgRenderer(QByteArray(_ICON_SVG))
    pixmap = QPixmap(QSize(64, 64))
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    icon_image = QIcon(pixmap)

    tray = QSystemTrayIcon(icon_image)
    tray.setToolTip("bgo")

    # We have to hold a reference to QMenu and every QAction (Qt
    # doesn't take ownership when added to a tray). Keeping them on a
    # closure-captured list survives garbage collection of the locals.
    held: list[object] = []

    def make_proc_submenu(snap: ProcSnapshot, parent: QMenu) -> QMenu:
        # ``bgo start <name>`` without a command is rejected by the
        # core CLI (start requires REMAINDER). For a registered proc
        # the correct respawn is ``bgo restart``, which preserves the
        # stored command. We label it Restart for online procs and
        # Start for stopped ones — same code path under the hood.
        sub = QMenu(snap.name, parent)
        is_running = snap.status == "running" and not snap.errored
        primary_label = "Restart" if is_running else "Start"

        primary = QAction(primary_label, sub)
        primary.triggered.connect(lambda *_: run_bgo("restart", snap.name))
        sub.addAction(primary)

        stop = QAction("Stop", sub)
        stop.triggered.connect(lambda *_: run_bgo("stop", snap.name))
        sub.addAction(stop)

        sub.addSeparator()

        logs = QAction("Open logs", sub)
        logs.triggered.connect(lambda *_: _open_logs(snap.name))
        sub.addAction(logs)

        held.extend([primary, stop, logs, sub])
        return sub

    def build_menu() -> QMenu:
        spec = build_menu_spec(load_snapshots())
        menu = QMenu()
        title_action = QAction(spec.title, menu)
        title_action.setEnabled(False)
        menu.addAction(title_action)
        menu.addSeparator()
        held.append(title_action)

        for snap in spec.procs:
            label = f"{snap.name} [{_status_label(snap)}]"
            sub = make_proc_submenu(snap, menu)
            sub.setTitle(label)
            menu.addMenu(sub)

        menu.addSeparator()
        for label, cmd in spec.actions:
            act = QAction(label, menu)
            if cmd == "__quit__":
                act.triggered.connect(app.quit)
            elif cmd == "__refresh__":
                act.triggered.connect(lambda *_: rebuild())
            else:
                act.triggered.connect(lambda *_, c=cmd: run_bgo(c))
            menu.addAction(act)
            held.append(act)

        return menu

    def rebuild() -> None:
        """Replace the tray's menu with a fresh snapshot-derived build."""
        # Drop old refs so they can be reclaimed. Qt will free them
        # once the previous menu's slots stop firing.
        held.clear()
        new_menu = build_menu()
        held.append(new_menu)
        tray.setContextMenu(new_menu)

    rebuild()
    tray.show()

    # QTimer keeps the polling on Qt's main thread; no GIL juggling,
    # no thread-unsafe menu mutation.
    timer = QTimer()
    timer.setInterval(max(1, poll_seconds) * 1000)
    timer.timeout.connect(rebuild)
    timer.start()
    held.append(timer)

    return int(app.exec())


def run(poll_seconds: int | None = None) -> int:
    """Entrypoint for ``bgo tray``. Resolves poll interval then runs."""
    interval = poll_seconds if (poll_seconds and poll_seconds > 0) else _poll_interval()
    return _run_tray(interval)


__all__ = [
    "ProcSnapshot",
    "MenuSpec",
    "load_snapshots",
    "build_menu_spec",
    "run_bgo",
    "run",
]
