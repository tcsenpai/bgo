#!/usr/bin/env bash
#
# bgo installer
#
# Installs the bgo-cli package (which provides the `bgo` command)
# with the first available Python packaging tool:
#
#     1. uv tool install        (https://docs.astral.sh/uv/)
#     2. pipx install           (https://pipx.pypa.io/)
#     3. python3 -m pip install --user
#
# Run from inside the repo checkout  -> installs from local source.
# Run from anywhere else             -> installs `bgo-cli` from PyPI.
#
# All three put `bgo` in a user bin dir (typically ~/.local/bin), so no
# sudo is needed. Idempotent: re-run with --force to reinstall over an
# existing install. Does NOT touch ~/.bgo/ (procs/logs) so process
# state survives upgrade.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- args ---
FORCE=0
UNINSTALL=0
for arg in "$@"; do
    case "$arg" in
        --local)     : ;;   # legacy flag: installs are always user-local now
        --force|-f)  FORCE=1 ;;
        --uninstall) UNINSTALL=1 ;;
        -h|--help)
            cat <<EOF
bgo installer

Installs the bgo-cli package, which provides the `bgo` command.
Uses the first available tool: uv, then pipx, then pip --user.
Run from inside the repo to install from local source; otherwise
the latest release is installed from PyPI.

Usage:
    ./install.sh              # install for the current user (no sudo)
    ./install.sh --force      # reinstall over an existing install
    ./install.sh --uninstall  # remove the installed package
    ./install.sh --local      # legacy no-op (installs are always user-local)

Combine flags as needed, e.g.  ./install.sh --force
EOF
            exit 0
            ;;
        *)
            echo "unknown option: $arg" >&2
            echo "run ./install.sh --help" >&2
            exit 2
            ;;
    esac
done

# --- source ---
# Inside the repo (or an unpacked sdist) install from local source;
# otherwise pull the release from PyPI.
if [[ -f "${SCRIPT_DIR}/pyproject.toml" && -d "${SCRIPT_DIR}/src/bgo_cli" ]]; then
    SOURCE="$SCRIPT_DIR"
    SOURCE_DESC="local source ($SOURCE)"
else
    SOURCE="bgo-cli"
    SOURCE_DESC="PyPI (bgo-cli)"
fi

# --- pick an installer ---
if command -v uv >/dev/null 2>&1; then
    INSTALLER="uv"
elif command -v pipx >/dev/null 2>&1; then
    INSTALLER="pipx"
elif command -v python3 >/dev/null 2>&1; then
    INSTALLER="pip"
else
    echo "no supported installer found." >&2
    echo "install uv (https://docs.astral.sh/uv/) or pipx (https://pipx.pypa.io/)," >&2
    echo "or make sure python3 with pip is available." >&2
    exit 1
fi

# --- uninstall path ---
if [[ $UNINSTALL -eq 1 ]]; then
    echo "uninstalling bgo-cli with $INSTALLER"
    case "$INSTALLER" in
        uv)   uv tool uninstall bgo-cli ;;
        pipx) pipx uninstall bgo-cli ;;
        pip)  python3 -m pip uninstall -y bgo-cli ;;
    esac
    echo "uninstalled"
    exit 0
fi

# --- preflight ---
# uv and pipx manage their own interpreters; the pip fallback relies on
# the system python3, which must satisfy requires-python (>= 3.10).
if [[ "$INSTALLER" == "pip" ]]; then
    if ! python3 -c 'import sys; assert sys.version_info >= (3, 10)' 2>/dev/null; then
        echo "error: bgo-cli requires Python >= 3.10." >&2
        echo "upgrade python3, or install uv / pipx and re-run." >&2
        exit 1
    fi
    if ! python3 -m pip --version >/dev/null 2>&1; then
        echo "error: python3 has no pip module." >&2
        echo "install uv (https://docs.astral.sh/uv/) or pipx (https://pipx.pypa.io/) and re-run." >&2
        exit 1
    fi
fi

# --- install ---
case "$INSTALLER" in
    uv)
        CMD=(uv tool install)
        [[ $FORCE -eq 1 ]] && CMD+=(--force)
        ;;
    pipx)
        CMD=(pipx install)
        [[ $FORCE -eq 1 ]] && CMD+=(--force)
        ;;
    pip)
        CMD=(python3 -m pip install --user)
        [[ $FORCE -eq 1 ]] && CMD+=(--force-reinstall)
        ;;
esac
CMD+=("$SOURCE")

echo "installing bgo from $SOURCE_DESC with $INSTALLER"
if ! "${CMD[@]}"; then
    echo >&2
    echo "install failed." >&2
    if [[ $FORCE -eq 0 ]]; then
        echo "if bgo is already installed, re-run with --force to reinstall." >&2
    fi
    exit 1
fi

echo "installed bgo ($INSTALLER)"

# --- legacy copy check ---
# Older install.sh copied the bare repo-root `bgo` script into a bin
# dir. That copy no longer works standalone (it imports the bgo_cli
# package) and, sitting in /usr/local/bin, it shadows the fresh
# user-local install. Warn only -- removing it needs sudo.
if [[ -f "${SCRIPT_DIR}/bgo" && -f /usr/local/bin/bgo ]] \
    && cmp -s "${SCRIPT_DIR}/bgo" /usr/local/bin/bgo; then
    echo
    echo "warning: /usr/local/bin/bgo is a stale copy left by an older install.sh."
    echo "it cannot run without the bgo_cli package and shadows this install."
    echo "remove it with:  sudo rm /usr/local/bin/bgo"
fi

# --- PATH check ---
if ! command -v bgo >/dev/null 2>&1; then
    echo
    echo "warning: the 'bgo' command is not on your PATH yet."
    case "$INSTALLER" in
        uv)   echo "run 'uv tool update-shell', or add ~/.local/bin to your PATH." ;;
        pipx) echo "run 'pipx ensurepath', or add ~/.local/bin to your PATH." ;;
        pip)
            echo "add your Python user bin dir to your PATH, e.g.:"
            echo "    export PATH=\"\$(python3 -m site --user-base)/bin:\$PATH\""
            ;;
    esac
fi

# --- version probe ---
if command -v bgo >/dev/null 2>&1; then
    echo
    bgo --help 2>&1 | head -1 || true
fi
