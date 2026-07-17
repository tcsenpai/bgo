# Installation

bgo is a Python 3.10+ package (`bgo-cli`) with zero runtime
dependencies. Installing the package puts the `bgo` command on your
`$PATH`. Several install paths exist; pick the one that matches
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

## install.sh

The `install.sh` shipped in the repo installs the package for you,
picking the first available tool — `uv tool install`, then `pipx`,
then `pip --user`. Run from inside the repo it installs from local
source; run from anywhere else it installs the `bgo-cli` release
from PyPI. No sudo needed.

```bash
./install.sh              # install for the current user
./install.sh --force      # reinstall over an existing install
./install.sh --uninstall  # remove the installed package
./install.sh --help       # all flags
```

## From a source checkout

To install from a clone (e.g. to hack on bgo):

```bash
git clone https://github.com/tcsenpai/bgo.git
cd bgo
uv tool install .            # or: pipx install . / pip install --user .
```

> Note: the repo-root `bgo` script is **not** standalone — it imports
> the `bgo_cli` package at startup. Copying it into a bin dir
> (`cp bgo ~/.local/bin/`) produces a broken binary; always install
> the package.

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
