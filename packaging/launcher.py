"""Entry point for the PyInstaller desktop build (opens the editor by default)."""

import sys

from pmk_macro_manager.cli import main

if __name__ == "__main__":
    sys.exit(main())
