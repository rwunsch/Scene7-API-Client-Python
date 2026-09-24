"""Make client/scene7api.py importable as `scene7api` without packaging it."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "client"))
