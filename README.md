# bgo - Background Go

A lightweight, simple background process manager inspired by pm2. Run any binary/script detached from your shell with ease.

## Features

- 🚀 **Simple syntax** - `bgo <name> -- <command>`
- 📊 **Status monitoring** - CPU, memory, uptime with clean table styling
- 📝 **Log management** - stdout/stderr with follow mode
- 🔄 **Start/Stop/Restart** - Full lifecycle control
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

```
NAME         STATUS     PID      CPU     MEM     UPTIME       COMMAND
────────────────────────────────────────────────────────────────────────────────
web          online     12345    2.5     0.1     00:05        python3 -m http.s...
api          online     12346    0.0     0.0     01:23        node server.js
worker       stopped    -        -       -       -            python3 worker.py
────────────────────────────────────────────────────────────────────────────────
Total: 3 | online: 2 | stopped: 1
```

## Storage

- State: `~/.bgo/state.json`
- Logs: `~/.bgo/logs/<name>.out.log` and `<name>.err.log`

## Requirements

- Python 3.7+
- Unix-like system (Linux/macOS)

## License

MIT
