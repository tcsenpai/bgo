# Login autostart

`bgo autostart` installs a per-user service that runs `bgo resurrect`
on session start, restoring managed processes according to their
per-proc autostart policy. Backends are auto-detected:

| Platform | Backend | Path |
|---|---|---|
| Linux | systemd user unit | `~/.config/systemd/user/bgo-resurrect.service` |
| macOS | LaunchAgent | `~/Library/LaunchAgents/sh.discus.bgo.resurrect.plist` |

## Commands

```bash
bgo autostart install            # resurrect at login
bgo autostart install --tray     # also launch the tray icon at login
bgo autostart status             # show what's installed
bgo autostart status --json      # machine-readable
bgo autostart uninstall          # remove resurrect
bgo autostart uninstall --tray   # remove tray entry only
bgo autostart set <name> always  # set per-proc policy
bgo autostart show <name>        # show per-proc policy
```

`install` is idempotent — re-running overwrites the unit content but
doesn't duplicate registrations.

## Linux: lingering

systemd user units only run after the user logs in. To start the
resurrect unit before a graphical session exists (e.g. headless
servers, automated reboots), enable lingering once:

```bash
loginctl enable-linger $USER
```

This modifies system state, so bgo does **not** run it automatically
— enable it yourself if you need that behavior.

## macOS: LaunchAgent

The plist is loaded via `launchctl bootstrap` (modern) with a fallback
to `launchctl load -w` (legacy). `RunAtLoad=true` triggers on login.

```bash
# Manual inspection
plutil -p ~/Library/LaunchAgents/sh.discus.bgo.resurrect.plist
launchctl list | grep sh.discus.bgo
```

## Tray autostart

`bgo autostart install --tray` writes a separate entry:

| Platform | Path |
|---|---|
| Linux | `~/.config/autostart/bgo-tray.desktop` (XDG spec) |
| macOS | `~/Library/LaunchAgents/sh.discus.bgo.tray.plist` |

The tray entry is independent of the resurrect entry — install both
for the typical "tray plus restored procs at login" workflow:

```bash
bgo autostart install            # resurrect
bgo autostart install --tray     # tray
```

See [Tray icon](tray.md) for tray-specific requirements (PySide6
install, GNOME extension, etc).

## How `resurrect` decides what to restart

Each proc has an `autostart` policy stored in its state file:

| Policy | Behavior |
|---|---|
| `always` | Restart on login unless already running. |
| `unless-stopped` (default) | Restart on login unless the user manually stopped it (`status: stopped`). |
| `never` | Never restart on login. |

A proc is only resurrected when its recorded PID is not currently alive
(i.e. it died with the session). New procs default to
`unless-stopped`; use `--autostart` at start time or `bgo autostart set`
to change it later.
