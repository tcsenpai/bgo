# Watch mode

Watch mode runs a *sidecar* process per watched proc — a detached
Python subprocess that polls the target and restarts it on crash.
State (restart count, error reason, last stderr tail) is recorded in
the proc JSON and surfaced via `bgo status`.

## Quick start

```bash
bgo start -w myapi -- node server.js          # start with watcher
bgo -w myapi node server.js                   # direct-mode variant
bgo watch myapi                               # attach to a running proc
bgo watch myapi --interval 5 --min-uptime 3 --on-fast-crash backoff
bgo unwatch myapi                             # detach; proc keeps running
bgo logs myapi --watcher                      # inspect watcher events
```

## Fast-crash policy

If a process dies before `--min-uptime` (default 2s) it's a *fast
crash*. Reaction depends on `--on-fast-crash`:

| Mode | Behavior |
|---|---|
| `backoff` (default) | Wait 2s, retry. Then 4s, then 8s. After 4 consecutive fast-crashes, mark `errored` and exit watcher. |
| `stop` | Mark `errored` on the first fast-crash. |
| `retry` | Retry indefinitely, capped at 8s backoff. |

When a proc enters `errored`:

- WATCH column shows `⚠ errored` (or `[!] errored` in plain).
- Status footer summarises errored procs and hints at recovery commands.
- `bgo status <name>` detail shows the error reason and last stderr tail.
- A desktop notification fires (see [Notifications](notifications.md)).
- `bgo restart <name>` clears the errored flag and re-spawns the
  watcher. Restart counter is **preserved** by default — use
  `--reset-counters` to zero it.

## Tunables

| Flag | Default | Notes |
|---|---|---|
| `--interval N` | 3 | Poll interval after the initial uptime window |
| `--min-uptime N` | 2 | Crash threshold; sub-window polled at high frequency |
| `--on-fast-crash MODE` | `backoff` | One of `backoff`, `stop`, `retry` |
| `--reset` | off | `bgo watch` only — reset prior watch config to defaults |

## Internals

The watcher is invoked as `bgo __watcher__ <name>` and runs the loop
in `bgo_cli._watcher.cmd_watcher_loop`. It polls every `interval`
seconds, computes uptime from the proc's `started_at`, and respawns
the target in place when it dies. The early-check phase polls at
0.2s during the first `min_uptime` window so fast-crashes are caught
with accurate uptime readings even when `interval > min_uptime`.

See [Architecture](architecture.md) for the full module layout.
