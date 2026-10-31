#!/usr/bin/env python3
"""Run the homelab status collector directly from a source checkout."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from homelab_status.collector import main


if __name__ == "__main__":
    main()
