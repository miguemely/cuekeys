import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Firmware core is plain Python: import it straight from the source tree.
sys.path.insert(0, str(ROOT / "firmware" / "lib"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
