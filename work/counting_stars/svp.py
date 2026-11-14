"""Compatibility exports for the original Counting Stars script imports."""

import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from svp_alignment.svp import (BLICK_PER_SECOND, read_svp, song_notes, note_times, write_svp)

__all__ = ["BLICK_PER_SECOND","read_svp","song_notes","note_times","write_svp"]
