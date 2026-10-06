"""Run the simulator as a package: python -m airlanes <map>."""

import sys

from airlanes.cli import main

if __name__ == "__main__":
    sys.exit(main())
