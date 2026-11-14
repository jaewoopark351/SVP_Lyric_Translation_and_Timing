"""Compatibility exports for the original Counting Stars script imports."""

import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from svp_alignment.verification.reporting import (CHORUS_RANGES, LARGE_ERROR_MS, write_csv, time_summary, lyric_rows, markdown)

__all__ = ["CHORUS_RANGES","LARGE_ERROR_MS","write_csv","time_summary","lyric_rows","markdown"]
