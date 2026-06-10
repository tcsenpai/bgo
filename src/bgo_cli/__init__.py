"""bgo — lightweight background process manager.

The actual implementation lives in the single-file `bgo` script at
the repo root, which doubles as the canonical source-of-truth for
the executable. At build time, hatchling pulls it into this package
as `bgo_cli._core` via the `force-include` configuration in
pyproject.toml.

For development (editable installs and bare `python -m bgo_cli`
inside the repo), we load it dynamically so the dev tree doesn't
need to mirror the script.
"""

from pathlib import Path
import importlib.machinery
import importlib.util
import sys

__version__ = "0.4.0"


def _load_core():
    """Resolve and load the underlying bgo script as a module."""
    # 1. Built / installed: src/bgo_cli/_core.py exists alongside this file.
    here = Path(__file__).resolve().parent
    packaged = here / "_core.py"
    if packaged.exists():
        spec = importlib.util.spec_from_file_location("bgo_cli._core", packaged)
    else:
        # 2. Editable / source checkout: walk up to the repo root, find ./bgo.
        repo_root = here.parent.parent
        candidate = repo_root / "bgo"
        if not candidate.exists():
            raise ImportError(
                "Cannot locate bgo core module — neither "
                f"{packaged} nor {candidate} exists."
            )
        spec = importlib.util.spec_from_loader(
            "bgo_cli._core",
            importlib.machinery.SourceFileLoader("bgo_cli._core", str(candidate)),
        )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bgo_cli._core"] = mod
    spec.loader.exec_module(mod)
    return mod


_core = _load_core()
main = _core.main

__all__ = ["main", "__version__"]
