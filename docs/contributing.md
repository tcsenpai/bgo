# Contributing

## Dev setup

```bash
git clone https://github.com/tcsenpai/bgo.git
cd bgo
uv sync --extra dev --extra tray
```

`--extra dev` pulls pytest, build, twine. `--extra tray` pulls
PySide6 so you can develop the tray module without a separate install.

## Running

The root `bgo` script is the canonical executable. From the repo:

```bash
./bgo --help
./bgo status
```

To run via the installed wheel (matches end-user experience):

```bash
uv tool install -e . --with PySide6
bgo --help
```

The `-e` flag is editable — edits to source land immediately, no
re-install needed unless `pyproject.toml` changes.

## Tests

```bash
uv run pytest tests/ -q              # all tests
uv run pytest tests/test_tray.py -v  # one module
uv run pytest -k notify              # by keyword
```

All 169 tests should pass before opening a PR. The tray's PySide6
event loop is intentionally not unit-tested (Qt internals); the
toolkit-agnostic helpers (`build_menu_spec`, `_status_label`,
`_status_glyph`, `_aggregate_status`, `_icon_svg`) are.

## Linting / types

No required linter is wired into CI yet. The newer modules
(`_notify`, `_autostart`, `_tray*`, `_term`, `_state`, `_proc`,
`_watcher`) are strictly typed and aim for mypy-clean — please keep
new code at that bar.

The remaining cmd_* handlers in the root `bgo` script were typed in
the [#5 sweep](https://github.com/tcsenpai/bgo/issues/5) — every
`cmd_*` signature is `(args: argparse.Namespace) -> int` with
docstrings describing inputs / behavior / exit codes.

## Project structure

See [Architecture](architecture.md).

## Releasing

The repo includes `publish.sh` for version bumps and PyPI publishes.
See `PUBLISHING.md` (root) for the full flow. PRs should not bump
the version — leave that to the maintainer.

## Commit style

Conventional Commits, single line subject ≤ 72 chars, body explains
*why* not *what*. Imperative mood (`add X`, not `added X`).

## Where to send patches

- Bugs and features: GitHub issues at `tcsenpai/bgo`.
- PRs: `dev` branch (not `main`); main is reserved for releases.
- Security: open a private security advisory in the GitHub UI rather
  than a public issue.
