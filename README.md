# bgo - Background Go

A lightweight, simple background process manager inspired by pm2. Run any binary/script detached from your shell with ease.

## Features

- 🚀 **Simple syntax** - `bgo <name> -- <command>`
- 📊 **Status monitoring** - CPU, memory, uptime with clean table styling
- 📝 **Log management** - stdout/stderr with follow mode
- 🔄 **Start/Stop/Restart** - Full lifecycle control
- 👁 **Watch mode** - Auto-restart crashed processes with fast-crash backoff
- 🧹 **Auto-cleanup** - Remove dead processes
- ⚡ **Zero dependencies** - Pure Python 3

## Installation

```bash
# Option 1: Copy to a directory in your PATH
cp bgo ~/.local/bin/
# or
cp bgo /usr/local/bin/

# Option 2: Create a symlink
ln -s $(pwd)/bgo ~/.local/bin/bgo
```

## Quick Start

```bash
# Start a process
bgo myserver -- python3 -m http.server 8080

# Check status (colored, responsive table)
bgo status

# View logs
bgo logs myserver
bgo logs myserver -f        # follow mode (tail -f)
bgo follow myserver         # shorthand for logs -f

# Stop/restart
bgo stop myserver
bgo restart myserver

# Delete when done
bgo delete myserver
```

## Commands

| Command | Description |
|---------|-------------|
| `bgo start <name> -- <cmd>` | Start a process with a name |
| `bgo <name> -- <cmd>` | Shorthand for start |
| `bgo status` | List all processes with stats (colored) |
| `bgo stop <name>` | Stop a process (SIGTERM) |
| `bgo stop <name> -f` | Force kill (SIGKILL) |
| `bgo restart <name>` | Restart a process |
| `bgo restart-stopped` | Pick stopped procs to restart (interactive menu) |
| `bgo restart-stopped --all` | Restart every stopped/dead proc |
| `bgo restart-stopped <name>...` | Restart specific stopped procs by name |
| `bgo restart-last` | Interactive menu of procs sorted most-recent-first |
| `bgo restart-last --all` | Restart all not-running procs in recent order |
| `bgo logs <name>` | Show last 50 lines |
| `bgo logs <name> -f` | Follow logs (tail -f) |
| `bgo logs <name> -n 100` | Show last 100 lines |
| `bgo logs <name> --stderr` | Show only stderr |
| `bgo follow <name>` | Shorthand for `logs -f` |
| `bgo clean` | Remove stopped processes |
| `bgo delete <name>` | Remove process and logs |
| `bgo start -w <name> -- <cmd>` | Start with auto-restart watcher |
| `bgo -w <name> <cmd>` | Direct mode with watcher |
| `bgo watch <name>` | Attach watcher to an already-running process |
| `bgo watch <name> --interval N --min-uptime N --on-fast-crash MODE` | Tune watcher |
| `bgo unwatch <name>` | Detach watcher (keep process running) |
| `bgo logs <name> --watcher` | View watcher events (restarts, errors) |

## Examples

```bash
# Python HTTP server
bgo web -- python3 -m http.server 8080

# Node.js app
bgo api -- npm start

# Custom binary
bgo worker -- ./my-worker --verbose --workers 4

# With working directory
bgo start dashboard --cwd /opt/app -- node server.js

# Watch logs (multiple ways)
bgo logs api -f
bgo follow api
bgo tail api

# Stop all (bash loop)
for name in $(bgo status | grep online | awk '{print $1}'); do bgo stop $name; done
```

## Status Table

The status table features:
- **Auto-sized columns** - Fits your terminal width
- **Color coding** - Green for online, red for stopped
- **Resource usage** - Live CPU%, MEM%, and uptime from `ps`
- **Watch column** - Restart count for watched procs, errored state if applicable

```
NAME         STATUS     PID      CPU     MEM     UPTIME       WATCH       COMMAND
────────────────────────────────────────────────────────────────────────────────
web          online     12345    2.5     0.1     00:05        ✓ 0         python3 -m http.s...
api          online     12346    0.0     0.0     01:23        ✓ 3         node server.js
worker       stopped    -        -       -       -            ⚠ errored   python3 worker.py
batch        online     12347    0.0     0.0     02:11        -           ./batch
────────────────────────────────────────────────────────────────────────────────
Total: 4 | online: 3 | stopped: 1

⚠ 1 errored:
   worker — 4 consecutive fast-crashes
     bgo logs worker --watcher   |   bgo restart worker
```

## Watch Mode

Watch mode runs a small sidecar process per watched proc that polls the target
and restarts it on crash. State (restart count, error reason, last stderr tail)
is recorded in the proc JSON and surfaced via `bgo status`.

### Quick start

```bash
# Start with watcher attached
bgo start -w myapi -- node server.js

# Direct mode with -w
bgo -w myapi node server.js

# Attach a watcher to an existing running proc
bgo watch myapi

# Custom config
bgo watch myapi --interval 5 --min-uptime 3 --on-fast-crash backoff

# Detach watcher (proc keeps running)
bgo unwatch myapi

# Inspect restart events
bgo logs myapi --watcher
```

### Fast-crash policy

If a process dies before `--min-uptime` (default 2s), it's a *fast crash*.
The watcher reacts based on `--on-fast-crash`:

| Mode | Behavior |
|------|----------|
| `backoff` (default) | Wait 2s, retry. If fast-crashes again, wait 4s. Then 8s. After 4 consecutive fast-crashes, mark `errored` and exit watcher. |
| `stop` | Mark `errored` on the first fast-crash. |
| `retry` | Keep retrying indefinitely with a capped 8s backoff. |

When a proc enters `errored` state:
- `bgo status` shows `⚠ errored` in the WATCH column.
- A footer line summarizes errored procs.
- `bgo status <name>` detail shows the error reason and last stderr tail.
- `bgo restart <name>` clears errored state, resets the restart counter, and re-spawns the watcher.

### Tunables

| Flag | Default | Notes |
|------|---------|-------|
| `--interval N` | 3 | Poll interval (seconds) after the initial uptime window. |
| `--min-uptime N` | 2 | Crash threshold. Sub-window is polled at high frequency for accuracy. |
| `--on-fast-crash MODE` | `backoff` | One of `backoff`, `stop`, `retry`. |
| `--reset` | off (`bgo watch` only) | Reset prior watch config to defaults. |

## Storage

- State: `~/.bgo/procs/<name>.json` (one file per process)
- Logs: `~/.bgo/logs/<name>.out.log`, `<name>.err.log`, `<name>.watcher.log`

## Requirements

- Python 3.7+
- Unix-like system (Linux/macOS)

## License

MIT
