"""Compatibility entry point for the original Counting Stars CLI."""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from svp_alignment.cli import main
from svp_alignment.legacy import prepare, run
from svp_alignment.profiles.counting_stars import ROOT, SOURCE, PROJECT, TARGET, NOTES, LYRICS, REPORT


if __name__ == "__main__":
    main()
