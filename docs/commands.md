# Commands

Complete CLI reference. See also [`bgo --help`](#help) for the
in-shell summary.

## Lifecycle

| Command | Description |
|---|---|
| `bgo start <name> -- <cmd>` | Start a process (alias: `open`) |
| `bgo <name> -- <cmd>` | Shorthand for start |
| `bgo stop <name>` | Stop (SIGTERM; alias: `kill`) |
| `bgo stop <name> -f` | Force kill (SIGKILL) |
| `bgo restart <name>` | Restart; preserves watch state and counters |
| `bgo restart <name> --reset-counters` | Also zero `watch.restarts` |
| `bgo restart-stopped` | Pick stopped procs to restart (interactive) |
| `bgo restart-stopped --all` | Restart every stopped proc |
| `bgo restart-stopped <name>...` | Restart named stopped procs |
| `bgo restart-last` | Menu sorted most-recent-first |
| `bgo restart-last --all` | Restart all not-running procs (recent first) |
| `bgo resurrect` | Restart procs that were running before shutdown |
| `bgo delete <name>` | Remove proc + logs (alias: `rm`) |
| `bgo delete <name> --keep-logs` | Remove proc, keep logs |
| `bgo clean` | Drop all stopped procs from the list |

## Inspection

| Command | Description |
|---|---|
| `bgo status` | Process table (alias: `ls`, `list`) |
| `bgo status <name>` | Detail view for one proc |
| `bgo status -w` | Watch mode (auto-refresh every 2s) |
| `bgo status -w --interval N` | Custom refresh interval |
| `bgo status --json` | Machine-readable output |
| `bgo status --plain` | ASCII-only (no color, no glyphs) |
| `bgo status --fancy` | Force Unicode box-drawing rendering |
| `bgo <registered-name>` | Shorthand for `bgo status <name>` |
| `bgo logs <name>` | Last 50 lines |
| `bgo logs <name> -f` | Follow logs |
| `bgo logs <name> -n 100` | Last 100 lines |
| `bgo logs <name> --stderr` | Only stderr |
| `bgo logs <name> --watcher` | Watcher event log |
| `bgo follow <name>` | Alias for `logs -f` (also: `tail`) |

## Watch mode

| Command | Description |
|---|---|
| `bgo start -w <name> -- <cmd>` | Start with watcher attached |
| `bgo -w <name> <cmd>` | Direct mode with watcher |
| `bgo watch <name>` | Attach watcher to a running proc |
| `bgo watch <name> --interval N --min-uptime N --on-fast-crash MODE` | Tune |
| `bgo unwatch <name>` | Detach watcher; proc keeps running |

Full details: [Watch mode](watch-mode.md).

## Autostart policy

| Command | Description |
|---|---|
| `bgo start --autostart unless-stopped <name> -- <cmd>` | Start with policy |
| `bgo autostart set <name> {always,unless-stopped,never}` | Change policy |
| `bgo autostart show <name>` | Show current policy |

Default is `unless-stopped`. See [Login autostart](autostart.md) for details.

## Autostart

| Command | Description |
|---|---|
| `bgo autostart install` | Run `bgo resurrect` at login |
| `bgo autostart install --tray` | Launch the tray icon at login |
| `bgo autostart uninstall [--tray]` | Remove the autostart entry |
| `bgo autostart status [--json]` | Show what's installed |

Full details: [Login autostart](autostart.md).

## Tray (optional)

| Command | Description |
|---|---|
| `bgo tray` | Launch the system-tray icon |
| `bgo tray --poll N` | Poll interval (default 3s) |
| `bgo tray --auto-install` | Inject PySide6 without prompting |

Full details: [Tray icon](tray.md).

## Help

```bash
bgo --help
bgo <subcommand> --help
```

`bgo` (no args) prints usage. `bgo <unknown>` errors out without
silently spawning anything.
