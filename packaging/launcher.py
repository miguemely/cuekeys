# SPDX-License-Identifier: LicenseRef-CueKeys-Source-Available-Reciprocal-1.0
"""Entry point for the PyInstaller desktop build (opens the editor by default)."""

import sys

from cuekeys.cli import main

if __name__ == "__main__":
    sys.exit(main())
