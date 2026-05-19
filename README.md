# bgo - Background Go

Lightweight, zero-dep background process manager inspired by pm2.
Detach any binary or script from your shell with one command.

[![PyPI](https://img.shields.io/pypi/v/bgo-cli.svg)](https://pypi.org/project/bgo-cli/)
[![Python](https://img.shields.io/pypi/pyversions/bgo-cli.svg)](https://pypi.org/project/bgo-cli/)
[![License](https://img.shields.io/pypi/l/bgo-cli.svg)](LICENSE)

PyPI: https://pypi.org/project/bgo-cli/

## Features

- 🚀 **Simple syntax** — `bgo <name> -- <command>`
- 🐧 **Unix-style aliases** — `bgo open` / `kill` / `rm` / `ls`
- 📊 **Status monitoring** — CPU, memory, uptime in plain / normal / fancy tables (auto-detect)
- 📝 **Log management** — stdout / stderr / watcher logs with follow mode
- 🔄 **Lifecycle** — start, stop, restart, restart-stopped, restart-last, resurrect
- 👁 **Watch mode** — auto-restart crashed processes with fast-crash backoff
- 🧹 **Auto-cleanup** — clean stopped procs; keep logs on delete if desired
- 🤖 **Scriptable** — `--json` output for any pipeline
- ⚡ **Zero runtime dependencies** — pure Python 3.9+

## Installation

### Recommended: `uv`

[`uv`](https://docs.astral.sh/uv/) installs `bgo-cli` into an isolated
environment and links the `bgo` command onto your PATH. No global
Python pollution, no virtualenv to manage.

```bash
uv tool install bgo-cli
```

Upgrade:
```bash
uv tool upgrade bgo-cli
```

Uninstall:
```bash
uv tool uninstall bgo-cli
```

### Alternatives

```bash
# pipx (also isolated, very similar to uv tool)
pipx install bgo-cli

# Plain pip (installs into the active environment)
pip install bgo-cli

# Install script — builds nothing, just copies the single-file script
./install.sh             # /usr/local/bin (sudo)
./install.sh --local     # ~/.local/bin (no sudo)
./install.sh --help      # --force / --uninstall

# Or fully manual — bgo is a single file
cp bgo ~/.local/bin/     # or /usr/local/bin/
ln -s "$(pwd)/bgo" ~/.local/bin/bgo
```

### Verify

```bash
bgo --help
bgo ls          # no procs registered yet
```

## Quick Start

```bash
# Start a process
bgo myserver -- python3 -m http.server 8080
bgo open myserver -- python3 -m http.server 8080   # alias

# Check status
bgo status        # full alias chain: status / ls / list
bgo ls

# Status detail for one proc (or: bgo <registered-name>)
bgo myserver

# View logs
bgo logs myserver
bgo logs myserver -f        # follow (tail -f)
bgo follow myserver         # alias for logs -f

# Stop / restart / delete
bgo stop myserver           # or: bgo kill myserver
bgo restart myserver
bgo delete myserver         # or: bgo rm myserver
bgo rm myserver --keep-logs # preserve log files

# Bare `bgo` prints help; `bgo <unknown>` errors out (never silently spawns)
bgo
```

## Commands

### Lifecycle

| Command | Description |
|---|---|
| `bgo start <name> -- <cmd>` | Start a process (alias: `open`) |
| `bgo <name> -- <cmd>` | Shorthand for start |
| `bgo stop <name>` | Stop (SIGTERM, alias: `kill`) |
| `bgo stop <name> -f` | Force kill (SIGKILL) |
| `bgo restart <name>` | Restart; preserves watch state and counters |
| `bgo restart <name> --reset-counters` | Also zero `watch.restarts` |
| `bgo restart-stopped` | Pick stopped procs to restart (interactive) |
| `bgo restart-stopped --all` | Restart every stopped proc |
| `bgo restart-stopped <name>...` | Restart named stopped procs |
| `bgo restart-last` | Menu sorted most-recent-first |
| `bgo restart-last --all` | Restart all not-running procs in recent order |
| `bgo resurrect` | Restart all procs that were running before shutdown |
| `bgo delete <name>` | Remove proc + logs (alias: `rm`) |
| `bgo delete <name> --keep-logs` | Remove proc, keep logs |
| `bgo clean` | Drop all stopped procs from the list |

### Inspection

| Command | Description |
|---|---|
| `bgo status` | Process table (alias: `ls`, `list`) |
| `bgo status <name>` | Detail view for one proc |
| `bgo status -w` | Watch mode (auto-refresh every 2s) |
| `bgo status -w --interval N` | Custom refresh interval |
| `bgo status --json` | Machine-readable output |
| `bgo status --plain` | ASCII-only output (no color, no glyphs) |
| `bgo status --fancy` | Force Unicode box-drawing rendering |
| `bgo <registered-name>` | Shorthand for `bgo status <name>` |
| `bgo logs <name>` | Last 50 lines |
| `bgo logs <name> -f` | Follow logs |
| `bgo logs <name> -n 100` | Last 100 lines |
| `bgo logs <name> --stderr` | Only stderr |
| `bgo logs <name> --watcher` | Watcher event log |
| `bgo follow <name>` | Alias for `logs -f` (also: `tail`) |

### Watch mode

| Command | Description |
|---|---|
| `bgo start -w <name> -- <cmd>` | Start with watcher attached |
| `bgo -w <name> <cmd>` | Direct mode with watcher |
| `bgo watch <name>` | Attach watcher to a running proc |
| `bgo watch <name> --interval N --min-uptime N --on-fast-crash MODE` | Tune |
| `bgo unwatch <name>` | Detach watcher, keep proc |

## Examples

```bash
# Python HTTP server
bgo web -- python3 -m http.server 8080

# Node.js app with watcher
bgo -w api -- npm start

# Custom binary with working directory
bgo start dashboard --cwd /opt/app -- node server.js

# Inspect one proc
bgo web

# Scripted: stop every online proc via JSON
bgo status --json | python3 -c '
import json, sys, subprocess
for p in json.load(sys.stdin):
    if p["status"] == "online":
        subprocess.run(["bgo", "stop", p["name"]])
'
```

## Status Table

The table auto-detects terminal capabilities and picks the best rendering:

| Level | Trigger | What you get |
|---|---|---|
| `plain` | non-TTY (pipes, CI logs), `TERM=dumb`, or `--plain` | ASCII only, no color, no glyphs |
| `normal` | TTY without UTF-8 locale | ANSI color + ASCII rules |
| `fancy` | TTY + UTF-8 locale (default) | ANSI color + Unicode box-drawing |

Override with `--plain` / `--fancy` or `BGO_TABLE=plain|normal|fancy`.

Sample (fancy):
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ NAME         STATUS     PID      CPU    MEM    UPTIME    WATCH      COMMAND                    ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃ web          ● online   12345    2.5    0.1    00:05     ✓ 0        python3 -m http.server 8080 ┃
┃ api          ● online   12346    0.0    0.0    01:23     ✓ 3        node server.js              ┃
┃ worker       ○ stopped  -        -      -      -         ⚠ errored  python3 worker.py           ┃
┃ batch        ● online   12347    0.0    0.0    02:11     ·          ./batch                     ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
Total: 4 | ● online: 3 | ○ stopped: 1

⚠ 1 errored:
   worker — 4 consecutive fast-crashes
     bgo logs worker --watcher   |   bgo restart worker
```

CPU / MEM / uptime are pulled in a single batched `ps` call regardless of how many procs are running.

## Watch Mode

Watch mode runs a sidecar process per watched proc that polls the
target and restarts it on crash. State (restart count, error reason,
last stderr tail) is recorded in the proc JSON and surfaced via
`bgo status`.

### Quick start

```bash
bgo start -w myapi -- node server.js          # start with watcher
bgo -w myapi node server.js                   # direct-mode variant
bgo watch myapi                               # attach to a running proc
bgo watch myapi --interval 5 --min-uptime 3 --on-fast-crash backoff
bgo unwatch myapi                             # detach, keep proc
bgo logs myapi --watcher                      # inspect events
```

### Fast-crash policy

If a process dies before `--min-uptime` (default 2s) it's a *fast crash*. Reaction depends on `--on-fast-crash`:

| Mode | Behavior |
|---|---|
| `backoff` (default) | Wait 2s, retry. Then 4s, then 8s. After 4 consecutive fast-crashes, mark `errored` and exit watcher. |
| `stop` | Mark `errored` on the first fast-crash. |
| `retry` | Retry indefinitely, capped at 8s backoff. |

When a proc enters `errored`:
- WATCH column shows `⚠ errored` (or `[!] errored` in plain).
- Status footer summarizes errored procs and hints at the recovery commands.
- `bgo status <name>` detail shows the error reason and last stderr tail.
- `bgo restart <name>` clears the errored flag and re-spawns the watcher. Restart counter is **preserved** by default — use `--reset-counters` to zero it.

### Tunables

| Flag | Default | Notes |
|---|---|---|
| `--interval N` | 3 | Poll interval after the initial uptime window |
| `--min-uptime N` | 2 | Crash threshold; sub-window polled at high frequency |
| `--on-fast-crash MODE` | `backoff` | One of `backoff`, `stop`, `retry` |
| `--reset` | off | `bgo watch` only — reset prior watch config to defaults |

## Desktop notifications

`bgo` fires a desktop notification when a watched process enters the
`errored` state (fast-crash budget exhausted, restart failed, etc.).
Zero new dependencies — it shells out to the platform's native
notifier:

- Linux: `notify-send` (libnotify; install via your distro).
- macOS: built-in `osascript`. Falls back to `terminal-notifier` if
  available.

Notifications are best-effort — if no notifier is reachable, the
watcher carries on silently.

| Env var | Values | Default | Effect |
|---|---|---|---|
| `BGO_NOTIFY` | `off`, `errors`, `all` | `errors` | What to fire on |
| `BGO_NOTIFY_CMD` | argv template with `{title}` / `{body}` | — | Override the backend entirely |

## Autostart at login

`bgo autostart` installs a per-user service that runs `bgo resurrect`
on session start, restoring every process that was registered as
`running` at shutdown. Backends are auto-detected:

- Linux → systemd user unit at `~/.config/systemd/user/bgo-resurrect.service`
- macOS → LaunchAgent at `~/Library/LaunchAgents/sh.discus.bgo.resurrect.plist`

```bash
bgo autostart install            # install resurrect at login
bgo autostart install --tray     # also install the tray icon at login
bgo autostart status             # show what's installed
bgo autostart status --json      # machine-readable
bgo autostart uninstall          # remove
bgo autostart uninstall --tray   # remove tray entry only
```

On Linux, services only run after the user logs in. To start the
resurrect unit before a graphical session exists (e.g. headless
servers), enable lingering once: `loginctl enable-linger $USER`.
Neither flag is set automatically — it modifies system state.

## Tray icon (optional)

`bgo tray` runs a system-tray icon (a gear with a colored status dot)
that lists all registered procs and exposes one-click actions for each.

**Icon dot color**:
- 🟢 green — at least one proc running, none errored
- 🔴 red   — any proc errored
- ⚫ gray  — empty or all stopped

**Menu**: each proc gets a submenu prefixed with a Unicode status glyph
(● online / ○ stopped / ⚠ errored). The submenu offers Start (or
Restart when online) / Stop / Open logs. Global entries: Resurrect all
/ Refresh now / Quit. The menu rebuilds from `~/.bgo/procs/*.json`
every few seconds; every action shells out to `bgo` so behavior
matches the CLI exactly.

**Open logs** spawns `bgo logs <name> -f` in a new terminal window
(live tail with formatting), not the raw log file in an editor. Linux
probes a curated list (kitty, alacritty, wezterm, foot, ghostty,
gnome-terminal, konsole, xfce4-terminal, tilix, xterm) and picks the
first one on PATH. macOS uses AppleScript to spawn Terminal.app. Set
`BGO_TERMINAL='kitty --'` (or any `binary [exec-flag]`) for an
explicit override; `BGO_TERMINAL=iterm` switches macOS to iTerm2.

**Left- and right-click** both open the menu. Middle-click does too.
Right-click is always handled by the host directly. Left/middle-click
is wired by us via Qt's `activated` signal — most hosts deliver it,
but a few (notably some KDE Plasma configurations that bind a custom
left-click action) may swallow it; in that case right-click still
works and the host setting is overrideable in tray config. Set
`BGO_TRAY_DEBUG=1` to log the activation reason to stderr while
debugging.

### Platform support

Tray UI uses **PySide6** (Qt for Python, LGPL). One library, native
support on every target:

| Platform | What happens |
|---|---|
| **macOS** | Native `NSStatusItem` in the menu bar |
| **KDE Plasma 6 (Wayland or X11)** | StatusNotifierItem, no setup |
| **Hyprland / sway + waybar** | SNI via waybar's `tray` module |
| **GNOME Wayland** | Needs the AppIndicator shell extension (see below) |

### Install

PySide6 is shipped as an optional extra to keep the core install
zero-dep:

```bash
# uv (recommended)
uv tool install bgo-cli --with PySide6

# pipx
pipx install bgo-cli
pipx inject bgo-cli PySide6

# pip
pip install 'bgo-cli[tray]'
```

If you forget, the first run of `bgo tray` detects your installer
(uv tool / pipx / pip) and offers to inject the dep for you. Skip
the confirmation with `--auto-install` or `BGO_TRAY_AUTOINSTALL=1`.

### Run in the background

The tray is just another command — run it under `bgo` itself:

```bash
bgo start -w bgotray -- bgo tray   # -w auto-restarts on crash
```

Or, simpler, install it as a login autostart entry:

```bash
bgo autostart install --tray       # tray starts on every login
```

### GNOME Wayland prerequisite

GNOME ships no system-tray host of its own. Install the
`AppIndicator and KStatusNotifierItem Support` shell extension once:

```bash
sudo dnf install gnome-shell-extension-appindicator   # Fedora
sudo apt install gnome-shell-extension-appindicator   # Debian/Ubuntu
gnome-extensions enable appindicatorsupport@rgcjonas.gmail.com
```

Log out and back in. KDE / Hyprland / macOS users do not need this
step.

### Tuning

| Flag / env | Default | Effect |
|---|---|---|
| `--poll N`, `BGO_TRAY_POLL` | `3` | Snapshot refresh interval (seconds) |
| `--auto-install`, `BGO_TRAY_AUTOINSTALL=1` | off | Skip the install prompt |
| `BGO_TERMINAL` | (auto-probe) | Terminal emulator for Open-logs (`'kitty --'`, `iterm`, etc.) |
| `BGO_TRAY_DEBUG=1` | off | Log activation reasons to stderr |

## Storage

- State: `~/.bgo/procs/<name>.json` — one file per process, written atomically (tmp + `os.replace`)
- Logs: `~/.bgo/logs/<name>.out.log`, `<name>.err.log`, `<name>.watcher.log`

## Testing

```bash
python3 -m pytest tests/ -v
```

169 tests covering state I/O, atomic writes, command-shape detection, name derivation, liveness + zombie filtering, watch-config inheritance, table rendering, desktop notifications, login autostart (systemd-user / launchd), and tray menu construction.

## Requirements

- Python 3.10+
- Linux or macOS (zombie detection is platform-aware: `/proc` on Linux, `ps -o stat=` on macOS)
- Optional `[tray]` extra: PySide6 (Qt for Python, LGPL)

## License

MIT
