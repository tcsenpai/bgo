# Architecture

bgo started as a single-file Python script. Over time the optional
features (notifications, autostart, tray) demanded proper modules. As
of the `dev`-branch refactor, the source split is:

```
bgo                         # entry script — argparse + cmd_* handlers
src/bgo_cli/
  __init__.py               # package shim; force-include target for wheels
  __main__.py               # `python -m bgo_cli` -> main()
  _term.py                  # ANSI colors, glyphs, table-level detection
  _state.py                 # proc JSON I/O, dir layout
  _proc.py                  # PID checks, kill_process, ps batch
  _watcher.py               # watch loop + helpers
  _notify.py                # desktop notifications
  _autostart.py             # systemd-user / launchd install
  _tray.py                  # PySide6 tray icon
  _tray_install.py          # uv/pipx/pip auto-install of PySide6
tests/
  conftest.py               # bgo module loader + sandbox fixture
  test_*.py                 # 169 tests
```

## Module dependency graph

```
        ┌─────────┐
        │ _term   │  (no deps)
        └────┬────┘
             │
        ┌────┴────┐
        │ _proc   │  (uses _term for one error message)
        └────┬────┘
             │
        ┌────┴────┐         ┌─────────┐
        │ _state  │         │ _notify │  (no deps)
        └────┬────┘         └────┬────┘
             │                   │
             └─────────┬─────────┘
                       │
                  ┌────┴────┐
                  │_watcher │  (lazy-imports _notify)
                  └────┬────┘
                       │
                  ┌────┴────┐    ┌────────────┐    ┌──────────────┐
                  │ bgo     │    │ _autostart │    │ _tray /      │
                  │ (cmd_*) │    │            │    │ _tray_install│
                  └─────────┘    └────────────┘    └──────────────┘
```

Cycles are forbidden. `_notify` and the tray modules are lazy-imported
from inside the script so missing optional deps never break a fresh
install.

## Storage layout

```
~/.bgo/
├── procs/
│   ├── web.json          # one file per registered proc
│   ├── api.json
│   └── …
└── logs/
    ├── web.out.log       # stdout
    ├── web.err.log       # stderr
    ├── web.watcher.log   # watcher event log
    ├── api.out.log
    └── …
```

Writes go through `save_proc` which uses tmp-file + `os.replace` for
atomicity. The watcher and the CLI can race writes safely.

## The `bgo` script

The root script is both:

1. The user-facing executable on `$PATH`.
2. The force-included `_core.py` payload in the wheel (see
   `pyproject.toml` `[tool.hatch.build.targets.wheel.force-include]`).

It owns the argparse setup, direct-mode parsing (e.g. `bgo myapp --
node server.js` without `start`), and the `cmd_*` handlers. The
handlers shell out to the modules above for state, processes, and
external features.

## Watcher protocol

When `bgo start -w …` (or `bgo watch …`) registers a watch block,
the script spawns:

```
$SHELL_OF_BGO bgo __watcher__ <name>
```

…as a detached subprocess (`start_new_session=True`). The watcher's
PID is recorded in `info["watch"]["watcher_pid"]`. The watcher polls
the target every `interval` seconds, computes uptime from
`started_at`, and reacts to crashes per the `on_fast_crash` policy.

On any errored transition the watcher fires a desktop notification
via `bgo_cli._notify` and exits.

See [Watch mode](watch-mode.md) for the user-facing surface and
fast-crash policy details.

## Tests

`tests/conftest.py` exposes a `bgo` fixture that loads the bare
script via `importlib.util.spec_from_loader` and sandboxes `~/.bgo/`
into a `tmp_path` directory. Tests for the modules import them
directly (`from bgo_cli import _notify`), so they don't pay the
script-load cost.

```bash
uv run pytest tests/                    # all 169 tests
uv run pytest tests/test_notify.py -v   # one module
```

## Future work

- Extract `cmd_*` handlers from the root script into
  `bgo_cli._commands` (tracked in
  [#6 (partial)](https://github.com/tcsenpai/bgo/issues/6)).
  Status rendering, the interactive multiselect, and the argparse
  front-end can follow.
- mypy/pyright strict pass over the script (modules already type-clean).
