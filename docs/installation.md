# Installation

bgo is a single-file Python 3.10+ script with zero runtime
dependencies. Several install paths exist; pick the one that matches
how you usually install Python CLIs.

## Recommended: `uv`

[uv](https://docs.astral.sh/uv/) installs bgo into an isolated
environment and links the `bgo` command onto your `$PATH`. No global
Python pollution, no virtualenv to manage manually.

```bash
uv tool install bgo-cli
uv tool upgrade bgo-cli
uv tool uninstall bgo-cli
```

To pre-include the optional [tray](tray.md) extra:

```bash
uv tool install bgo-cli --with PySide6
```

## pipx

```bash
pipx install bgo-cli
pipx inject bgo-cli PySide6   # for tray (optional)
pipx upgrade bgo-cli
pipx uninstall bgo-cli
```

## Plain pip

```bash
pip install bgo-cli            # global / current env
pip install 'bgo-cli[tray]'    # with tray extra
pip install --user bgo-cli     # user site-packages
```

## install.sh (no PyPI)

The `install.sh` shipped in the repo copies the single-file `bgo`
script to a target directory. No build, no Python packaging.

```bash
./install.sh             # /usr/local/bin (needs sudo)
./install.sh --local     # ~/.local/bin (no sudo)
./install.sh --help      # --force / --uninstall
```

## Fully manual

Because `bgo` is a single executable Python file:

```bash
cp bgo ~/.local/bin/                       # or any PATH dir
ln -s "$(pwd)/bgo" ~/.local/bin/bgo        # symlink to a checkout
```

## Verify

```bash
bgo --help
bgo ls         # no procs registered yet
```

## Requirements

- Python 3.10+
- Linux or macOS (zombie detection is platform-aware: `/proc` on
  Linux, `ps -o stat=` on macOS)
- Optional `[tray]` extra: PySide6 (Qt for Python, LGPL)

## Next

- [Commands](commands.md) — what to actually run.
- [Watch mode](watch-mode.md) — auto-restart on crash.
- [Tray icon](tray.md) — the optional GUI.
