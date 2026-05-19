# Tray icon (optional)

`bgo tray` runs a system-tray icon — a gear with a colored status dot
— that lists every registered proc and exposes one-click actions for
each. The menu rebuilds from `~/.bgo/procs/*.json` every few seconds,
so it always reflects current state.

## What you see

**Icon dot color** (status of all registered procs combined):

| Dot | Meaning |
|---|---|
| 🟢 green | at least one proc running, none errored |
| 🔴 red | any proc is errored |
| ⚫ gray | empty or all stopped |

**Menu glyph** (per-proc, in submenu labels):

| Glyph | Meaning |
|---|---|
| ● | online (running, not errored) |
| ○ | stopped |
| ⚠ | errored |

**Per-proc submenu**:

- **Restart** (when online) or **Start** (when stopped) — both route
  to `bgo restart <name>` under the hood, because `bgo start` without
  a command is rejected by the CLI; `restart` respawns with the
  stored command.
- **Stop**
- **Open logs** — spawns `bgo logs <name> -f` in a new terminal
  window (live tail with formatting), not the raw log file in an
  editor.

**Global menu entries**:

- Resurrect all
- Refresh now
- Quit

## Click activation

- **Right-click** opens the menu (always; handled by Qt/host).
- **Left-click** and **middle-click** open the same menu, via Qt's
  `activated(Trigger / MiddleClick)` signal. Most hosts honor this;
  some KDE Plasma setups bind a custom left-click action that
  swallows it — in that case right-click still works.
- Set `BGO_TRAY_DEBUG=1` to log the activation reason to stderr.

## Open-logs terminal probe

Linux probes a curated list, picking the first one on `$PATH`:

```
kitty → alacritty → wezterm → foot → ghostty →
gnome-terminal → konsole → xfce4-terminal → tilix → xterm
```

macOS uses AppleScript to spawn Terminal.app. `BGO_TERMINAL=iterm`
switches macOS to iTerm2. For any other emulator:

```bash
export BGO_TERMINAL='kitty --'
export BGO_TERMINAL='alacritty -e'
export BGO_TERMINAL='weirdterm'    # defaults to -e exec flag
```

## Platform support

PySide6 (Qt for Python, LGPL) speaks the StatusNotifierItem (SNI)
protocol natively, so one library covers every target:

| Platform | What happens |
|---|---|
| macOS | Native `NSStatusItem` in the menu bar |
| KDE Plasma 6 (Wayland or X11) | SNI, no setup |
| Hyprland / sway + waybar | SNI via waybar's `tray` module |
| GNOME Wayland | Needs the AppIndicator shell extension |

### GNOME Wayland prerequisite

GNOME ships no system-tray host of its own. Install the
"AppIndicator and KStatusNotifierItem Support" shell extension once:

```bash
sudo dnf install gnome-shell-extension-appindicator   # Fedora
sudo apt install gnome-shell-extension-appindicator   # Debian/Ubuntu
gnome-extensions enable appindicatorsupport@rgcjonas.gmail.com
```

Log out and back in. KDE / Hyprland / macOS users do not need this.

## Install

The tray UI uses PySide6. It's shipped as an optional extra to keep
the core install zero-dep:

```bash
uv tool install bgo-cli --with PySide6     # uv (recommended)
pipx inject bgo-cli PySide6                # pipx
pip install 'bgo-cli[tray]'                # pip
```

If you forget, the first run of `bgo tray` detects your installer
(uv tool / pipx / pip) and offers to inject the dep for you. Skip
the confirmation with `--auto-install` or `BGO_TRAY_AUTOINSTALL=1`.

## Run the tray in the background

The tray is just another command — wrap it under `bgo`:

```bash
bgo start -w bgotray -- bgo tray     # -w auto-restarts on crash
```

Or, simpler, install it as a login autostart entry:

```bash
bgo autostart install --tray         # tray starts on every login
```

See [Login autostart](autostart.md) for details.

## Tuning

| Flag / env | Default | Effect |
|---|---|---|
| `--poll N`, `BGO_TRAY_POLL` | `3` | Snapshot refresh interval (seconds) |
| `--auto-install`, `BGO_TRAY_AUTOINSTALL=1` | off | Skip the install prompt |
| `BGO_TERMINAL` | (auto-probe) | Terminal emulator for Open-logs |
| `BGO_TRAY_DEBUG=1` | off | Log activation reasons to stderr |
