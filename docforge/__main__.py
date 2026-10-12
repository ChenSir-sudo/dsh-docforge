"""``python3 -m docforge`` — same entry point as the ``docforge`` console script."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
