# bgo documentation

Welcome to the bgo wiki. This folder is the canonical place for
long-form documentation; the [project root README](../README.md) is a
quickstart and feature overview that links here for detail.

## Contents

### Getting started

- **[Installation](installation.md)** — uv (recommended), pipx, pip,
  install.sh, source checkout.
- **[Commands](commands.md)** — full CLI reference: lifecycle,
  inspection, watch mode, autostart, tray.

### Features

- **[Watch mode](watch-mode.md)** — auto-restart on crash, fast-crash
  policy (`backoff` / `stop` / `retry`), tunables.
- **[Desktop notifications](notifications.md)** — fired on errored
  state transitions. Zero-dep, native per-platform backends.
- **[Login autostart](autostart.md)** — systemd user units on Linux,
  LaunchAgents on macOS. Brings procs back after reboot.
- **[Tray icon](tray.md)** — PySide6 system-tray icon with gear+dot
  status indicator. Works on KDE / Hyprland / GNOME (with extension)
  / macOS.

### Reference

- **[Architecture](architecture.md)** — module layout, where each
  concern lives, the watcher protocol.
- **[FAQ](faq.md)** — common questions and gotchas.
- **[Contributing](contributing.md)** — dev setup, test loop, where to
  send patches.

## License

[MIT](../LICENSE).
