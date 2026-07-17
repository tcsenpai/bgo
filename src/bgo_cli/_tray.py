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
import threading
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

    The ``_run_tray`` layer translates this into ``QMenu``/``QAction``
    objects; tests inspect the spec directly. Keeping this layer
    framework-agnostic means swapping Qt for another toolkit in the
    future touches only ``_run_tray``.
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
    """Load every proc state file as a snapshot, sorted by ``name``.

    Sort happens after parsing so the order follows the proc's stored
    ``name`` field (which may differ from the on-disk filename).
    """
    if not procs_dir.exists():
        return []
    out: list[ProcSnapshot] = []
    for pf in procs_dir.glob("*.json"):
        snap = _load_one(pf)
        if snap is not None:
            out.append(snap)
    return sorted(out, key=lambda s: s.name)


# --- Menu construction ---------------------------------------------------


def _status_label(snap: ProcSnapshot) -> str:
    """Short human label for a proc's status, used in the menu."""
    if snap.errored:
        return "errored"
    if snap.status == "running":
        return "online"
    return "stopped"


# Unicode glyphs paired with status keys. QAction labels render
# Unicode reliably across KDE, GNOME, and macOS — the only way to get
# "color" in menu items without per-platform theming code is to use
# glyphs whose shape (filled vs hollow vs warning) communicates state.
_STATUS_GLYPHS: dict[str, str] = {
    "online":  "●",   # filled circle  — running
    "stopped": "○",   # hollow circle  — stopped
    "errored": "⚠",   # warning sign   — errored
}


def _status_glyph(snap: ProcSnapshot) -> str:
    """Return the Unicode glyph for the snap's status."""
    return _STATUS_GLYPHS[_status_label(snap)]


def build_menu_spec(snapshots: Iterable[ProcSnapshot]) -> MenuSpec:
    """Render snapshots into a :class:`MenuSpec` for the toolkit layer.

    Side-effect-free; safe to call in tests without PySide6 installed.
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

    Delegates to :func:`bgo_cli._proc.resolve_bgo_binary` so the tray,
    autostart, and watcher all agree on the binary to use.
    """
    from bgo_cli._proc import resolve_bgo_binary

    return resolve_bgo_binary()


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


def _run_bgo_in_thread(*args: str, on_done: Callable[[int], None]) -> threading.Thread:
    """Run :func:`run_bgo` on a daemon thread; call ``on_done(rc)`` when done.

    Tray action slots use this so a slow ``bgo`` invocation (up to the
    20 s timeout) never blocks the Qt GUI thread. ``on_done`` fires on
    the worker thread — callers must marshal back to the GUI thread
    themselves (``_run_tray`` wires it to a ``Signal.emit``, which Qt
    queue-delivers to the GUI thread).
    """
    def work() -> None:
        on_done(run_bgo(*args))

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    return thread


# Ordered preferences for graphical terminal emulators. We pick the
# first one on PATH. Each tuple is (binary, exec-flag) — the flag is
# whatever the terminal uses to mean "the rest of the argv is the
# command to run". This list deliberately favors modern terminals
# (kitty/wezterm/alacritty/foot) before the desktop-environment
# defaults so users with both installed get the lighter one.
_LINUX_TERMINALS: tuple[tuple[str, str], ...] = (
    ("kitty", "--"),
    ("alacritty", "-e"),
    ("wezterm", "start"),
    ("foot", "--"),
    ("ghostty", "-e"),
    ("gnome-terminal", "--"),
    ("konsole", "-e"),
    ("xfce4-terminal", "-e"),
    ("tilix", "-e"),
    ("xterm", "-e"),
)


def _resolve_terminal() -> tuple[str, str] | None:
    """Pick the first available terminal emulator on Linux.

    Honors ``$BGO_TERMINAL`` for an explicit override; the value is
    parsed as ``<binary> [exec-flag]`` (defaulting to ``-e`` when no
    flag is given). Returns ``None`` if nothing usable was found.
    """
    override = (os.environ.get("BGO_TERMINAL") or "").strip()
    if override:
        parts = override.split(None, 1)
        binary = parts[0]
        flag = parts[1] if len(parts) > 1 else "-e"
        if shutil.which(binary):
            return binary, flag
        return None
    for binary, flag in _LINUX_TERMINALS:
        if shutil.which(binary):
            return binary, flag
    return None


def _open_logs(name: str) -> None:
    """Open ``bgo logs <name> -f`` in a fresh terminal window.

    macOS uses AppleScript to spawn Terminal.app (or iTerm2 if it's
    set as default via ``$BGO_TERMINAL=iterm``). Linux probes a
    curated list of common emulators and runs the first one found.
    Any failure is written to stderr — the tray loop must stay alive.
    """
    log = BGO_DIR / "logs" / f"{name}.out.log"
    if not log.exists():
        sys.stderr.write(f"bgo tray: no log file for {name}\n")
        return

    from bgo_cli._proc import resolve_bgo_binary

    follow_cmd = [resolve_bgo_binary(), "logs", name, "-f"]

    if sys.platform == "darwin":
        _open_logs_darwin(follow_cmd)
        return

    terminal = _resolve_terminal()
    if terminal is None:
        sys.stderr.write(
            "bgo tray: no terminal emulator found on PATH. "
            "Set $BGO_TERMINAL to override (e.g. BGO_TERMINAL='alacritty -e').\n"
        )
        return

    binary, flag = terminal
    argv = [binary, flag, *follow_cmd]
    try:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        sys.stderr.write(f"bgo tray: {binary} failed to launch: {exc}\n")


def _open_logs_darwin(follow_cmd: list[str]) -> None:
    """Spawn ``follow_cmd`` in a new Terminal.app (or iTerm) window.

    AppleScript is the only friction-free way to open a fresh window
    on macOS without writing a temporary launcher script. The command
    is shell-quoted so paths with spaces survive the round-trip.
    """
    import shlex

    # Shell-quote each arg so the spawned terminal's shell parses the
    # command back into argv correctly.
    quoted = " ".join(shlex.quote(arg) for arg in follow_cmd)
    # Then escape the result for the AppleScript string layer: any
    # backslashes or double quotes inside `quoted` (e.g. from paths
    # containing them) would otherwise terminate the AppleScript
    # literal early or smuggle in extra AppleScript tokens.
    quoted = quoted.replace("\\", "\\\\").replace('"', '\\"')
    override = (os.environ.get("BGO_TERMINAL") or "").strip().lower()
    use_iterm = override in ("iterm", "iterm2")

    if use_iterm:
        script = (
            'tell application "iTerm"\n'
            "  activate\n"
            "  create window with default profile\n"
            f'  tell current session of current window to write text "{quoted}"\n'
            "end tell"
        )
    else:
        script = f'tell application "Terminal" to do script "{quoted}"'

    try:
        subprocess.Popen(
            ["osascript", "-e", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        sys.stderr.write(f"bgo tray: osascript failed: {exc}\n")


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


# Status -> hex color for the gear's center dot. Chosen for contrast
# against most tray backgrounds (both dark and light themes) and for
# common color-blindness friendliness (green/red is suboptimal but
# universally understood for status — paired with shape would be
# better in a future revision).
_DOT_COLORS: dict[str, str] = {
    "online":  "#3ddc84",  # bright green — at least one proc running, none errored
    "errored": "#ff5252",  # red          — any proc in errored state
    "idle":    "#9e9e9e",  # neutral gray — nothing registered or everything stopped
}


def _icon_svg(dot_color: str) -> bytes:
    """Render the gear+dot SVG with the given dot color.

    Composition strategy avoids the ``fill-rule=evenodd`` cutout that
    some renderers (notably Qt's QSvgRenderer + KDE Plasma's monochrome
    SNI repaint pass) mishandle:

    1. **Ring** — a thick stroked circle = the gear body.
    2. **Teeth** — 12 small rectangles placed radially around the ring.
    3. **Dot**  — colored circle in the middle, sitting on top.

    Each is a separate SVG element. Total: 14 shapes, all explicitly
    filled, no path subtraction. Renders identically on Qt, KDE
    monochrome repaint, and macOS Cocoa.
    """
    # 12 teeth at 30° intervals. Each tooth = 6×8 rect centered on a
    # radial line at radius 26 from center (32, 32).
    import math

    teeth = []
    for i in range(12):
        angle = math.radians(i * 30)
        # Place tooth so its base touches the outer edge of the ring.
        cx = 32 + math.cos(angle) * 28
        cy = 32 + math.sin(angle) * 28
        # Rotate the rect to align with the radial direction.
        deg = i * 30
        teeth.append(
            f'<rect x="-3" y="-4" width="6" height="8" rx="1.2" '
            f'fill="#ffffff" '
            f'transform="translate({cx:.2f} {cy:.2f}) rotate({deg})"/>'
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        # Outer ring — white stroke, no fill (transparent center so
        # the dot below shows through cleanly).
        '<circle cx="32" cy="32" r="22" fill="none" '
        'stroke="#ffffff" stroke-width="6"/>'
        # 12 teeth radiating outward.
        + "".join(teeth) +
        # Status dot — colored, fills the inner ring.
        f'<circle cx="32" cy="32" r="9" fill="{dot_color}"/>'
        '</svg>'
    ).encode("utf-8")


def _aggregate_status(snapshots: list[ProcSnapshot]) -> str:
    """Reduce a snapshot list to one status key for the icon dot.

    - ``errored``  : any proc flagged ``errored`` (highest priority)
    - ``online``   : at least one proc running, none errored
    - ``idle``     : empty list or all procs stopped
    """
    if any(s.errored for s in snapshots):
        return "errored"
    if any(s.status == "running" for s in snapshots):
        return "online"
    return "idle"


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
    import signal

    try:
        from PySide6.QtCore import QByteArray, QObject, QTimer, Signal
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

    def make_icon(dot_color: str) -> QIcon:
        """Rasterize the gear+dot SVG into a Qt icon at 64×64."""
        renderer = QSvgRenderer(QByteArray(_icon_svg(dot_color)))
        pixmap = QPixmap(QSize(64, 64))
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        try:
            renderer.render(painter)
        finally:
            painter.end()
        return QIcon(pixmap)

    tray = QSystemTrayIcon(make_icon(_DOT_COLORS["idle"]))
    tray.setToolTip("bgo")
    current_status = {"key": "idle"}

    # We have to hold a reference to QMenu and every QAction (Qt
    # doesn't take ownership when added to a tray). Keeping them on a
    # closure-captured list survives garbage collection of the locals.
    held: list[object] = []

    # --- Async action dispatch ------------------------------------------
    # ``run_bgo`` blocks for up to its 20 s timeout; calling it from a
    # QAction slot would freeze the menu and icon for the duration. Run
    # it on a daemon thread and marshal the exit code back through a Qt
    # Signal (thread-safe: Qt queue-delivers it to the GUI thread, where
    # ``bridge`` lives). While one action is in flight, further triggers
    # are dropped — the forced rebuild on completion reflects the result.
    class _ActionBridge(QObject):
        finished = Signal(int)

    bridge = _ActionBridge()
    action_busy = {"in_flight": False}

    def on_action_done(_rc: int) -> None:
        action_busy["in_flight"] = False
        rebuild(force=True)

    bridge.finished.connect(on_action_done)
    held.append(bridge)

    def run_bgo_action(*args: str) -> None:
        if action_busy["in_flight"]:
            return
        action_busy["in_flight"] = True
        _run_bgo_in_thread(*args, on_done=bridge.finished.emit)

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
        primary.triggered.connect(lambda *_: run_bgo_action("restart", snap.name))
        sub.addAction(primary)

        stop = QAction("Stop", sub)
        stop.triggered.connect(lambda *_: run_bgo_action("stop", snap.name))
        sub.addAction(stop)

        sub.addSeparator()

        logs = QAction("Open logs", sub)
        logs.triggered.connect(lambda *_: _open_logs(snap.name))
        sub.addAction(logs)

        held.extend([primary, stop, logs, sub])
        return sub

    def build_menu_from(snapshots: list[ProcSnapshot]) -> QMenu:
        spec = build_menu_spec(snapshots)
        menu = QMenu()
        title_action = QAction(spec.title, menu)
        title_action.setEnabled(False)
        menu.addAction(title_action)
        menu.addSeparator()
        held.append(title_action)

        for snap in spec.procs:
            label = f"{_status_glyph(snap)}  {snap.name}  ·  {_status_label(snap)}"
            sub = make_proc_submenu(snap, menu)
            sub.setTitle(label)
            menu.addMenu(sub)

        menu.addSeparator()
        for label, cmd in spec.actions:
            act = QAction(label, menu)
            if cmd == "__quit__":
                act.triggered.connect(app.quit)
            elif cmd == "__refresh__":
                act.triggered.connect(lambda *_: rebuild(force=True))
            else:
                act.triggered.connect(lambda *_, c=cmd: run_bgo_action(c))
            menu.addAction(act)
            held.append(act)

        return menu

    # Last snapshot list that produced the current menu. Rebuilding a
    # QMenu allocates dozens of QObjects (plus native NSMenu bridges on
    # macOS) that Qt never fully reclaims, so unconditional rebuilds on
    # every poll tick leak — ~40 KB every 3 s adds up to gigabytes over
    # days. Skipping no-op rebuilds keeps the steady state allocation-free.
    last_snapshots: dict[str, list[ProcSnapshot] | None] = {"value": None}

    def rebuild(force: bool = False) -> None:
        """Replace the tray's menu and icon from the latest snapshot."""
        old_menu = tray.contextMenu()
        # Never swap the menu while the user has it open: the deferred
        # delete below would tear it down mid-interaction.
        if old_menu is not None and old_menu.isVisible():
            return
        snapshots = load_snapshots()
        if not force and snapshots == last_snapshots["value"]:
            return
        last_snapshots["value"] = snapshots
        # Drop old refs so they can be reclaimed. Qt will free them
        # once the previous menu's slots stop firing.
        held.clear()
        status_key = _aggregate_status(snapshots)
        if status_key != current_status["key"]:
            tray.setIcon(make_icon(_DOT_COLORS[status_key]))
            current_status["key"] = status_key
        # Tooltip echoes current status for users whose tray hides
        # color cues (some monochrome themes recolor icons).
        tray.setToolTip(f"bgo — {status_key}")
        new_menu = build_menu_from(snapshots)
        held.append(new_menu)
        tray.setContextMenu(new_menu)
        if old_menu is not None:
            # setContextMenu does not take ownership of (or free) the
            # previous menu; without an explicit deleteLater the C++
            # object and its native counterparts outlive the wrapper.
            old_menu.deleteLater()

    def on_activated(reason: "QSystemTrayIcon.ActivationReason") -> None:
        """Show the context menu on left-click and middle-click.

        Right-click is handled by Qt + the host natively (it always
        opens the ``setContextMenu`` menu). Left-click (``Trigger``)
        and middle-click do nothing by default, so we explicitly pop
        the same menu at the cursor.

        Notes on host behavior:
        - KDE Plasma's SNI host *should* deliver Trigger to Qt; if it
          doesn't, the activation is being consumed by the host's own
          left-click action (configurable in Plasma's tray settings).
        - GNOME via AppIndicator typically routes left-click to the
          menu directly without going through Qt's signal.
        - macOS NSStatusItem always fires Trigger on a single click.

        ``$BGO_TRAY_DEBUG=1`` prints the received reason so users can
        diagnose host-specific quirks.
        """
        if os.environ.get("BGO_TRAY_DEBUG"):
            sys.stderr.write(f"bgo tray: activated reason={reason}\n")
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.MiddleClick,
        ):
            menu = tray.contextMenu()
            if menu is not None:
                from PySide6.QtGui import QCursor
                # exec() is blocking but force-shows the menu reliably
                # across SNI hosts. popup() is async and gets eaten by
                # some compositors before paint.
                menu.exec(QCursor.pos())

    tray.activated.connect(on_activated)
    rebuild()
    tray.show()

    # QTimer keeps the polling on Qt's main thread; no GIL juggling,
    # no thread-unsafe menu mutation.
    timer = QTimer()
    timer.setInterval(max(1, poll_seconds) * 1000)
    timer.timeout.connect(rebuild)
    timer.start()
    held.append(timer)

    # SIGINT (Ctrl+C) handling. Qt's C++ event loop blocks in select()
    # and never returns to the Python interpreter, so a plain
    # signal.signal() handler would never fire. Two fixes together:
    # 1. Restore the default Python SIGINT handler that calls app.quit
    #    via Qt's signal-safe path.
    # 2. Run a no-op QTimer every 200ms so the interpreter wakes up
    #    often enough to deliver pending signals to Python handlers.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    sigwake = QTimer()
    sigwake.setInterval(200)
    sigwake.timeout.connect(lambda: None)
    sigwake.start()
    held.append(sigwake)

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
