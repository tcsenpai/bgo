# Publishing bgo to PyPI

This repo is configured for two publish paths: **automated** (GitHub
Actions on tag push, via PyPI Trusted Publishing) and **manual** (local
`twine upload` for the first release or for emergency releases).

## One-time setup

### 1. Reserve the package name on PyPI

The PyPI distribution name is `bgo-cli` (the import name is `bgo_cli`,
the CLI command is `bgo`). Register the project under your account at
https://pypi.org if it doesn't exist yet, or do the first manual
upload (below) which creates it.

### 2. Configure Trusted Publishing (one-time, recommended)

Trusted Publishing replaces API tokens with OIDC. No long-lived
secret to rotate.

1. Go to https://pypi.org/manage/account/publishing/
2. Add a **pending publisher** with:
   - PyPI Project Name: `bgo-cli`
   - Owner: `tcsenpai`
   - Repository: `bgo`
   - Workflow filename: `publish.yml`
   - Environment name: `pypi`
3. In the GitHub repo Settings → Environments, create an environment
   named `pypi`.
4. From now on, pushing a `v*` tag triggers
   `.github/workflows/publish.yml`, which builds and uploads via OIDC.

## Releasing

### Automated (tag-based)

```bash
# 1. Bump the version (single source of truth — keep both in sync)
#    pyproject.toml :: [project] version
#    src/bgo_cli/__init__.py :: __version__
$EDITOR pyproject.toml src/bgo_cli/__init__.py

# 2. Update CHANGELOG / README if needed, commit
git add pyproject.toml src/bgo_cli/__init__.py
git commit -m "release: 0.2.1"

# 3. Tag and push
git tag v0.2.1
git push origin main --tags

# 4. GitHub Actions publishes to PyPI automatically.
#    Watch the run at: https://github.com/tcsenpai/bgo/actions
```

### Manual (first release, or override)

```bash
# Clean previous builds
rm -rf dist/ build/ src/*.egg-info/

# Build sdist + wheel
python -m build

# Verify metadata
python -m twine check dist/*

# Upload (will prompt for credentials or read from ~/.pypirc)
python -m twine upload dist/*
```

To test against TestPyPI first:

```bash
python -m twine upload --repository testpypi dist/*
pip install --index-url https://test.pypi.org/simple/ bgo-cli
```

## Verifying a release

After publish, verify in a clean environment:

```bash
python -m venv /tmp/bgo-verify
/tmp/bgo-verify/bin/pip install bgo-cli
/tmp/bgo-verify/bin/bgo --help
/tmp/bgo-verify/bin/python -c "import bgo_cli; print(bgo_cli.__version__)"
```

## Notes

- The wheel ships `bgo_cli/_core.py`, which is the root `bgo` script
  pulled in via hatchling's `force-include`. There is exactly one copy
  of the implementation in source control; the package layer is a thin
  re-exporter.
- The root `bgo` script remains the canonical single-file artifact for
  users who prefer `cp bgo /usr/local/bin/` or `install.sh`.
- `__version__` lives in `src/bgo_cli/__init__.py` and must match the
  `[project] version` field in `pyproject.toml`. The release commit
  must update both.
