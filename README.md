# bgo — Background Go

Lightweight, zero-dep background process manager inspired by pm2.
Detach any binary or script from your shell with one command.

[![PyPI](https://img.shields.io/pypi/v/bgo-cli.svg)](https://pypi.org/project/bgo-cli/)
[![Python](https://img.shields.io/pypi/pyversions/bgo-cli.svg)](https://pypi.org/project/bgo-cli/)
[![License](https://img.shields.io/pypi/l/bgo-cli.svg)](LICENSE)

PyPI: <https://pypi.org/project/bgo-cli/>

## Features

- **Simple syntax** — `bgo <name> -- <command>`
- **Unix-style aliases** — `bgo open` / `kill` / `rm` / `ls`
- **Status monitoring** — CPU, memory, uptime; plain / normal / fancy
  tables with auto-detection
- **Log management** — stdout / stderr / watcher logs with follow mode
- **Lifecycle** — start, stop, restart, restart-stopped, restart-last,
  resurrect
- **Watch mode** — auto-restart crashed processes with fast-crash backoff
- **Desktop notifications** on errored transitions
- **Login autostart** via systemd-user (Linux) or LaunchAgent (macOS)
- **Tray icon** (optional) — PySide6, gear+dot status indicator,
  KDE/Hyprland/GNOME/macOS
- **Scriptable** — `--json` output for any pipeline
- **Zero runtime dependencies** in the core; one optional extra for the tray

## Quick start

```bash
uv tool install bgo-cli          # see docs/installation.md for alternatives

bgo myserver -- python3 -m http.server 8080
bgo ls
bgo logs myserver -f
bgo restart myserver
bgo stop myserver
```

`bgo` with no args prints help. `bgo <unknown>` errors out rather than
silently spawning something.

## Documentation

Long-form docs live in [`docs/`](docs/README.md):

| Topic | Where |
|---|---|
| Install paths (uv / pipx / pip / install.sh / manual) | [docs/installation.md](docs/installation.md) |
| Full CLI reference | [docs/commands.md](docs/commands.md) |
| Watch mode (auto-restart + fast-crash policy) | [docs/watch-mode.md](docs/watch-mode.md) |
| Desktop notifications | [docs/notifications.md](docs/notifications.md) |
| Login autostart (systemd / launchd) | [docs/autostart.md](docs/autostart.md) |
| Tray icon (optional, PySide6) | [docs/tray.md](docs/tray.md) |
| Module architecture | [docs/architecture.md](docs/architecture.md) |
| FAQ | [docs/faq.md](docs/faq.md) |
| Contributing | [docs/contributing.md](docs/contributing.md) |

## Sample status table

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ NAME         STATUS     PID      CPU    MEM    UPTIME    WATCH      COMMAND                    ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃ web          ● online   12345    2.5    0.1    00:05     ✓ 0        python3 -m http.server 8080 ┃
┃ api          ● online   12346    0.0    0.0    01:23     ✓ 3        node server.js              ┃
┃ worker       ○ stopped  -        -      -      -         ⚠ errored  python3 worker.py           ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
Total: 3 | ● online: 2 | ○ stopped: 1

⚠ 1 errored:
   worker — 4 consecutive fast-crashes
     bgo logs worker --watcher   |   bgo restart worker
```

Override the rendering with `--plain` / `--fancy` or
`BGO_TABLE=plain|normal|fancy`.

## Storage

- State: `~/.bgo/procs/<name>.json` — one file per process, atomic writes.
- Logs: `~/.bgo/logs/<name>.{out,err,watcher}.log`.

Full layout: [docs/architecture.md](docs/architecture.md#storage-layout).

## Testing

```bash
uv run pytest tests/ -v
```

169 tests covering state I/O, atomic writes, command-shape detection,
name derivation, liveness + zombie filtering, watch-config inheritance,
table rendering, desktop notifications, login autostart, and tray menu
construction.

## Requirements

- Python 3.10+
- Linux or macOS
- Optional `[tray]` extra: PySide6 (Qt for Python, LGPL)

## License

[MIT](LICENSE).
