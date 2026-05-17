#!/usr/bin/env bash
#
# publish.sh — end-to-end PyPI release for bgo-cli
#
# Steps:
#   1. Read version from pyproject.toml
#   2. Verify pyproject.toml and src/bgo_cli/__init__.py versions match
#   3. Verify working tree is clean (or --allow-dirty)
#   4. Clean dist/, build sdist + wheel
#   5. twine check
#   6. twine upload (prompts unless TWINE_PASSWORD or ~/.pypirc set)
#   7. Smoke-test the live package in a throwaway venv
#   8. Tag v<version> and push
#
# Token resolution order:
#   - $TWINE_PASSWORD env var (with TWINE_USERNAME=__token__)
#   - ~/.pypirc [pypi] section
#   - interactive prompt from twine
#
# Flags:
#   --test            Upload to TestPyPI instead of PyPI
#   --skip-smoke      Skip the post-upload install test
#   --skip-tag        Don't tag/push after upload
#   --allow-dirty     Allow uncommitted changes (use with care)
#   --yes             Non-interactive — auto-confirm prompts
#   -h, --help

set -euo pipefail

# --- args ---
TEST=0
SKIP_SMOKE=0
SKIP_TAG=0
ALLOW_DIRTY=0
YES=0
for arg in "$@"; do
    case "$arg" in
        --test)        TEST=1 ;;
        --skip-smoke)  SKIP_SMOKE=1 ;;
        --skip-tag)    SKIP_TAG=1 ;;
        --allow-dirty) ALLOW_DIRTY=1 ;;
        --yes|-y)      YES=1 ;;
        -h|--help)
            sed -n '2,/^set -euo pipefail/p' "$0" | grep -E '^#' | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "unknown flag: $arg" >&2; exit 2 ;;
    esac
done

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO"

# --- helpers ---
say()  { echo -e "\033[1;36m[$(date +%H:%M:%S)]\033[0m $*"; }
ok()   { echo -e "\033[1;32m✓\033[0m $*"; }
err()  { echo -e "\033[1;31m✗\033[0m $*" >&2; }
confirm() {
    [[ $YES -eq 1 ]] && return 0
    read -r -p "$1 [y/N] " ans
    case "$ans" in y|Y|yes) return 0 ;; *) return 1 ;; esac
}

# --- preflight ---
say "preflight"

# venv
if [[ ! -x "${REPO}/.venv/bin/python" ]]; then
    say "creating .venv"
    uv venv .venv >/dev/null
    uv pip install --python .venv/bin/python build twine pytest >/dev/null
fi
PY="${REPO}/.venv/bin/python"

# version sync
PYPROJECT_V=$(grep -E '^version\s*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')
INIT_V=$(grep -E '^__version__' src/bgo_cli/__init__.py | sed -E 's/.*"([^"]+)".*/\1/')
if [[ "$PYPROJECT_V" != "$INIT_V" ]]; then
    err "version mismatch: pyproject.toml=${PYPROJECT_V}  __init__.py=${INIT_V}"
    exit 1
fi
VERSION="$PYPROJECT_V"
ok "version: ${VERSION}"

# working tree clean
if [[ $ALLOW_DIRTY -eq 0 ]]; then
    if [[ -n "$(git status --porcelain)" ]]; then
        err "working tree dirty — commit or pass --allow-dirty"
        git status --short
        exit 1
    fi
    ok "working tree clean"
fi

# tag doesn't already exist
if git rev-parse "v${VERSION}" >/dev/null 2>&1; then
    err "tag v${VERSION} already exists"
    if [[ $SKIP_TAG -eq 0 ]]; then
        echo "  re-run with --skip-tag if you've already tagged this version" >&2
        exit 1
    fi
fi

# --- tests ---
say "running tests"
$PY -m pytest tests/ -q
ok "tests passed"

# --- build ---
say "cleaning dist/"
rm -rf dist/ build/ src/*.egg-info/

say "building sdist + wheel"
$PY -m build

# --- verify ---
say "twine check"
$PY -m twine check dist/*
ok "metadata valid"

# show artifacts
echo
ls -lh dist/
echo

# confirm
if [[ $TEST -eq 1 ]]; then
    REPO_NAME="TestPyPI"
    UPLOAD_ARGS="--repository testpypi"
    INDEX_URL="--index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/"
else
    REPO_NAME="PyPI"
    UPLOAD_ARGS=""
    INDEX_URL=""
fi

confirm "upload bgo-cli ${VERSION} to ${REPO_NAME}?" || { echo "cancelled"; exit 0; }

# --- upload ---
say "uploading to ${REPO_NAME}"
# If TWINE_PASSWORD is set, also set TWINE_USERNAME to __token__ for convenience
if [[ -n "${TWINE_PASSWORD:-}" && -z "${TWINE_USERNAME:-}" ]]; then
    export TWINE_USERNAME=__token__
fi
# shellcheck disable=SC2086
$PY -m twine upload $UPLOAD_ARGS dist/*
ok "uploaded"

# --- smoke test ---
if [[ $SKIP_SMOKE -eq 0 ]]; then
    say "smoke-testing installed package"
    SMOKE_DIR=$(mktemp -d /tmp/bgo-smoke.XXXXXX)
    trap 'rm -rf "$SMOKE_DIR"' EXIT
    uv venv "$SMOKE_DIR/venv" >/dev/null

    # PyPI/TestPyPI takes a few seconds to propagate
    for i in 1 2 3 4 5 6; do
        # shellcheck disable=SC2086
        if uv pip install --python "$SMOKE_DIR/venv/bin/python" $INDEX_URL "bgo-cli==${VERSION}" >/dev/null 2>&1; then
            break
        fi
        say "not yet available, retrying (${i}/6)"
        sleep 5
    done

    "$SMOKE_DIR/venv/bin/bgo" --help >/dev/null
    INSTALLED_V=$("$SMOKE_DIR/venv/bin/python" -c "import bgo_cli; print(bgo_cli.__version__)")
    if [[ "$INSTALLED_V" != "$VERSION" ]]; then
        err "installed version ${INSTALLED_V} != expected ${VERSION}"
        exit 1
    fi
    ok "smoke test passed (bgo-cli ${INSTALLED_V})"
fi

# --- tag ---
if [[ $SKIP_TAG -eq 0 && $TEST -eq 0 ]]; then
    say "tagging v${VERSION}"
    git tag "v${VERSION}"
    git push origin "v${VERSION}"
    ok "tag pushed"
fi

echo
ok "released bgo-cli ${VERSION} to ${REPO_NAME}"
if [[ $TEST -eq 0 ]]; then
    echo "    https://pypi.org/project/bgo-cli/${VERSION}/"
else
    echo "    https://test.pypi.org/project/bgo-cli/${VERSION}/"
fi
