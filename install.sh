#!/usr/bin/env bash
#
# bgo installer
#
# Default:  /usr/local/bin/bgo   (requires sudo)
# --local:  ~/.local/bin/bgo     (no sudo)
#
# Idempotent: re-runs replace the existing binary. Does NOT touch
# ~/.bgo/ (procs/logs) so process state survives upgrade.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="${SCRIPT_DIR}/bgo"

# --- args ---
LOCAL=0
FORCE=0
UNINSTALL=0
for arg in "$@"; do
    case "$arg" in
        --local)     LOCAL=1 ;;
        --force|-f)  FORCE=1 ;;
        --uninstall) UNINSTALL=1 ;;
        -h|--help)
            cat <<EOF
bgo installer

Usage:
    ./install.sh              # install to /usr/local/bin (needs sudo)
    ./install.sh --local      # install to ~/.local/bin
    ./install.sh --force      # overwrite without prompting
    ./install.sh --uninstall  # remove installed binary

Combine flags as needed, e.g.  ./install.sh --local --force
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

# --- target ---
if [[ $LOCAL -eq 1 ]]; then
    TARGET_DIR="${HOME}/.local/bin"
    SUDO=""
else
    TARGET_DIR="/usr/local/bin"
    if [[ $EUID -eq 0 ]]; then
        SUDO=""
    else
        SUDO="sudo"
    fi
fi
TARGET="${TARGET_DIR}/bgo"

# --- uninstall path ---
if [[ $UNINSTALL -eq 1 ]]; then
    if [[ ! -e "$TARGET" ]]; then
        echo "bgo not installed at $TARGET"
        exit 0
    fi
    echo "removing $TARGET"
    $SUDO rm -f "$TARGET"
    echo "uninstalled"
    exit 0
fi

# --- preflight ---
if [[ ! -f "$SOURCE" ]]; then
    echo "source bgo binary not found at $SOURCE" >&2
    exit 1
fi
if ! python3 -c 'import sys; assert sys.version_info >= (3,9)' 2>/dev/null; then
    echo "warning: python3 >= 3.9 not detected. bgo uses 3.9+ syntax (PEP 604 union types)." >&2
fi

# --- install ---
mkdir -p "$TARGET_DIR" 2>/dev/null || $SUDO mkdir -p "$TARGET_DIR"

if [[ -e "$TARGET" && $FORCE -eq 0 ]]; then
    EXISTING_SIZE=$(stat -c%s "$TARGET" 2>/dev/null || stat -f%z "$TARGET" 2>/dev/null || echo "?")
    SOURCE_SIZE=$(stat -c%s "$SOURCE" 2>/dev/null || stat -f%z "$SOURCE" 2>/dev/null || echo "?")
    echo "existing: $TARGET ($EXISTING_SIZE bytes)"
    echo "new:      $SOURCE ($SOURCE_SIZE bytes)"
    read -r -p "overwrite? [y/N] " ans
    case "$ans" in
        y|Y|yes) ;;
        *) echo "cancelled"; exit 0 ;;
    esac
fi

$SUDO install -m 0755 "$SOURCE" "$TARGET"

echo "installed bgo -> $TARGET"

# --- PATH check ---
if ! command -v bgo >/dev/null 2>&1; then
    echo
    echo "warning: $TARGET_DIR is not on your PATH."
    if [[ $LOCAL -eq 1 ]]; then
        echo "add this to your shell rc:"
        echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi
fi

# --- version probe ---
if command -v bgo >/dev/null 2>&1; then
    echo
    bgo --help 2>&1 | head -1 || true
fi
