# Desktop notifications

bgo fires a desktop notification when a watched process transitions
into the `errored` state — fast-crash budget exhausted, restart
failed, or `--on-fast-crash stop` triggered. The watcher loop is
unaffected by notification failures; notifications are best-effort.

## Backends

Zero new Python dependencies — we shell out to platform-native
binaries, in priority order:

| Order | Binary | Platform |
|---|---|---|
| 1 | `$BGO_NOTIFY_CMD` (override) | any |
| 2 | `notify-send` (libnotify) | Linux |
| 3 | `osascript` (AppleScript) | macOS |
| 4 | `terminal-notifier` (brew) | macOS fallback |

If none are reachable, notifications silently no-op.

## Gating

| Env | Values | Default | Effect |
|---|---|---|---|
| `BGO_NOTIFY` | `off`, `errors`, `all` | `errors` | What level fires |
| `BGO_NOTIFY_CMD` | argv template with `{title}` / `{body}` | — | Bypass backend detection |

`BGO_NOTIFY_CMD` is parsed with `shlex.split` so quoted values group
correctly. Example:

```bash
export BGO_NOTIFY_CMD='/usr/local/bin/my-notifier --title "{title}" --body "{body}"'
```

## When notifications fire

- Watcher exhausts backoff retries → `errored`.
- Watcher restart fails (command not found, permission denied, etc).
- `--on-fast-crash stop` mode hits its first fast-crash.

Manual `bgo stop` and clean exits do **not** fire notifications.
That's deliberate — they're for incidents, not regular ops.

## Testing

Verify your backend is reachable:

```bash
BGO_NOTIFY=all python3 -c "from bgo_cli._notify import notify; \
  print(notify('bgo test', 'hello', 'info'))"
```

Should print `True` and pop a notification. If `False`, set
`BGO_NOTIFY_CMD` or install `notify-send` / `terminal-notifier`.
