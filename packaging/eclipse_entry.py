"""PyInstaller entry point for the Eclipse executable."""

import sys

from eclipse_agent.main import main

if __name__ == "__main__":
    sys.exit(main())
