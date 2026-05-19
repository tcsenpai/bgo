"""Test bootstrap.

bgo is a single-file executable with no .py extension. Load it as a
module via importlib so tests can import its functions directly, and
sandbox ~/.bgo into a tmpdir so test runs cannot stomp on a real
~/.bgo/ on the developer's machine.
"""

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BGO_PATH = ROOT / "bgo"
SRC_PATH = ROOT / "src"

# Make `from bgo_cli import ...` resolvable during pytest collection,
# before any test module is imported. CI runs `python -m pytest` from
# the repo root without installing the package, so without this the
# test_*.py modules that import bgo_cli fail at collection time.
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


def _load_bgo():
    spec = importlib.util.spec_from_loader(
        "bgo_mod",
        importlib.machinery.SourceFileLoader("bgo_mod", str(BGO_PATH)),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def bgo(monkeypatch, tmp_path):
    """Fresh bgo module with sandboxed ~/.bgo pointing into tmp_path.

    State paths now live in ``bgo_cli._state`` (post-modularization).
    Patching both the script module *and* the state module keeps tests
    that read either path consistent.
    """
    sandbox = tmp_path / "bgo_home"
    sandbox.mkdir()
    monkeypatch.setenv("HOME", str(sandbox))
    if "bgo_mod" in sys.modules:
        del sys.modules["bgo_mod"]
    mod = _load_bgo()
    bgo_dir = sandbox / ".bgo"
    procs_dir = bgo_dir / "procs"
    logs_dir = bgo_dir / "logs"
    # Patch both the script's re-exported names AND the source module
    # so any code path that resolves via either binding sees the same
    # sandbox.
    for target in (mod, sys.modules.get("bgo_cli._state")):
        if target is None:
            continue
        target.BGO_DIR = bgo_dir
        target.PROCS_DIR = procs_dir
        target.LOGS_DIR = logs_dir
    mod.init_dirs()
    return mod
