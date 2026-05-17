"""Allow `python -m bgo_cli` invocation."""

import sys

from bgo_cli import main

if __name__ == "__main__":
    sys.exit(main())
