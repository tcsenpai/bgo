# FAQ

## Why does `bgo` need a separate watcher process?

The watcher polls the target's PID and decides what to do on death.
Running it inline would mean the foreground `bgo start` command never
returns until the target exits — defeating the point. A detached
subprocess (`start_new_session=True`) survives shell logouts and
keeps polling.

## Where is state stored?

`~/.bgo/procs/<name>.json` for state files and
`~/.bgo/logs/<name>.{out,err,watcher}.log` for logs. See
[Architecture](architecture.md#storage-layout).

## How do I run bgo at system boot, not user login?

On Linux, enable systemd lingering for your user:

```bash
loginctl enable-linger $USER
```

Then `bgo autostart install` (which targets `default.target`) will
fire at boot rather than at first login. macOS LaunchAgents already
run at login by default; for boot-time start use a LaunchDaemon
instead (system-scope, not user-scope — out of bgo's scope).

## Does `bgo` survive a reboot?

Procs running at shutdown time are recorded with `status: running`.
After reboot, `bgo resurrect` walks the state files and respawns
each one. Combine with `bgo autostart install` to make this
automatic.

## Why doesn't my tray icon appear on GNOME Wayland?

GNOME doesn't ship a system-tray host. Install the `AppIndicator and
KStatusNotifierItem Support` shell extension once — see
[Tray icon § GNOME Wayland prerequisite](tray.md#gnome-wayland-prerequisite).

## Why is the tray icon a gear with a colored dot?

It's a status indicator: green = at least one proc running and none
errored, red = something errored, gray = nothing running. The shape
(gear) communicates "service/process manager"; the color communicates
state at a glance. See [Tray icon § What you see](tray.md#what-you-see).

## Open-logs doesn't open anything on Linux

Make sure at least one of these is on `$PATH`: `kitty`, `alacritty`,
`wezterm`, `foot`, `ghostty`, `gnome-terminal`, `konsole`,
`xfce4-terminal`, `tilix`, `xterm`. Or set `BGO_TERMINAL` explicitly:

```bash
export BGO_TERMINAL='kitty --'
```

## Can I use `bgo` over plain SSH?

Yes, for the CLI side (start/stop/status/logs). The tray and
notifications need a graphical session — they'll silently no-op or
print a "no system tray available" hint when run over SSH.

## Where does `bgo logs <name>` get its formatting?

`bgo logs` shells out to `tail` for the follow mode and reads the
file directly for static views. Output is the raw bytes that the
target wrote — bgo doesn't reformat them.

## Does `bgo` work on Windows?

No. Zombie detection and process-group kills use POSIX-specific
APIs (`os.killpg`, `/proc/`, `ps -o stat=`). Linux and macOS only.

## I get `Permission denied killing PID …`

The proc is running as a different user. Run `bgo stop <name>` as
that user, or with `sudo` (not recommended — sudo'd bgo writes state
files under root's home, not yours).

## How do I debug the watcher?

Watcher events are logged to `~/.bgo/logs/<name>.watcher.log`. View
with:

```bash
bgo logs <name> --watcher
bgo logs <name> --watcher -f      # live tail
```

## How do I uninstall everything bgo created?

```bash
bgo autostart uninstall
bgo autostart uninstall --tray
rm -rf ~/.bgo                    # state + logs
uv tool uninstall bgo-cli        # the binary itself
# or: pipx uninstall bgo-cli / pip uninstall bgo-cli
```
