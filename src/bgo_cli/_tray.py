"""System-tray icon for bgo (optional extra ``bgo-cli[tray]``).

This module is imported lazily by ``cmd_tray`` and is the only place
``pystray`` / ``Pillow`` are referenced at runtime. Splitting the
import-bearing glue (``_run_tray``) from the pure menu construction
(``build_menu_spec``) lets us unit-test the menu without the optional
deps installed.

UI model
========
We poll ``~/.bgo/procs/*.json`` every ``poll_seconds`` (default 3,
overridable by ``$BGO_TRAY_POLL`` or ``--poll``). The full menu is
rebuilt from the snapshot — pystray rebuilds cheaply, and a
declarative menu avoids the bugs that come from in-place mutation.

Actions never duplicate state-management logic from the core script.
Every Start/Stop/Restart click shells out to the ``bgo`` binary, so
behavior matches the CLI exactly and we don't risk diverging.
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


# --- pystray glue --------------------------------------------------------


def _make_icon_image():  # pragma: no cover — exercised only with Pillow
    """Build a tiny B/W icon image. Imported lazily so tests don't need PIL."""
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGB", (size, size), "black")
    draw = ImageDraw.Draw(img)
    # Three horizontal bars — readable at 16px.
    for y in (14, 28, 42):
        draw.rectangle((10, y, size - 10, y + 8), fill="white")
    return img


def _run_tray(poll_seconds: int) -> int:  # pragma: no cover — needs pystray
    """Run the pystray event loop until the user quits.

    This is the only function in the module that requires the optional
    deps. Kept thin: the bulk of behavior lives in the pure helpers
    above so it stays testable.
    """
    import pystray
    from pystray import MenuItem as Item, Menu

    quit_flag = {"stop": False}

    def make_proc_submenu(snap: ProcSnapshot) -> Menu:
        # ``bgo start <name>`` without a command argument is rejected
        # by the core CLI (start requires REMAINDER). For a known
        # registered proc the correct re-spawn is ``bgo restart``,
        # which preserves the stored command. We surface "Restart"
        # for online procs and "Start" (which shells out to restart
        # under the hood) for stopped ones — both routes hit the
        # same code path, but the labels match user expectations.
        is_running = snap.status == "running" and not snap.errored
        primary_label = "Restart" if is_running else "Start"
        return Menu(
            Item(primary_label, lambda _icon, _it, n=snap.name: run_bgo("restart", n)),
            Item("Stop",        lambda _icon, _it, n=snap.name: run_bgo("stop", n)),
            Menu.SEPARATOR,
            Item("Open logs", lambda _icon, _it, n=snap.name: _open_logs(n)),
        )

    def build_menu() -> Menu:
        spec = build_menu_spec(load_snapshots())
        items: list = [Item(spec.title, None, enabled=False), Menu.SEPARATOR]
        for snap in spec.procs:
            label = f"{snap.name} [{_status_label(snap)}]"
            items.append(Item(label, make_proc_submenu(snap)))
        items.append(Menu.SEPARATOR)
        for label, cmd in spec.actions:
            if cmd == "__quit__":
                def _quit(icon, _item):  # noqa: ANN001
                    quit_flag["stop"] = True
                    icon.stop()
                items.append(Item(label, _quit))
            elif cmd == "__refresh__":
                items.append(Item(label, lambda icon, _it: icon.update_menu()))
            else:
                items.append(
                    Item(label, lambda _icon, _it, c=cmd: run_bgo(c))
                )
        return Menu(*items)

    icon = pystray.Icon(
        "bgo",
        icon=_make_icon_image(),
        title="bgo",
        menu=build_menu(),
    )

    # Periodically rebuild the menu so status reflects fresh snapshots.
    import threading

    def poller() -> None:
        import time
        while not quit_flag["stop"]:
            time.sleep(poll_seconds)
            try:
                icon.menu = build_menu()
                icon.update_menu()
            except Exception:
                # Pystray internals are toolkit-specific; swallow to
                # keep the loop alive on transient errors.
                pass

    t = threading.Thread(target=poller, daemon=True)
    t.start()
    icon.run()
    return 0


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
