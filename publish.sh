#!/usr/bin/env bash
#
# publish.sh — end-to-end PyPI release for bgo-cli
#
# Steps:
#   1. Read version from pyproject.toml + verify __init__.py matches
#   2. Bump version (interactive prompt unless --bump or --current given)
#   3. Verify working tree is clean (or --allow-dirty)
#   4. Run tests
#   5. Clean dist/, build sdist + wheel
#   6. twine check
#   7. twine upload (prompts unless TWINE_PASSWORD or ~/.pypirc set)
#   8. Smoke-test the live package in a throwaway venv
#   9. Tag v<version> and push
#
# Token resolution order:
#   - $TWINE_PASSWORD env var (with TWINE_USERNAME=__token__)
#   - ~/.pypirc [pypi] section
#   - interactive prompt from twine
#
# Flags:
#   --bump patch      Bump 0.2.0 -> 0.2.1 (semver patch)
#   --bump minor      Bump 0.2.0 -> 0.3.0
#   --bump major      Bump 0.2.0 -> 1.0.0
#   --bump X.Y.Z      Set explicit version
#   --current         Don't bump — release the current version as-is
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
BUMP=""
CURRENT=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --test)        TEST=1 ;;
        --skip-smoke)  SKIP_SMOKE=1 ;;
        --skip-tag)    SKIP_TAG=1 ;;
        --allow-dirty) ALLOW_DIRTY=1 ;;
        --yes|-y)      YES=1 ;;
        --current)     CURRENT=1 ;;
        --bump)        BUMP="${2:-}"; shift ;;
        --bump=*)      BUMP="${1#*=}" ;;
        -h|--help)
            sed -n '2,/^set -euo pipefail/p' "$0" | grep -E '^#' | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "unknown flag: $1" >&2; exit 2 ;;
    esac
    shift
done

if [[ -n "$BUMP" && $CURRENT -eq 1 ]]; then
    echo "--bump and --current are mutually exclusive" >&2
    exit 2
fi

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
CURRENT_VERSION="$PYPROJECT_V"
ok "current version: ${CURRENT_VERSION}"

# --- bump ---
# Compute next version. Sources: --bump <spec>, --current, or interactive prompt.
bump_semver() {
    # bump_semver <current> <patch|minor|major> -> echoes next
    local cur="$1" part="$2"
    if [[ ! "$cur" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
        echo "non-semver current version: ${cur} — use --bump X.Y.Z explicitly" >&2
        return 1
    fi
    local maj="${BASH_REMATCH[1]}" min="${BASH_REMATCH[2]}" pat="${BASH_REMATCH[3]}"
    case "$part" in
        patch) echo "${maj}.${min}.$((pat + 1))" ;;
        minor) echo "${maj}.$((min + 1)).0" ;;
        major) echo "$((maj + 1)).0.0" ;;
        *) echo "bad bump part: ${part}" >&2; return 1 ;;
    esac
}

resolve_next_version() {
    local cur="$1" spec="$2"
    # explicit X.Y.Z or X.Y.Z<suffix>
    if [[ "$spec" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-].+)?$ ]]; then
        echo "$spec"
        return
    fi
    # semver keyword
    case "$spec" in
        patch|minor|major) bump_semver "$cur" "$spec" ;;
        *) echo "invalid --bump value: ${spec}" >&2; return 1 ;;
    esac
}

if [[ $CURRENT -eq 1 ]]; then
    NEW_VERSION="$CURRENT_VERSION"
    say "releasing current version ${CURRENT_VERSION} (no bump)"
elif [[ -n "$BUMP" ]]; then
    NEW_VERSION=$(resolve_next_version "$CURRENT_VERSION" "$BUMP") || exit 1
    say "bumping ${CURRENT_VERSION} -> ${NEW_VERSION}  (via --bump ${BUMP})"
elif [[ $YES -eq 1 ]]; then
    err "non-interactive run (--yes) requires --bump or --current"
    exit 2
else
    PATCH_V=$(bump_semver "$CURRENT_VERSION" patch || echo "?")
    MINOR_V=$(bump_semver "$CURRENT_VERSION" minor || echo "?")
    MAJOR_V=$(bump_semver "$CURRENT_VERSION" major || echo "?")
    echo
    echo "current: ${CURRENT_VERSION}"
    echo
    echo "  1) patch   -> ${PATCH_V}"
    echo "  2) minor   -> ${MINOR_V}"
    echo "  3) major   -> ${MAJOR_V}"
    echo "  4) custom  -> enter X.Y.Z"
    echo "  5) current -> release ${CURRENT_VERSION} as-is (no bump)"
    echo "  q) quit"
    echo
    read -r -p "choice [1-5,q]: " choice
    case "$choice" in
        1|p|patch) NEW_VERSION="$PATCH_V" ;;
        2|m|minor) NEW_VERSION="$MINOR_V" ;;
        3|M|major) NEW_VERSION="$MAJOR_V" ;;
        4|c|custom)
            read -r -p "new version: " NEW_VERSION
            if [[ ! "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-].+)?$ ]]; then
                err "not a valid version: ${NEW_VERSION}"
                exit 1
            fi
            ;;
        5) NEW_VERSION="$CURRENT_VERSION" ;;
        q|Q) echo "cancelled"; exit 0 ;;
        *) err "invalid choice: ${choice}"; exit 1 ;;
    esac
fi

# Apply bump (if version actually changes)
if [[ "$NEW_VERSION" != "$CURRENT_VERSION" ]]; then
    say "updating version files"
    # pyproject.toml: version = "..."
    sed -i.bak -E "s/^version\s*=\s*\"[^\"]+\"/version = \"${NEW_VERSION}\"/" pyproject.toml
    # __init__.py: __version__ = "..."
    sed -i.bak -E "s/^__version__\s*=\s*\"[^\"]+\"/__version__ = \"${NEW_VERSION}\"/" src/bgo_cli/__init__.py
    rm -f pyproject.toml.bak src/bgo_cli/__init__.py.bak

    # Verify the edits actually took
    NEW_PY=$(grep -E '^version\s*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')
    NEW_INIT=$(grep -E '^__version__' src/bgo_cli/__init__.py | sed -E 's/.*"([^"]+)".*/\1/')
    if [[ "$NEW_PY" != "$NEW_VERSION" || "$NEW_INIT" != "$NEW_VERSION" ]]; then
        err "version edit failed: pyproject=${NEW_PY} init=${NEW_INIT}"
        exit 1
    fi
    ok "version bumped to ${NEW_VERSION}"

    # Commit the bump
    if confirm "commit version bump ${CURRENT_VERSION} -> ${NEW_VERSION}?"; then
        git add pyproject.toml src/bgo_cli/__init__.py
        git commit -m "release: ${NEW_VERSION}"
        ok "bump committed"
    else
        err "version files modified but commit skipped — tree will be dirty"
        if [[ $ALLOW_DIRTY -eq 0 ]]; then
            echo "  use --allow-dirty if intentional" >&2
            exit 1
        fi
    fi
fi

VERSION="$NEW_VERSION"

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
