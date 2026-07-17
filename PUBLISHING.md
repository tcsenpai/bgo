# Publishing bgo to PyPI

Manual, token-based release. CI runs tests + builds on every push to
`main` (`.github/workflows/test.yml`) but does **not** auto-publish.
Releases go out via `./publish.sh`.

## One-time setup

The PyPI distribution name is `bgo-cli` (the import name is `bgo_cli`,
the CLI command is `bgo`). The first `twine upload` creates the
project under your PyPI account.

### Credentials

Pick one — `publish.sh` resolves in this order:

**Option A — environment variable (one-shot)**
```bash
TWINE_PASSWORD=pypi-AgEI...your-token ./publish.sh --yes
```

**Option B — `~/.pypirc` (persistent)**
```ini
[pypi]
  username = __token__
  password = pypi-AgEI...your-full-token-here

[testpypi]
  repository = https://test.pypi.org/legacy/
  username = __token__
  password = pypi-AgEI...your-testpypi-token
```
Then `chmod 600 ~/.pypirc`.

**Option C — interactive**
Run `./publish.sh` and twine prompts for username (`__token__`) and
password (the token).

## Releasing

### Standard flow

```bash
# Interactive — script prompts for the version bump
./publish.sh

# Or non-interactive with an explicit bump
./publish.sh --bump patch --yes      # 0.2.0 -> 0.2.1
./publish.sh --bump minor --yes      # 0.2.0 -> 0.3.0
./publish.sh --bump major --yes      # 0.2.0 -> 1.0.0
./publish.sh --bump 0.5.0 --yes      # explicit X.Y.Z

# Or skip the bump and release the current version as-is
./publish.sh --current --yes
```

`publish.sh` does (in order):
1. Verify pyproject.toml and __init__.py versions match
2. **Bump the version** (interactive prompt: patch/minor/major/custom/current/quit, or via `--bump`/`--current`). Edits both files and commits `release: <new-version>`.
3. Verify working tree is clean (use `--allow-dirty` to override)
4. Verify `v<version>` tag doesn't already exist
5. Run pytest
6. Clean `dist/` and run `python -m build`
7. `twine check` both artifacts
8. Confirm with you (skip with `--yes`)
9. `twine upload`
10. Smoke-test in a throwaway venv (skip with `--skip-smoke`)
11. `git tag v<version> && git push origin v<version>` (skip with `--skip-tag`)

The script will refuse `--yes` without `--bump` or `--current` — explicit intent required for non-interactive runs.

### TestPyPI first (optional)

```bash
./publish.sh --test
```

Uploads to https://test.pypi.org/ instead. Skips the git tag step
automatically.

### Flag reference

| Flag | Effect |
|---|---|
| `--bump patch\|minor\|major` | Semver bump |
| `--bump X.Y.Z` | Explicit version |
| `--current` | Don't bump, release current version |
| `--test` | TestPyPI instead of PyPI; also implies `--skip-tag` |
| `--skip-smoke` | Don't install + smoke-test after upload |
| `--skip-tag` | Don't `git tag` + push |
| `--allow-dirty` | Allow uncommitted changes (use with care) |
| `--yes` / `-y` | Non-interactive — auto-confirm prompts (requires `--bump` or `--current`) |

## Manual fallback (without the script)

If `publish.sh` is unavailable or you need to do something it doesn't
support:

```bash
rm -rf dist/ build/ src/*.egg-info/
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
.venv/bin/python -m twine upload dist/*       # or --repository testpypi
```

## Verifying a release

```bash
uv venv /tmp/bgo-verify
uv pip install --python /tmp/bgo-verify/bin/python bgo-cli
/tmp/bgo-verify/bin/bgo --help
/tmp/bgo-verify/bin/python -c "import bgo_cli; print(bgo_cli.__version__)"
rm -rf /tmp/bgo-verify
```

(`publish.sh` runs this automatically unless `--skip-smoke`.)

## Notes

- The wheel ships `bgo_cli/_core.py`, which is the root `bgo` script
  pulled in via hatchling's `force-include`. Exactly one copy of the
  implementation in source control; the package layer is a thin
  re-exporter.
- The root `bgo` script is the canonical source of the implementation,
  but it is not standalone-runnable: it imports the `bgo_cli` package.
  Users install the package instead — from PyPI, or via `install.sh`
  (which wraps `uv tool` / `pipx` / `pip --user`). `cp bgo
  /usr/local/bin/` produces a broken binary and must not be advertised.
- `__version__` lives in `src/bgo_cli/__init__.py` and must match the
  `[project] version` field in `pyproject.toml`. `publish.sh` refuses
  to run if they drift.
- Future option: re-enable automated publishing via PyPI Trusted
  Publishing (OIDC, no long-lived secret) — see
  https://docs.pypi.org/trusted-publishers/ and add a workflow at
  `.github/workflows/publish.yml`.
