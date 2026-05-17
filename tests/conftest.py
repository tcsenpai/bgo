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
    """Fresh bgo module with sandboxed ~/.bgo pointing into tmp_path."""
    sandbox = tmp_path / "bgo_home"
    sandbox.mkdir()
    monkeypatch.setenv("HOME", str(sandbox))
    if "bgo_mod" in sys.modules:
        del sys.modules["bgo_mod"]
    mod = _load_bgo()
    mod.BGO_DIR = sandbox / ".bgo"
    mod.PROCS_DIR = mod.BGO_DIR / "procs"
    mod.LOGS_DIR = mod.BGO_DIR / "logs"
    mod.init_dirs()
    return mod
